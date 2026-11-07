"""«Итоги недели» (Mark 2026-11-07): notes that projects drop into an inbox, grouped by direction.

Any project (a Claude thread, Codex, a script) writes one Markdown note per week into an inbox folder:

    ---
    project: HARDWARE
    direction: AI-инфраструктура        # optional, the project name is used without it
    week: 2026-11-02                    # optional, any day of the week; else the date in the
    ---                                 # file name (2026-11-06-hardware.md), else the file time
    ## Сделано
    - Mac mini on a UPS
    ## Ждёт тебя
    - Choose the UPS model
    ## Дальше
    - Network backup of the MacBook Pro

The inboxes are ``~/.agent-bridge/weekly-inbox/`` (local agents on the Mac mini) and
``00-Inbox/weekly/`` of the vault checkout (cloud projects push the note to the vault repo).
``WEEKLY_INBOX_DIRS`` (paths joined with ``:``) replaces that list.

Weeks run Monday to Sunday and are keyed by their Monday. The weekly digest stores each week as
``<monday>.md`` (the Telegram text) and ``<monday>.json`` (the same week, structured for the
«Итоги недели» page); this module also reads that history back.
"""
from __future__ import annotations

import json
import os
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

HOME = Path.home()
DEFAULT_INBOXES = (HOME / ".agent-bridge" / "weekly-inbox", HOME / "jarvis-context-vault" / "00-Inbox" / "weekly")
SECTIONS = {"done": "Сделано", "waiting": "Ждёт тебя", "next": "Дальше"}
# Headings people actually write; matched on the start of the heading, case-insensitive.
SECTION_WORDS = {
    "done": ("сделано", "готово", "итоги", "done", "shipped"),
    "waiting": ("ждёт тебя", "ждет тебя", "ждёт марка", "ждет марка", "нужен макс", "нужно от тебя", "waiting", "blocked"),
    "next": ("дальше", "следующ", "план", "next"),
}
MAX_NOTE_BYTES = 64 * 1024
MAX_ITEMS = 12
MAX_ITEM_CHARS = 300
MAX_NOTES = 60
WEEK_FILE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.(md|json)$")
DATE_PREFIX = re.compile(r"^(\d{4}-\d{2}-\d{2})")


def inbox_dirs() -> list[Path]:
    raw = os.environ.get("WEEKLY_INBOX_DIRS", "").strip()
    if raw:
        return [Path(part).expanduser() for part in raw.split(":") if part.strip()]
    return list(DEFAULT_INBOXES)


def monday(day: date) -> date:
    return day - timedelta(days=day.weekday())


def report_week(today: date) -> date:
    """The week a report built today is about: the one holding yesterday.

    On Monday that is the whole previous week (the scheduled digest); later in the week it is the
    current week so far («Собрать сводку сейчас»)."""
    return monday(today - timedelta(days=1))


def _parse_date(text: str) -> date | None:
    try:
        return date.fromisoformat(str(text).strip()[:10])
    except ValueError:
        return None


def _clean(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text[:MAX_ITEM_CHARS - 1] + "…" if len(text) > MAX_ITEM_CHARS else text


def parse_note(text: str) -> dict[str, Any]:
    """Front matter and the three lists of one note. Unknown headings are ignored."""
    meta: dict[str, str] = {}
    body = text.replace("\r\n", "\n")
    if body.startswith("---\n"):
        head, sep, rest = body[4:].partition("\n---")
        if sep:
            for line in head.splitlines():
                key, colon, value = line.partition(":")
                if colon and key.strip():
                    meta[key.strip().lower()] = value.split(" #", 1)[0].strip().strip("\"'")
            body = rest.split("\n", 1)[1] if "\n" in rest else ""
    lists: dict[str, list[str]] = {key: [] for key in SECTIONS}
    current: str | None = None
    for line in body.splitlines():
        heading = re.match(r"^#{1,4}\s+(.+?)\s*:?\s*$", line) or re.match(r"^\*\*(.+?):?\*\*:?\s*$", line.strip())
        if heading:
            words = re.sub(r"^[^\wА-Яа-яЁё]+", "", heading.group(1)).lower()
            current = next((key for key, starts in SECTION_WORDS.items() if words.startswith(starts)), None)
            continue
        item = re.match(r"^\s*(?:[-*•]|\d+[.)])\s+(?:\[[ xX]\]\s+)?(.+)$", line)
        if current and item and len(lists[current]) < MAX_ITEMS:
            cleaned = _clean(item.group(1))
            if cleaned:
                lists[current].append(cleaned)
    return {"meta": meta, **lists}


def _note_week(path: Path, meta: dict[str, str]) -> date | None:
    day = _parse_date(meta.get("week", "")) or _parse_date(meta.get("date", ""))
    if day is None:
        found = DATE_PREFIX.match(path.name)
        day = _parse_date(found.group(1)) if found else None
    if day is None:
        try:
            day = datetime.fromtimestamp(path.stat().st_mtime).date()
        except OSError:
            return None
    return monday(day)


def collect_notes(week: date, dirs: Iterable[Path] | None = None) -> list[dict[str, Any]]:
    """Notes about this week from every inbox. A broken or oversized note is skipped, never fatal."""
    notes = []
    for folder in dirs if dirs is not None else inbox_dirs():
        try:
            files = sorted(p for p in folder.rglob("*.md") if p.is_file() and not p.name.startswith("."))
        except OSError:
            continue
        for path in files:
            try:
                if path.stat().st_size > MAX_NOTE_BYTES:
                    continue
                parsed = parse_note(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError):
                continue
            if _note_week(path, parsed["meta"]) != week:
                continue
            if not any(parsed[key] for key in SECTIONS):
                continue
            project = _clean(parsed["meta"].get("project") or path.stem)[:60]
            notes.append({"project": project,
                          "direction": _clean(parsed["meta"].get("direction") or project)[:60],
                          "file": path.name, **{key: parsed[key] for key in SECTIONS}})
            if len(notes) >= MAX_NOTES:
                return notes
    return notes


def group_by_direction(notes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One block per direction, in the order directions first appear; duplicates dropped."""
    blocks: dict[str, dict[str, Any]] = {}
    for note in notes:
        block = blocks.setdefault(note["direction"].casefold(), {"name": note["direction"], "projects": [],
                                                                 **{key: [] for key in SECTIONS}})
        if note["project"] not in block["projects"]:
            block["projects"].append(note["project"])
        for key in SECTIONS:
            for item in note[key]:
                if item.casefold() not in {seen.casefold() for seen in block[key]}:
                    block[key].append(item)
    return list(blocks.values())


def direction_lines(blocks: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for block in blocks:
        title = block["name"]
        others = [p for p in block["projects"] if p.casefold() != title.casefold()]
        lines += ["", f"▸ {title}" + (f" ({', '.join(others)})" if others else "")]
        for key, label in SECTIONS.items():
            if block[key]:
                lines.append(f"{label}:")
                lines += [f"• {item}" for item in block[key]]
    return lines


def history(out: Path, limit: int = 60) -> list[dict[str, Any]]:
    """Saved weeks, newest first. Weeks saved before the structured file existed come back as text only."""
    weeks: dict[str, dict[str, Any]] = {}
    try:
        names = [p.name for p in out.iterdir() if p.is_file()]
    except OSError:
        return []
    for name in names:
        found = WEEK_FILE.match(name)
        if found:
            weeks.setdefault(found.group(1), {})[found.group(2)] = out / name
    result = []
    for key in sorted(weeks, reverse=True)[:limit]:
        files = weeks[key]
        entry: dict[str, Any] | None = None
        if "json" in files:
            try:
                entry = json.loads(files["json"].read_text(encoding="utf-8"))
            except (OSError, ValueError):
                entry = None
        if not isinstance(entry, dict):
            try:
                text = files["md"].read_text(encoding="utf-8") if "md" in files else ""
            except OSError:
                text = ""
            if not text.strip():
                continue
            entry = {"week": key, "title": text.splitlines()[0], "text": text.strip(), "directions": []}
        entry["week"] = key
        result.append(entry)
    return result
