"""Order and archive of the computers on «Техника» (Mark 2026-11-03: «сделай drag drop и archive desarchive»).

The switcher above the computer panels shows Mac mini, MacBook Air and MacBook Pro. Mark can drag
them into his own order and put a computer he does not use (the MacBook Air is switched off) into
the archive, and take it back out. The store lives on the Mac mini, so every device that opens
Command Center as the owner sees the same order. A missing or broken store means the shipped order.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
import threading

MACHINES = ("mac-mini", "air", "pro")
MAX_BODY_BYTES = 1024

_STORE_LOCK = threading.Lock()


def validate_layout(payload: object) -> dict[str, list[str]]:
    """Return a clean ``{"order": [...], "archived": [...]}`` or raise ValueError."""
    if not isinstance(payload, dict) or set(payload) - {"order", "archived"}:
        raise ValueError("layout_expected")
    order, archived = payload.get("order", []), payload.get("archived", [])
    if not isinstance(order, list) or not isinstance(archived, list):
        raise ValueError("lists_expected")
    for item in (*order, *archived):
        if item not in MACHINES:
            raise ValueError("unknown_machine")
    if len(set(order)) != len(order) or len(set(archived)) != len(archived):
        raise ValueError("duplicate_machine")
    # Computers the page did not name (a newer page added one) keep their shipped place at the end.
    clean_order = list(order) + [machine for machine in MACHINES if machine not in order]
    if len(archived) >= len(MACHINES):
        raise ValueError("one_machine_must_stay")
    return {"order": clean_order, "archived": [m for m in clean_order if m in archived]}


def load_layout(path: Path) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return {**validate_layout({"order": data.get("order", []), "archived": data.get("archived", [])}),
                "updated_at": data.get("updated_at")}
    except (OSError, ValueError, TypeError, AttributeError):
        return {"order": list(MACHINES), "archived": [], "updated_at": None}


def save_layout(path: Path, payload: object, *, now: datetime | None = None) -> dict:
    layout = validate_layout(payload)
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
    record = {**layout, "updated_at": stamp}
    path = Path(path)
    with _STORE_LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp = tempfile.mkstemp(prefix=".machine-layout.", dir=path.parent)
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
    return record
