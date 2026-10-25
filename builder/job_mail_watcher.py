#!/usr/bin/env python3
"""Watch Mark's job mailbox for employer replies (Mark 2026-10-24).

Every 10 minutes (launchd ``com.pirajoke.job-mail-watcher``) it reads new mail with the read-only
Gmail grant from «Подключить почту», sorts each employer reply (see dashboard_builder/job_mail.py)
and keeps ``~/.agent-bridge/job-mail/replies.json``. For a new invite it:

* sends Mark a short Telegram line (company, role, link to the mail; never the mail text),
  once ``~/.agent-bridge/telegram_digest.json`` exists (the same bot config as the weekly digest);
* adds «Ответить …» to «Ждёт тебя», marked as Mark's own (agents never answer employers);
* closes that item by itself once Mark has replied in the thread.

It never sends, labels, moves or marks mail as read: the grant does not allow it.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import urllib.parse
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parent))

from dashboard_builder import job_mail  # noqa: E402
from dashboard_builder import owner_todo  # noqa: E402
from dashboard_builder.platform_edits import _write_json  # noqa: E402

HOME = Path.home()
OWNER_TODO_FILE = Path(os.environ.get("OWNER_TODO_FILE") or HOME / ".agent-bridge" / "owner-todo.json")
TELEGRAM_FILE = Path(os.environ.get("JOB_MAIL_TELEGRAM_FILE") or HOME / ".agent-bridge" / "telegram_digest.json")
FIRST_SCAN_DAYS = 60
MAX_REPLIES = 600
MAX_NEW_PER_RUN = 80
SEARCH = ("-in:sent -in:chats -in:drafts -category:promotions -category:social "
          "(candidature OR application OR entretien OR interview OR poste OR position OR recrutement OR recruiting "
          "OR recruitment OR opportunity OR opportunité OR rendez-vous OR échange OR call OR candidat OR applying)")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _since(value) -> datetime | None:
    try:
        return datetime.strptime(str(value), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _header(message: dict, name: str) -> str:
    for header in message.get("payload", {}).get("headers", []) or []:
        if str(header.get("name", "")).lower() == name.lower():
            return str(header.get("value") or "")
    return ""


def _body(part: dict) -> str:
    """Plain text of a Gmail message payload (text/plain preferred, HTML stripped as a fallback)."""
    import base64
    import html
    import re

    plain, rich = [], []

    def walk(node: dict) -> None:
        data = node.get("body", {}).get("data")
        mime = str(node.get("mimeType") or "")
        if data and mime.startswith("text/"):
            text = base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", "replace")
            (plain if mime == "text/plain" else rich).append(text)
        for child in node.get("parts") or []:
            walk(child)

    walk(part or {})
    if plain:
        return "\n".join(plain)[:8000]
    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", "\n".join(rich))
    return html.unescape(re.sub(r"<[^>]+>", " ", text))[:8000]


class Gmail:
    def __init__(self, token: str, opener=urllib.request.urlopen):
        self.token, self.opener = token, opener

    def get(self, path: str, **query) -> dict:
        url = f"{job_mail.GMAIL_API}/{path}"
        if query:
            url += "?" + urllib.parse.urlencode(query, doseq=True)
        return job_mail._get_json(url, self.token, self.opener)

    def search(self, query: str, limit: int) -> list[str]:
        ids, page = [], None
        while len(ids) < limit:
            answer = self.get("messages", q=query, maxResults=min(100, limit - len(ids)), **({"pageToken": page} if page else {}))
            ids += [entry["id"] for entry in answer.get("messages", []) if isinstance(entry, dict) and entry.get("id")]
            page = answer.get("nextPageToken")
            if not page:
                break
        return ids

    def message(self, message_id: str) -> dict:
        return self.get(f"messages/{message_id}", format="full")

    def mark_replied(self, thread_id: str, after_ms: int) -> bool:
        thread = self.get(f"threads/{thread_id}", format="metadata", metadataHeaders="From")
        return any("SENT" in (message.get("labelIds") or []) and int(message.get("internalDate") or 0) > after_ms
                   for message in thread.get("messages", []))


def _link(email: str, thread_id: str) -> str:
    return f"https://mail.google.com/mail/?authuser={urllib.parse.quote(email)}#all/{thread_id}"


def _telegram(text: str, opener=urllib.request.urlopen) -> str:
    try:
        config = json.loads(TELEGRAM_FILE.read_text(encoding="utf-8"))
        bot, chat = str(config["bot_token"]), str(config["chat_id"])
    except (OSError, ValueError, KeyError, TypeError):
        return "telegram_not_configured"
    request = urllib.request.Request(f"https://api.telegram.org/bot{bot}/sendMessage", method="POST",
                                     data=json.dumps({"chat_id": chat, "text": text, "disable_web_page_preview": True}).encode(),
                                     headers={"Content-Type": "application/json"})
    try:
        with opener(request, timeout=20) as response:
            return "sent" if json.loads(response.read() or b"{}").get("ok") else "telegram_refused"
    except Exception:  # noqa: BLE001 — a failed alert must not stop the watcher; the site still shows it.
        return "telegram_failed"


def _todo_text(reply: dict) -> tuple[str, str]:
    text = f"Ответить {reply['company']}: зовут на собеседование"[:owner_todo.TEXT_MAX]
    note = " · ".join(part for part in (reply.get("role"), f"письмо от {reply['date'][:10]}", "отвечаешь и выбираешь время ты") if part)
    return text, note[:owner_todo.NOTE_MAX]


def _add_todo(reply: dict) -> str | None:
    text, note = _todo_text(reply)
    try:
        record = owner_todo.change_items(OWNER_TODO_FILE, {"action": "add", "text": text, "note": note})
        item_id = record["items"][0]["id"]
        # Answering employers and booking slots is Mark's alone: keep the agent runner off it.
        owner_todo.set_triage(OWNER_TODO_FILE, item_id, False, "Ответ работодателю пишет только Марк")
        return item_id
    except (OSError, ValueError, LookupError):
        return None


def _close_todo(item_id: str) -> None:
    try:
        owner_todo.change_items(OWNER_TODO_FILE, {"action": "done", "id": item_id})
    except (OSError, ValueError, LookupError):
        pass


def run(root: Path | None = None, *, opener=urllib.request.urlopen, now: datetime | None = None) -> dict:
    p = job_mail.paths(root)
    now = now or _now()
    status = {"last_run": _iso(now), "ok": True}
    saved = job_mail._read(p["replies"]) or {}
    replies = [reply for reply in saved.get("replies", []) if isinstance(reply, dict)] if isinstance(saved, dict) else []
    seen = set(saved.get("seen", [])) if isinstance(saved, dict) else set()
    first = not (isinstance(saved, dict) and saved.get("first_scan_done"))
    last_scan = saved.get("last_scan_ok") if isinstance(saved, dict) else None
    new_invites = 0
    try:
        token, email = job_mail.access_token(root, opener)
        gmail = Gmail(token, opener)
        # After the first scan, start a day before the last complete one, so days the Mac mini was off are not lost.
        since = _since(last_scan) if not first else None
        window = f"after:{int(since.timestamp()) - 86400}" if since else f"newer_than:{FIRST_SCAN_DAYS}d"
        new_ids = [mid for mid in gmail.search(f"{window} {SEARCH}", 500 if first else 100) if mid not in seen][:500 if first else MAX_NEW_PER_RUN]
        for message_id in new_ids:
            message = gmail.message(message_id)
            seen.add(message_id)
            labels = message.get("labelIds") or []
            if "SENT" in labels or "DRAFT" in labels:
                continue
            sender, subject = _header(message, "From"), _header(message, "Subject")
            body = _body(message.get("payload") or {})
            verdict = job_mail.classify(subject, body, sender)
            if verdict is None:
                continue
            received = datetime.fromtimestamp(int(message.get("internalDate") or 0) / 1000, timezone.utc)
            reply = {"id": message_id, "thread_id": message.get("threadId") or message_id, "date": _iso(received),
                     "company": job_mail.company_of(sender, subject), "role": job_mail.role_of(subject, body),
                     "subject": " ".join(subject.split())[:140], "verdict": verdict, "answered": False,
                     "link": _link(email, message.get("threadId") or message_id), "ms": int(message.get("internalDate") or 0)}
            replies.append(reply)
            if verdict == "positive":
                reply["alert_pending"] = True
                new_invites += 1
        # Has Mark answered an open invite? Then it is no longer waiting on him.
        for reply in replies:
            if reply.get("verdict") == "positive" and not reply.get("answered"):
                if gmail.mark_replied(reply["thread_id"], int(reply.get("ms") or 0)):
                    reply["answered"] = True
                    if reply.get("todo_id"):
                        _close_todo(reply["todo_id"])
        status["email"] = email
        last_scan = _iso(now)
    except LookupError as error:
        status.update(ok=False, reason=str(error))
    except (RuntimeError, OSError, ValueError) as error:
        status.update(ok=False, reason=str(error)[:60] or "gmail_unavailable")
    # Every open invite gets its «Ждёт тебя» item once and its Telegram line until one is delivered.
    pending = [reply for reply in replies if reply.get("verdict") == "positive" and not reply.get("answered")
               and reply.get("alert_pending")]
    for reply in pending:
        if not reply.get("todo_id"):
            reply["todo_id"] = _add_todo(reply)
    if pending:
        lines = [f"🟢 {reply['company']}: зовут на собеседование" + (f" ({reply['role']})" if reply.get("role") else "") + f"\n{reply['link']}"
                 for reply in pending[:10]]
        head = "Ответы работодателей, которые ждут тебя:" if len(pending) > 1 else "Новый положительный ответ:"
        status["telegram"] = _telegram(head + "\n\n" + "\n\n".join(lines) + "\n\nОтвечаешь и выбираешь время ты.", opener)
        if status["telegram"] == "sent":
            for reply in pending[:10]:
                reply.pop("alert_pending", None)
    for reply in replies:
        if reply.get("answered"):
            reply.pop("alert_pending", None)
    replies.sort(key=lambda reply: reply.get("date", ""), reverse=True)
    record = {"replies": replies[:MAX_REPLIES], "seen": sorted(seen)[-5000:], "updated_at": _iso(now),
              "first_scan_done": (not first) or status["ok"], "last_scan_ok": last_scan}
    p["dir"].mkdir(parents=True, exist_ok=True)
    os.chmod(p["dir"], 0o700)
    _write_json(p["replies"], record, prefix=".replies-")
    _write_json(p["status"], status, prefix=".status-")
    return {**status, "new": new_invites}


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(description=__doc__.splitlines()[0]).parse_args(argv)
    result = run()
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("ok") or result.get("reason") == "not_connected" else 1


if __name__ == "__main__":
    raise SystemExit(main())
