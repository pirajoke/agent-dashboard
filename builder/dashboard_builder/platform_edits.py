"""Owner edits to Platforms cards: a name, a status label, a description, a priority and a group per card.

Mark 2026-10-20: «Добавь кнопку Эдит, чтоб, если что, я мог менять название, менять статус,
менять приоритетность». The page keeps its built-in names; this file only overrides them, so a
missing, unreadable or empty store falls back to the shipped cards. It lives on the Mac mini, so
the same edits show on every device that opens Command Center as the owner.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import tempfile
import threading

MAX_BODY_BYTES = 16 * 1024
MAX_CARDS = 60
NAME_MAX = 60
STATUS_MAX = 40
DESCRIPTION_MAX = 200
PRIORITIES = ("main", "normal")
GROUPS = ("product", "personal")  # Mark 2026-10-28: «Продукты» first, then «Личные».

_STORE_LOCK = threading.Lock()  # The server is threaded; one card change at a time.
_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
_CONTROL = re.compile(r"[\x00-\x1f\x7f​-‏‪-‮⁦-⁩]")


def _clean_text(value: object, limit: int) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("text_expected")
    text = " ".join(value.split())
    if _CONTROL.search(text):
        raise ValueError("control_characters")
    if len(text) > limit:
        raise ValueError("text_too_long")
    return text or None


def validate_edits(payload: object) -> dict[str, dict[str, str]]:
    """Return clean per-card overrides, or raise ValueError for anything malformed."""
    if not isinstance(payload, dict) or not isinstance(payload.get("edits"), dict):
        raise ValueError("edits_object_expected")
    edits = payload["edits"]
    if len(edits) > MAX_CARDS:
        raise ValueError("too_many_cards")
    clean: dict[str, dict[str, str]] = {}
    for card_id, entry in edits.items():
        if not isinstance(card_id, str) or not _ID.match(card_id):
            raise ValueError("invalid_card_id")
        if not isinstance(entry, dict) or set(entry) - {"name", "status", "description", "priority", "group"}:
            raise ValueError("invalid_card_entry")
        result: dict[str, str] = {}
        name = _clean_text(entry.get("name"), NAME_MAX)
        status = _clean_text(entry.get("status"), STATUS_MAX)
        description = _clean_text(entry.get("description"), DESCRIPTION_MAX)
        priority = entry.get("priority")
        if name:
            result["name"] = name
        if status:
            result["status"] = status
        if description:
            result["description"] = description
        if priority is not None:
            if priority not in PRIORITIES:
                raise ValueError("invalid_priority")
            result["priority"] = priority
        group = entry.get("group")
        if group is not None:
            if group not in GROUPS:
                raise ValueError("invalid_group")
            result["group"] = group
        if result:
            clean[card_id] = result
    return clean


def load_edits(path: Path) -> dict:
    """Read the store; anything unreadable counts as no edits rather than an error page."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return {"edits": validate_edits(data), "updated_at": data.get("updated_at")}
    except (OSError, ValueError, TypeError, AttributeError):
        return {"edits": {}, "updated_at": None}


def save_edits(path: Path, payload: object, *, now: datetime | None = None) -> dict:
    """Validate and atomically replace the store; returns what was written."""
    edits = validate_edits(payload)
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
    record = {"edits": edits, "updated_at": stamp}
    _write_json(Path(path), record, prefix=".platform-edits.")
    return record


def save_card_edit(path: Path, payload: object, *, now: datetime | None = None) -> dict:
    """Change one card on top of what is stored now, so two devices never wipe each other's edits.

    ``payload`` is ``{"card": id, "edit": {...}, "v": 2}``; an empty or null ``edit`` puts the card back.
    A page opened before descriptions existed sends no ``v`` and knows nothing about the description,
    so its save keeps the stored one instead of silently dropping it.
    """
    if not isinstance(payload, dict) or set(payload) - {"card", "edit", "v"}:
        raise ValueError("card_edit_expected")
    card_id, entry = payload.get("card"), payload.get("edit") or {}
    change = validate_edits({"edits": {card_id: entry}}) if isinstance(card_id, str) else None
    if change is None:
        raise ValueError("invalid_card_id")
    with _STORE_LOCK:
        edits = dict(load_edits(path)["edits"])
        previous = edits.pop(card_id, None) or {}
        if payload.get("v") != 2 and "description" in previous:
            change.setdefault(card_id, {}).setdefault("description", previous["description"])
        edits.update(change)
        return save_edits(path, {"edits": edits}, now=now)


def _write_json(path: Path, record: dict, *, prefix: str) -> None:
    """Atomically replace ``path`` with ``record``, readable only by the owner."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=prefix, dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(record, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.chmod(temp, 0o600)
        os.replace(temp, path)
    except BaseException:
        try:
            os.unlink(temp)
        except OSError:
            pass
        raise
