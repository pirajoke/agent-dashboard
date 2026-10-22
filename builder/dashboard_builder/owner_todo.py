"""«Ждёт тебя»: Mark's own list of things only he can do (Mark 2026-10-22).

The automatic «Ждёт вас» list in MAIN MANAGER is built from dates, day summaries and PRs.
This one is what agents ask Mark to do by hand (a UPS, a macOS switch, «сливай #61»), and he adds,
closes and reopens items on the site himself. It lives only on the Mac mini, behind the owner check,
so nothing of it is in the public HTML.
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

_STORE_LOCK = threading.Lock()
_ID = re.compile(r"^t-[a-f0-9]{8}$")


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
    return item


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
            else:
                raise ValueError("invalid_action")
        record = {"items": items, "updated_at": stamp}
        _write_json(path, record, prefix=".owner-todo-")
        return record
