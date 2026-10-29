"""GitHub, Linear and Notion as part of Command Center (Mark 2026-10-29).

«мне нужно чтобы ты видел notion и github и linear, либо давал ссылки на них — это часть архитектуры».
The «Платформы» page shows one card per tool with direct links. The owner also sees a short live
list on each card: open pull requests, Linear issues in progress, recently edited Notion pages.
Only titles and links leave this module; no counts, ids, dates or tokens. A tool without a token on
the Mac mini simply shows its links.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import urlencode, urlsplit

GITHUB_OWNER = "pirajoke"
LIST_LIMIT = 3
TITLE_LIMIT = 120
CACHE_SECONDS = 300
TIMEOUT_SECONDS = 8

TOOLS = (
    {
        "id": "github",
        "name": "GitHub",
        "description": "Код всех проектов. Каждая правка агентов приходит сюда как PR.",
        "url": "https://github.com/pirajoke?tab=repositories",
        "extra": {"label": "Открытые PR", "url": "https://github.com/pulls?q=is%3Aopen+is%3Apr+user%3Apirajoke"},
        "live_title": "Ждут слияния",
    },
    {
        "id": "linear",
        "name": "Linear",
        "description": "Задачи по проектам: что сделать и что уже в работе.",
        "url": "https://linear.app/pirajoke",
        "extra": {"label": "Мои задачи", "url": "https://linear.app/pirajoke/my-issues/assigned"},
        "live_title": "В работе",
    },
    {
        "id": "notion",
        "name": "Notion",
        "description": "Страницы, заметки и общие документы.",
        "url": "https://www.notion.so/",
        "extra": None,
        "live_title": "Недавно менялись",
    },
)

_cache: dict = {"at": 0.0, "live": None}
_cache_lock = threading.Lock()


def _token(env: str, relative: str) -> str:
    value = os.environ.get(env, "").strip()
    if value:
        return value
    path = Path.home() / relative
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _request_json(url: str, *, headers: dict, body: dict | None = None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(url, data, {"User-Agent": "command-center", "Accept": "application/json", **headers})
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        return json.loads(response.read().decode("utf-8"))


def _item(title: object, url: object, allowed_host: str) -> dict | None:
    if not isinstance(title, str) or not isinstance(url, str):
        return None
    title = " ".join(title.split())[:TITLE_LIMIT]
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if not title or parts.scheme != "https" or not (host == allowed_host or host.endswith("." + allowed_host)):
        return None
    return {"title": title, "url": url}


def fetch_github() -> list[dict]:
    query = urlencode({"q": f"is:pr is:open user:{GITHUB_OWNER}", "sort": "updated", "order": "desc", "per_page": LIST_LIMIT})
    headers = {"Accept": "application/vnd.github+json"}
    token = _token("GITHUB_TOKEN", ".config/command-center/github_token")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    payload = _request_json(f"https://api.github.com/search/issues?{query}", headers=headers)
    rows = payload.get("items") if isinstance(payload, dict) else None
    return [i for i in (_item(r.get("title"), r.get("html_url"), "github.com") for r in rows or [] if isinstance(r, dict)) if i]


def fetch_linear() -> list[dict] | None:
    token = _token("LINEAR_API_KEY", ".config/linear/token")
    if not token:
        return None
    query = """query($n: Int!) { issues(first: $n, orderBy: updatedAt,
      filter: { state: { type: { eq: "started" } } }) { nodes { title url } } }"""
    payload = _request_json("https://api.linear.app/graphql", headers={"Authorization": token, "Content-Type": "application/json"},
                            body={"query": query, "variables": {"n": LIST_LIMIT}})
    if not isinstance(payload, dict) or payload.get("errors"):
        raise ValueError("linear_error")
    nodes = ((payload.get("data") or {}).get("issues") or {}).get("nodes") or []
    return [i for i in (_item(n.get("title"), n.get("url"), "linear.app") for n in nodes if isinstance(n, dict)) if i]


def _notion_title(page: dict) -> object:
    for prop in (page.get("properties") or {}).values():
        if isinstance(prop, dict) and prop.get("type") == "title":
            return "".join(part.get("plain_text", "") for part in prop.get("title") or [] if isinstance(part, dict))
    return None


def fetch_notion() -> list[dict] | None:
    token = _token("NOTION_TOKEN", ".config/notion/token")
    if not token:
        return None
    payload = _request_json("https://api.notion.com/v1/search", headers={
        "Authorization": f"Bearer {token}", "Notion-Version": "2022-06-28", "Content-Type": "application/json",
    }, body={"page_size": LIST_LIMIT, "filter": {"property": "object", "value": "page"},
             "sort": {"direction": "descending", "timestamp": "last_edited_time"}})
    rows = payload.get("results") if isinstance(payload, dict) else None
    return [i for i in (_item(_notion_title(r), r.get("url"), "notion.so") for r in rows or [] if isinstance(r, dict)) if i]


FETCHERS = {"github": fetch_github, "linear": fetch_linear, "notion": fetch_notion}


def _safe(fetcher) -> dict:
    try:
        items = fetcher()
    except (urllib.error.URLError, OSError, ValueError, TimeoutError, AttributeError, TypeError):
        return {"state": "unavailable", "items": []}
    if items is None:
        return {"state": "not_configured", "items": []}
    return {"state": "ready", "items": items[:LIST_LIMIT]}


def _live(fetchers: dict, now: float) -> dict:
    with _cache_lock:
        if _cache["live"] is not None and now - _cache["at"] < CACHE_SECONDS:
            return _cache["live"]
    with ThreadPoolExecutor(max_workers=len(fetchers)) as pool:
        futures = {key: pool.submit(_safe, fn) for key, fn in fetchers.items()}
        live = {key: future.result() for key, future in futures.items()}
    with _cache_lock:
        _cache.update(at=now, live=live)
    return live


def work_tools_projection(owner: bool = False, *, fetchers: dict | None = None, now: float | None = None) -> dict:
    """Links for everyone; the short live lists only for the owner."""
    live = _live(fetchers or FETCHERS, time.time() if now is None else now) if owner else {}
    tools = []
    for tool in TOOLS:
        entry = {key: tool[key] for key in ("id", "name", "description", "url", "extra")}
        if owner:
            entry["live"] = {"title": tool["live_title"], **live.get(tool["id"], {"state": "unavailable", "items": []})}
        tools.append(entry)
    return {"state": "ready" if owner else "owner_required", "tools": tools}


def reset_cache() -> None:
    with _cache_lock:
        _cache.update(at=0.0, live=None)
