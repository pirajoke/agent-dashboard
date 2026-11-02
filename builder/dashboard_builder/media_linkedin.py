"""«Медиа» tab: owner-only bridge to the AI Singularity news service (LinkedIn via Buffer).

The news service owns publishing, deduplication and limits. This module only
forwards the owner's reads and actions to its scoped `/media-control` API with the
same dedicated token Jarvis uses. Nothing here stores news, posts or the token.
"""
from __future__ import annotations

import json
import os
import re
import stat
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ALLOWED_ORIGINS = {"http://127.0.0.1:8790", "https://singularity.meshly.fr"}
TIME_RE = re.compile(r"^([01]?\d|2[0-3]):[0-5]\d$")
MAX_BATCH = 10
POSTS_PER_DAY_RANGE = (1, 10)
MAX_INSTRUCTION = 300
MAX_POST_TEXT = 3000
MAX_COMMENT = 1250
MAX_SOURCE_TEXT = 8000
SHA_RE = re.compile(r"^[a-f0-9]{64}$")
LINKEDIN_POST_RE = re.compile(r"^https://([a-z]{2,3}\.|www\.)?linkedin\.com/\S{1,2000}$")


class MediaUnavailable(RuntimeError):
    """The news service is not configured or did not answer."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # never follow: the token must not leave
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def news_config(home: Path | None = None) -> tuple[str, str] | None:
    """Origin and token, from the environment or Jarvis' protected news-control.json."""
    origin = os.environ.get("JARVIS_NEWS_URL", "").rstrip("/")
    token = os.environ.get("JARVIS_NEWS_CONTROL_TOKEN", "")
    if not origin and not token:
        path = (home or Path.home()) / ".config" / "jarvis" / "news-control.json"
        try:
            info = path.lstat()
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                    or stat.S_IMODE(info.st_mode) != 0o600):
                return None
            data = json.loads(path.read_text())
            origin, token = str(data["origin"]).rstrip("/"), str(data["token"])
        except (OSError, ValueError, KeyError, TypeError):
            return None
    if origin not in ALLOWED_ORIGINS or len(token) < 32:
        return None
    return origin, token


def call(method: str, path: str, body: dict | None = None, *, timeout: float = 30,
         home: Path | None = None) -> tuple[int, dict]:
    config = news_config(home)
    if config is None:
        raise MediaUnavailable("not_configured")
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(
        config[0] + path, data=data, method=method,
        headers={"Authorization": "Bearer " + config[1], "Content-Type": "application/json",
                 "Accept": "application/json"})
    try:
        with _OPENER.open(request, timeout=timeout) as response:
            return response.status, json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as error:
        try:
            payload = json.loads(error.read() or b"{}")
        except ValueError:
            payload = {}
        return error.code, payload if isinstance(payload, dict) else {}
    except (OSError, ValueError) as error:
        raise MediaUnavailable("unreachable") from error


def overview(*, home: Path | None = None) -> dict:
    """Schedule, pending posts and offered stories in one owner response."""
    try:
        status, schedule = call("GET", "/media-control/schedule", home=home)
        if status != 200:
            return {"state": "unavailable", "reason": f"schedule_http_{status}"}
        status, news = call("GET", "/media-control/news", home=home)
        if status != 200:
            return {"state": "unavailable", "reason": f"news_http_{status}"}
        # Today's queue is optional: an older news service without it still works.
        status, today = call("GET", "/media-control/today", home=home)
        # Reviewed comments are optional too (news service before #73).
        comments_status, comments = call("GET", "/media-control/comments", home=home)
    except MediaUnavailable as error:
        return {"state": "not_configured" if str(error) == "not_configured" else "unavailable"}
    return {"state": "ready", "schedule": schedule, "news": news.get("items", []),
            "today": today if status == 200 else None,
            "comments": comments if comments_status == 200 else None}


def save_schedule(body: dict, *, home: Path | None = None) -> tuple[int, dict]:
    slots = body.get("slots")
    if not isinstance(slots, list) or len(slots) > 10 or not all(
            isinstance(s, str) and TIME_RE.match(s.strip()) for s in slots):
        raise ValueError("invalid_slots")
    return call("PUT", "/media-control/schedule", {"slots": [s.strip() for s in slots]}, home=home)


def save_settings(body: dict, *, home: Path | None = None) -> tuple[int, dict]:
    """«Настройки Медиа»: how many LinkedIn posts the bot may put out per day."""
    value = body.get("posts_per_day")
    low, high = POSTS_PER_DAY_RANGE
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ValueError("invalid_posts_per_day")
    return call("PUT", "/media-control/settings", {"posts_per_day": value}, home=home)


def preview(body: dict, *, home: Path | None = None) -> tuple[int, dict]:
    article_id = str(uuid.UUID(str(body.get("article_id", ""))))
    # Generation runs two model passes; allow it time.
    return call("POST", f"/media-control/news/{article_id}/preview", timeout=240, home=home)


def rewrite(body: dict, *, home: Path | None = None) -> tuple[int, dict]:
    """Rework a prepared draft by the owner's short instruction ("короче", ...)."""
    candidate_id = str(uuid.UUID(str(body.get("candidate_id", ""))))
    instruction = body.get("instruction")
    if not isinstance(instruction, str):
        raise ValueError("invalid_instruction")
    instruction = " ".join(instruction.split())
    if not 1 <= len(instruction) <= MAX_INSTRUCTION:
        raise ValueError("invalid_instruction")
    return call("POST", f"/media-control/candidates/{candidate_id}/rewrite",
                {"instruction": instruction}, timeout=240, home=home)


def edit(body: dict, *, home: Path | None = None) -> tuple[int, dict]:
    """Save the owner's own wording for a prepared draft."""
    candidate_id = str(uuid.UUID(str(body.get("candidate_id", ""))))
    text = body.get("text")
    if not isinstance(text, str) or not 1 <= len(text.strip()) <= MAX_POST_TEXT:
        raise ValueError("invalid_text")
    return call("POST", f"/media-control/candidates/{candidate_id}/text",
                {"text": text.strip()}, home=home)


def send_batch(body: dict, *, home: Path | None = None) -> tuple[int, dict]:
    items = body.get("items")
    if not isinstance(items, list) or not 1 <= len(items) <= MAX_BATCH:
        raise ValueError("invalid_items")
    clean = []
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("preview"), dict):
            raise ValueError("invalid_items")
        clean.append({"candidate_id": str(uuid.UUID(str(item.get("candidate_id", "")))),
                      "preview": item["preview"]})
    return call("POST", "/media-control/send-batch", {"items": clean}, timeout=120, home=home)


def _comment_id(body: dict) -> str:
    return str(uuid.UUID(str(body.get("comment_id", ""))))


def comment_create(body: dict, *, home: Path | None = None) -> tuple[int, dict]:
    """Draft comments for someone else's LinkedIn post the owner picked."""
    url = body.get("url")
    post_text = body.get("post_text") or ""
    if not isinstance(url, str) or not LINKEDIN_POST_RE.match(url.strip()):
        raise ValueError("invalid_url")
    if not isinstance(post_text, str) or len(post_text) > MAX_SOURCE_TEXT:
        raise ValueError("invalid_post_text")
    return call("POST", "/media-control/comments",
                {"url": url.strip(), "post_text": post_text.strip()}, timeout=240, home=home)


def comment_text(body: dict, *, home: Path | None = None) -> tuple[int, dict]:
    text = body.get("text")
    if not isinstance(text, str) or not 1 <= len(text.strip()) <= MAX_COMMENT:
        raise ValueError("invalid_text")
    return call("POST", f"/media-control/comments/{_comment_id(body)}/text",
                {"text": text.strip()}, home=home)


def comment_rewrite(body: dict, *, home: Path | None = None) -> tuple[int, dict]:
    instruction = body.get("instruction")
    if not isinstance(instruction, str):
        raise ValueError("invalid_instruction")
    instruction = " ".join(instruction.split())
    if not 1 <= len(instruction) <= MAX_INSTRUCTION:
        raise ValueError("invalid_instruction")
    return call("POST", f"/media-control/comments/{_comment_id(body)}/rewrite",
                {"instruction": instruction}, timeout=240, home=home)


def comment_send(body: dict, *, home: Path | None = None) -> tuple[int, dict]:
    """Send exactly the reviewed text: the news service checks this hash."""
    digest = body.get("text_sha256")
    if not isinstance(digest, str) or not SHA_RE.match(digest):
        raise ValueError("invalid_text_sha256")
    return call("POST", f"/media-control/comments/{_comment_id(body)}/send",
                {"text_sha256": digest}, timeout=60, home=home)


def comment_close(body: dict, *, home: Path | None = None) -> tuple[int, dict]:
    """«Я опубликовал» (manual) or «Убрать» (dismiss)."""
    action = body.get("action")
    if action not in ("manual", "dismiss"):
        raise ValueError("invalid_action")
    return call("POST", f"/media-control/comments/{_comment_id(body)}/{action}", {}, home=home)
