"""«Журнал починок» for the Медик on Техника (Mark 2026-11-02).

Mark: «хочу чтобы ты видел историю починок и помнил контекст». Each entry says which computer,
when, what was wrong and what was done. The Медик shows the latest entries and, when a computer
has the same kind of trouble again, reminds what helped last time.

It lives only on the Mac mini (``~/.agent-bridge/machine-repairs.json``) behind the owner check:
app names and fixes are private context and never reach the public HTML. Mark adds entries on the
site; agents append with ``python3 -m dashboard_builder.repair_log add …`` after a repair.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import secrets
import sys
import threading

from .platform_edits import _clean_text, _write_json

MAX_BODY_BYTES = 4 * 1024
MAX_ENTRIES = 200
TEXT_MAX = 300
MACHINES = ("mini", "pro", "air")
# Which part of the computer the trouble was about; lets the Медик match a new problem to an old fix.
SIGNS = ("ram", "cpu", "disk", "service", "network", "other")

_STORE_LOCK = threading.Lock()
_ID = re.compile(r"^r-[a-f0-9]{8}$")
_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_AT = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?Z$")


class StoreUnavailable(OSError):
    """The file exists but cannot be read as a log; never overwrite it."""


def _today(now: datetime | None) -> str:
    return (now or datetime.now(timezone.utc)).astimezone(timezone.utc).strftime("%Y-%m-%d")


def _clean_entry(entry: object, *, now: datetime | None = None, new: bool = False) -> dict | None:
    if not isinstance(entry, dict):
        return None
    machine = entry.get("machine")
    if machine not in MACHINES:
        return None
    try:
        problem = _clean_text(entry.get("problem"), TEXT_MAX)
        fix = _clean_text(entry.get("fix"), TEXT_MAX)
    except ValueError:
        return None
    if not problem or not fix:
        return None
    day = entry.get("date") or (_today(now) if new else None)
    if not isinstance(day, str) or not _DAY.match(day):
        return None
    signs = entry.get("signs") or []
    if not isinstance(signs, list):
        return None
    signs = [sign for sign in dict.fromkeys(signs) if sign in SIGNS] or ["other"]
    entry_id = entry.get("id") if not new else f"r-{secrets.token_hex(4)}"
    if not isinstance(entry_id, str) or not _ID.match(entry_id):
        return None
    clean = {"id": entry_id, "machine": machine, "date": day, "problem": problem, "fix": fix, "signs": signs}
    # The time of the entry (UTC) lets the Медик show «×3, last at 14:05»; older entries have only the day.
    at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if new and not entry.get("date") else entry.get("at")
    if isinstance(at, str) and _AT.match(at):
        clean["at"] = at
    try:
        by = _clean_text(entry.get("by"), 40)
    except ValueError:
        by = None
    if by:
        clean["by"] = by
    return clean


def load_entries(path: Path) -> dict:
    """Entries newest first. A missing file is an empty log; a broken one is an error, not empty."""
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {"entries": []}
    try:
        data = json.loads(raw)
    except ValueError as error:
        raise StoreUnavailable("repair_log_unreadable") from error
    if not isinstance(data, dict) or not isinstance(data.get("entries"), list):
        raise StoreUnavailable("repair_log_unreadable")
    entries = [clean for clean in (_clean_entry(item) for item in data["entries"]) if clean]
    entries.sort(key=lambda item: (item["date"], item.get("at", "")), reverse=True)
    return {"entries": entries[:MAX_ENTRIES]}


def change_entries(path: Path, body: object, *, now: datetime | None = None) -> dict:
    """Apply ``{"action": "add", ...}`` or ``{"action": "remove", "id": ...}`` and return the log."""
    if not isinstance(body, dict):
        raise ValueError("object_expected")
    with _STORE_LOCK:
        record = load_entries(path)
        entries = record["entries"]
        action = body.get("action")
        if action == "add":
            entry = _clean_entry(body, now=now, new=True)
            if entry is None:
                raise ValueError("invalid_entry")
            entries.insert(0, entry)
        elif action == "remove":
            before = len(entries)
            entries = [item for item in entries if item["id"] != body.get("id")]
            if len(entries) == before:
                raise LookupError("entry_not_found")
        else:
            raise ValueError("unknown_action")
        entries.sort(key=lambda item: (item["date"], item.get("at", "")), reverse=True)
        record = {"entries": entries[:MAX_ENTRIES]}
        _write_json(path, record, prefix=".machine-repairs-")
        return record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Append a repair to the Медик's log on this Mac.")
    sub = parser.add_subparsers(dest="command", required=True)
    add = sub.add_parser("add")
    add.add_argument("--machine", required=True, choices=MACHINES)
    add.add_argument("--problem", required=True)
    add.add_argument("--fix", required=True)
    add.add_argument("--sign", action="append", choices=SIGNS, default=[])
    add.add_argument("--date", help="YYYY-MM-DD, today by default")
    add.add_argument("--by", default="claude")
    add.add_argument("--file", default=str(Path.home() / ".agent-bridge" / "machine-repairs.json"))
    sub.add_parser("list").add_argument("--file", default=str(Path.home() / ".agent-bridge" / "machine-repairs.json"))
    args = parser.parse_args(argv)
    path = Path(args.file).expanduser()
    if args.command == "list":
        print(json.dumps(load_entries(path), ensure_ascii=False, indent=2))
        return 0
    body = {"action": "add", "machine": args.machine, "problem": args.problem, "fix": args.fix,
            "signs": args.sign, "by": args.by}
    if args.date:
        body["date"] = args.date
    try:
        change_entries(path, body)
    except (ValueError, LookupError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
