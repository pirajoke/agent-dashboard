"""«Ждёт тебя»: Mark's own list of things only he can do (Mark 2026-10-22).

The automatic «Ждёт вас» list in MAIN MANAGER is built from dates, day summaries and PRs.
This one is what agents ask Mark to do by hand (a UPS, a macOS switch, «сливай #61»), and he adds,
closes and reopens items on the site himself. It lives only on the Mac mini, behind the owner check,
so nothing of it is in the public HTML.

Mark can also hand an item to an agent (2026-10-23). The item then carries an ``agent`` record:
who took it and where it stands. Only Mark queues or takes back; the agent side (a session or the
runner on the Mac mini) moves it through working → done / needs_mark / failed with
``update_agent``, never through the web API.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re
import secrets
import threading

from .platform_edits import _clean_text, _write_json

MAX_BODY_BYTES = 8 * 1024
MAX_ITEMS = 60
TEXT_MAX = 200
NOTE_MAX = 300
RESULT_MAX = 300
URL_MAX = 300

AGENTS = ("claude", "codex")
AGENT_STATES = ("queued", "working", "done", "needs_mark", "failed")
# Where an agent may move a task. Finished states can be picked up again only after Mark re-queues.
_AGENT_MOVES = {"queued": {"working", "needs_mark", "failed"}, "working": {"done", "needs_mark", "failed"}}

_STORE_LOCK = threading.Lock()
_ID = re.compile(r"^t-[a-f0-9]{8}$")
_RESULT_URL = re.compile(r"^https://[A-Za-z0-9.-]+(?::\d+)?/[^\s<>\"']*$")


# The open asks to Mark on 2026-10-22, shown until he first changes the list; then the file takes over.
SEED_ITEMS = (
    {"id": "t-00000001", "text": "Поставить ИБП для Mac mini и роутера",
     "note": "Чтобы сайт и сервисы не падали, когда пропадает свет."},
    {"id": "t-00000002", "text": "Разрешить сервисам работать в фоне на Mac mini",
     "note": "Системные настройки → Основные → Объекты входа и расширения."},
    {"id": "t-00000003", "text": "Решить по PR #61: восстановление после перезагрузки",
     "note": "Если согласен, напиши «сливай #61»."},
    {"id": "t-00000004", "text": "Решить по PR #56: внешняя проверка, что сайт жив"},
)


class StoreUnavailable(OSError):
    """The file exists but cannot be read as a list; never overwrite it."""


def _now(now: datetime | None) -> str:
    return (now or datetime.now(timezone.utc)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _valid_item(entry: object) -> dict | None:
    if not isinstance(entry, dict) or not isinstance(entry.get("id"), str) or not _ID.match(entry["id"]):
        return None
    try:
        text = _clean_text(entry.get("text"), TEXT_MAX)
        note = _clean_text(entry.get("note"), NOTE_MAX)
    except ValueError:
        return None
    if not text:
        return None
    item = {"id": entry["id"], "text": text, "done": entry.get("done") is True,
            "created_at": str(entry.get("created_at") or "")[:20]}
    if note:
        item["note"] = note
    if item["done"] and entry.get("done_at"):
        item["done_at"] = str(entry["done_at"])[:20]
    agent = _valid_agent(entry.get("agent"))
    if agent:
        item["agent"] = agent
    triage = entry.get("triage")
    if isinstance(triage, dict) and isinstance(triage.get("agent"), bool) and isinstance(triage.get("text"), str):
        clean = {"agent": triage["agent"], "text": triage["text"][:TEXT_MAX + NOTE_MAX + 1]}
        try:
            why = _clean_text(triage.get("why"), RESULT_MAX)
        except ValueError:
            why = None
        if why:
            clean["why"] = why
        item["triage"] = clean
    return item


def _valid_agent(entry: object) -> dict | None:
    """A damaged agent record drops back to «Mark's item», never breaks the list."""
    if not isinstance(entry, dict) or entry.get("by") not in AGENTS or entry.get("state") not in AGENT_STATES:
        return None
    agent = {"by": entry["by"], "state": entry["state"], "updated_at": str(entry.get("updated_at") or "")[:20]}
    try:
        result = _clean_text(entry.get("result"), RESULT_MAX)
    except ValueError:
        result = None
    if result:
        agent["result"] = result
    url = entry.get("url")
    if isinstance(url, str) and len(url) <= URL_MAX and _RESULT_URL.match(url):
        agent["url"] = url
    return agent


def load_items(path: Path) -> dict:
    """No file means an empty list; a damaged file raises StoreUnavailable so a save cannot wipe it."""
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {"items": [{**item, "done": False, "created_at": "2026-10-22T21:00:00Z"} for item in SEED_ITEMS],
                "updated_at": None}
    except OSError as error:
        raise StoreUnavailable("store_unreadable") from error
    try:
        data = json.loads(raw)
    except ValueError as error:
        raise StoreUnavailable("store_unreadable") from error
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        raise StoreUnavailable("store_unreadable")
    items = [item for item in map(_valid_item, data["items"]) if item]
    return {"items": items, "updated_at": data.get("updated_at")}


def change_items(path: Path, payload: object, *, now: datetime | None = None, new_id=None) -> dict:
    """Apply one owner action: add, done, undo, edit or delete. Raises ValueError / LookupError."""
    if not isinstance(payload, dict):
        raise ValueError("invalid_request")
    action = payload.get("action")
    new_id = new_id or (lambda: f"t-{secrets.token_hex(4)}")
    with _STORE_LOCK:
        record = load_items(path)
        items = record["items"]
        stamp = _now(now)
        if action == "add":
            text = _clean_text(payload.get("text"), TEXT_MAX)
            note = _clean_text(payload.get("note"), NOTE_MAX)
            if not text:
                raise ValueError("text_required")
            if len(items) >= MAX_ITEMS:
                # Closed items make room first, oldest closed first.
                closed = [item for item in items if item["done"]]
                if not closed:
                    raise ValueError("too_many_items")
                items.remove(min(closed, key=lambda item: item.get("done_at") or ""))
            item = {"id": new_id(), "text": text, "done": False, "created_at": stamp}
            if note:
                item["note"] = note
            items.insert(0, item)
        else:
            item_id = payload.get("id")
            if not isinstance(item_id, str) or not _ID.match(item_id):
                raise ValueError("invalid_id")
            match = next((item for item in items if item["id"] == item_id), None)
            if match is None:
                raise LookupError("item_not_found")
            if action == "done":
                match.update(done=True, done_at=stamp)
            elif action == "undo":
                match["done"] = False
                match.pop("done_at", None)
            elif action == "edit":
                text = _clean_text(payload.get("text"), TEXT_MAX)
                if not text:
                    raise ValueError("text_required")
                match["text"] = text
                note = _clean_text(payload.get("note"), NOTE_MAX)
                if note:
                    match["note"] = note
                else:
                    match.pop("note", None)
            elif action == "delete":
                items.remove(match)
            elif action == "assign":
                by = payload.get("by") or "claude"
                if by not in AGENTS:
                    raise ValueError("invalid_agent")
                if match["done"]:
                    raise ValueError("item_closed")
                match["agent"] = {"by": by, "state": "queued", "updated_at": stamp}
            elif action == "unassign":
                match.pop("agent", None)
                # Taken back by Mark: the runner must not hand it straight back to an agent.
                match["triage"] = {"agent": False, "text": triage_key(match), "why": "Марк оставил себе"}
            else:
                raise ValueError("invalid_action")
        record = {"items": items, "updated_at": stamp}
        _write_json(path, record, prefix=".owner-todo-")
        return record


def update_agent(path: Path, item_id: str, state: str, *, by: str, result: str | None = None,
                 url: str | None = None, now: datetime | None = None) -> dict:
    """The agent side: claim a queued item or report how it went. Raises ValueError / LookupError."""
    if not isinstance(item_id, str) or not _ID.match(item_id):
        raise ValueError("invalid_id")
    if by not in AGENTS:
        raise ValueError("invalid_agent")
    if state not in AGENT_STATES or state == "queued":
        raise ValueError("invalid_state")
    clean_result = _clean_text(result, RESULT_MAX)
    if url is not None and (not isinstance(url, str) or len(url) > URL_MAX or not _RESULT_URL.match(url)):
        raise ValueError("invalid_url")
    with _STORE_LOCK:
        record = load_items(path)
        match = next((item for item in record["items"] if item["id"] == item_id), None)
        if match is None:
            raise LookupError("item_not_found")
        agent = match.get("agent")
        if not agent:
            raise ValueError("not_assigned")  # Mark took it back, or never gave it.
        if state not in _AGENT_MOVES.get(agent["state"], set()):
            raise ValueError("invalid_move")
        if agent["state"] == "working" and agent["by"] != by:
            raise ValueError("taken_by_other_agent")
        stamp = _now(now)
        match["agent"] = {"by": by, "state": state, "updated_at": stamp}
        if clean_result:
            match["agent"]["result"] = clean_result
        if url:
            match["agent"]["url"] = url
        record = {"items": record["items"], "updated_at": stamp}
        _write_json(path, record, prefix=".owner-todo-")
        return record


def queued_items(path: Path) -> list[dict]:
    """Open items waiting for an agent, oldest hand-off first."""
    items = [item for item in load_items(path)["items"]
             if not item["done"] and item.get("agent", {}).get("state") == "queued"]
    return sorted(items, key=lambda item: item["agent"]["updated_at"])


def triage_key(item: dict) -> str:
    """What the triage decision was made on; editing the item asks again."""
    return f"{item.get('text', '')}\n{item.get('note', '')}"


def untriaged_items(path: Path) -> list[dict]:
    """Open items no agent holds and nobody has sorted since their last edit."""
    return [item for item in load_items(path)["items"]
            if not item["done"] and "agent" not in item
            and item.get("triage", {}).get("text") != triage_key(item)]


def set_triage(path: Path, item_id: str, agent_can: bool, why: str | None, *, by: str = "claude",
               now: datetime | None = None) -> dict:
    """Store Claude's «могу сам / только Марк» call; a «могу сам» item goes straight to the queue."""
    clean_why = _clean_text(why, RESULT_MAX)
    with _STORE_LOCK:
        record = load_items(path)
        match = next((item for item in record["items"] if item["id"] == item_id), None)
        if match is None:
            raise LookupError("item_not_found")
        if match["done"] or "agent" in match:
            return record  # Mark closed it or handed it out meanwhile.
        stamp = _now(now)
        match["triage"] = {"agent": bool(agent_can), "text": triage_key(match)}
        if clean_why:
            match["triage"]["why"] = clean_why
        if agent_can:
            match["agent"] = {"by": by, "state": "queued", "updated_at": stamp}
        record = {"items": record["items"], "updated_at": stamp}
        _write_json(path, record, prefix=".owner-todo-")
        return record
