"""«Точки роста»: what Mark wants to learn and grow into, with honest progress.

The list lives in Mark's Obsidian vault (``AMBITIONS-DREAMS/ТОЧКИ-РОСТА.md``), not in
the dashboard: he edits it there, and the dashboard only reads it. Each area is a
``## heading`` followed by a few ``- Key: value`` lines and a checklist::

    ## Private Equity и покупка бизнеса
    - Картинка: pe
    - Зачем: Купить и вести работающий бизнес.
    - Проекты: financial, jobradar
    - [x] Разобрать модели сделок
    - [ ] Заполнить тезис покупки

``Картинка`` is optional: without a known one, the title picks the picture.

Progress is the share of ticked steps, and only exists once an area has steps. Time is
the real work of the last 30 days in the projects an area names, taken from the Daily
Work session files; an area with no linked project, or no session files to read, has
unknown time, never a made-up zero. A note untouched for NOTE_STALE_DAYS is ``stale``:
its ticks may no longer match where Mark is.
"""
from __future__ import annotations

import json
import re
import threading
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

NOTE_FILE = Path.home() / "ObsidianVault" / "AMBITIONS-DREAMS" / "ТОЧКИ-РОСТА.md"
PICTURES = {"pe", "digital", "research", "podcast", "design", "coworking", "trading", "pmp", "robots", "agents", "growth"}
# Without a known «Картинка:», the title picks one. Order matters: «Дизайн-агентство» is design, not agents.
_PICTURE_HINTS = (
    ("design", ("дизайн", "design")),
    ("research", ("исследован", "research", "наук")),
    ("trading", ("трейд", "trading", "инвест", "бирж")),
    ("pmp", ("pmp", "сертифик", "проектн", "project manag")),
    ("robots", ("робот", "электрон", "robot", "arduino")),
    ("agents", ("агент", "agent")),
    ("pe", ("private equity", "венчур", "покупк", "сделк")),
    ("digital", ("digital", "монетиз", "tiktok", "shopify", "магазин")),
    ("podcast", ("подкаст", "podcast", "бренд")),
    ("coworking", ("коворкинг", "cowork")),
)
TIME_WINDOW_DAYS = 30
NOTE_STALE_DAYS = 30
_STEP_RE = re.compile(r"^\s*[-*]\s+\[( |x|X)\]\s+(.+?)\s*$")
_META_RE = re.compile(r"^\s*[-*]\s+(Картинка|Зачем|Проекты|Заметка)\s*:\s*(.*?)\s*$", re.IGNORECASE)
_TEXT_LIMIT = 200


def _clean(text: str, limit: int = _TEXT_LIMIT) -> str:
    text = re.sub(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]", lambda m: m.group(2) or m.group(1), text)
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _key(text: str) -> str:
    return re.sub(r"[^0-9a-zа-яё]", "", text.lower())


def _slug(title: str, used: set[str]) -> str:
    base = re.sub(r"[^0-9a-zа-яё]+", "-", title.lower()).strip("-")[:40] or "area"
    slug, n = base, 2
    while slug in used:
        slug, n = f"{base}-{n}", n + 1
    used.add(slug)
    return slug


def _guess_picture(title: str) -> str:
    lowered = title.lower()
    for picture, hints in _PICTURE_HINTS:
        if any(hint in lowered for hint in hints):
            return picture
    return "growth"


def parse_note(text: str) -> list[dict[str, Any]]:
    areas: list[dict[str, Any]] = []
    used: set[str] = set()
    current: dict[str, Any] | None = None
    for line in text.splitlines():
        if line.startswith("## "):
            title = _clean(line[3:], 80)
            current = {"id": _slug(title, used), "title": title, "why": "", "picture": _guess_picture(title),
                       "projects": [], "steps": []}
            areas.append(current)
            continue
        if current is None:
            continue
        step = _STEP_RE.match(line)
        if step:
            current["steps"].append({"text": _clean(step.group(2)), "done": step.group(1).lower() == "x"})
            continue
        meta = _META_RE.match(line)
        if not meta:
            continue
        name, value = meta.group(1).lower(), meta.group(2)
        if name == "картинка":
            picture = value.strip().lower()
            if picture in PICTURES:
                current["picture"] = picture
        elif name == "зачем":
            current["why"] = _clean(value)
        elif name == "проекты":
            current["projects"] = [_key(item) for item in value.split(",") if _key(item)]
    return areas


def _minutes_by_project(daily_work_dir: Path, today: date) -> dict[str, int] | None:
    """Active minutes per normalised project name over the last TIME_WINDOW_DAYS days.

    None when there are no session files to read at all: the time is unknown, not zero.
    One broken file or record is skipped without hiding the rest.
    """
    since = (today - timedelta(days=TIME_WINDOW_DAYS - 1)).isoformat()
    totals: dict[str, int] = {}
    sessions_dir = daily_work_dir / "sessions"
    try:
        paths = list(sessions_dir.glob("*/*.json")) if sessions_dir.is_dir() else []
    except OSError:
        paths = []
    if not paths:
        return None
    for path in paths:
        if path.stem < since or path.stem > today.isoformat():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        sessions = payload.get("sessions") if isinstance(payload, dict) else None
        if not isinstance(sessions, list):
            continue
        for session in sessions:
            if not isinstance(session, dict):
                continue
            name = _key(str(session.get("project") or ""))
            minutes = session.get("active_minutes")
            if name and isinstance(minutes, (int, float)) and minutes > 0:
                totals[name] = totals.get(name, 0) + int(minutes)
    return totals


def growth_projection(note_file: Path, daily_work_dir: Path, *, owner: bool, today: date | None = None) -> dict[str, Any]:
    today = today or date.today()
    observed_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        text = note_file.read_text(encoding="utf-8")
        changed = datetime.fromtimestamp(note_file.stat().st_mtime, timezone.utc)
    except FileNotFoundError:
        return {"ok": True, "state": "empty", "owner_view": owner, "areas": [], "count": 0,
                "observed_at": observed_at}
    except OSError:
        return {"ok": False, "state": "unavailable", "owner_view": owner, "areas": [], "count": 0,
                "observed_at": observed_at}
    areas = parse_note(text)
    note_age_days = max(0, (today - changed.date()).days)
    state = "stale" if note_age_days >= NOTE_STALE_DAYS else "live"
    if not owner:
        # The public view says how many areas exist, never what they are.
        return {"ok": True, "state": state, "owner_view": False, "areas": [], "count": len(areas),
                "observed_at": observed_at}
    minutes = _minutes_by_project(daily_work_dir, today)
    for area in areas:
        total = len(area["steps"])
        done = sum(1 for step in area["steps"] if step["done"])
        area["progress"] = {"done": done, "total": total}
        area["linked"] = bool(area["projects"])
        if area["projects"] and minutes is not None:
            area["minutes_30d"] = sum(value for name, value in minutes.items()
                                      if any(key and key in name for key in area["projects"]))
        else:
            area["minutes_30d"] = None
        area.pop("projects")
    return {"ok": True, "state": state, "owner_view": True, "areas": areas, "count": len(areas),
            "source": "Obsidian · AMBITIONS-DREAMS/ТОЧКИ-РОСТА.md", "window_days": TIME_WINDOW_DAYS,
            "time_available": minutes is not None, "note_updated_at": changed.isoformat(timespec="seconds"),
            "note_age_days": note_age_days, "stale_after_days": NOTE_STALE_DAYS, "observed_at": observed_at}


# ── Edits from the site (Mark 2026-10-22: «Точки роста правятся прямо на сайте») ──
# The note stays the source of truth and stays a normal Obsidian note: an edit changes only the lines
# it is about and keeps the rest of the file byte for byte. Each change names the step by its text as
# the page saw it, so a note edited in Obsidian meanwhile gives a conflict instead of a wrong tick.
EDIT_MAX_BODY_BYTES = 4 * 1024
_EDIT_LOCK = threading.Lock()


class NoteConflict(Exception):
    """The note changed since the page read it."""


def _sections(lines: list[str]) -> list[dict[str, Any]]:
    """Areas with the line numbers of their heading, meta lines and steps, in parse_note order."""
    used: set[str] = set()
    sections: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for index, line in enumerate(lines):
        if line.startswith("## "):
            current = {"id": _slug(_clean(line[3:], 80), used), "heading": index, "last": index, "steps": []}
            sections.append(current)
            continue
        if current is None:
            continue
        step = _STEP_RE.match(line)
        if step:
            current["steps"].append({"line": index, "text": _clean(step.group(2)), "done": step.group(1).lower() == "x"})
            current["last"] = index
        elif _META_RE.match(line):
            current["last"] = index
    return sections


def _one_line(value: object, limit: int) -> str:
    if not isinstance(value, str):
        raise ValueError("text_expected")
    text = " ".join(value.split())
    if not text:
        raise ValueError("text_required")
    if len(text) > limit or re.search(r"[\x00-\x1f\x7f]", text):
        raise ValueError("text_too_long" if len(text) > limit else "control_characters")
    return text


def change_note(note_file: Path, payload: object) -> None:
    """Apply one owner edit to the note: toggle, add_step, delete_step or add_area."""
    if not isinstance(payload, dict):
        raise ValueError("invalid_request")
    action = payload.get("action")
    if action not in {"toggle", "add_step", "delete_step", "add_area"}:
        raise ValueError("invalid_action")
    with _EDIT_LOCK:
        try:
            raw = note_file.read_bytes().decode("utf-8")  # bytes: keep CRLF as it is
        except FileNotFoundError:
            if action != "add_area":
                raise NoteConflict("note_missing") from None
            raw = "# Точки роста\n"
        newline = "\r\n" if "\r\n" in raw else "\n"
        lines = raw.split(newline)
        if action == "add_area":
            title = _one_line(payload.get("title"), 80)
            why = payload.get("why")
            block = [f"## {title}"]
            if why not in (None, ""):
                block.append(f"- Зачем: {_one_line(why, _TEXT_LIMIT)}")
            lines = (raw.rstrip("\r\n") + newline * 2 + newline.join(block) + newline).split(newline)
        else:
            area_id = payload.get("area")
            section = next((item for item in _sections(lines) if item["id"] == area_id), None)
            if section is None:
                raise NoteConflict("area_not_found")
            if action == "add_step":
                text = _one_line(payload.get("text"), _TEXT_LIMIT)
                lines.insert(section["last"] + 1, f"- [ ] {text}")
            elif action in {"toggle", "delete_step"}:
                index = payload.get("step")
                if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < len(section["steps"]):
                    raise NoteConflict("step_not_found")
                step = section["steps"][index]
                if step["text"] != payload.get("text"):
                    raise NoteConflict("step_changed")
                if action == "delete_step":
                    del lines[step["line"]]
                else:
                    done = payload.get("done")
                    if not isinstance(done, bool):
                        raise ValueError("done_expected")
                    lines[step["line"]] = re.sub(r"\[( |x|X)\]", "[x]" if done else "[ ]", lines[step["line"]], count=1)
            else:
                raise ValueError("invalid_action")
        text = newline.join(lines)
        note_file.parent.mkdir(parents=True, exist_ok=True)
        temp = note_file.with_name(f".{note_file.name}.site-edit")
        temp.write_bytes(text.encode("utf-8"))
        try:
            temp.chmod(note_file.stat().st_mode & 0o777)
        except FileNotFoundError:
            pass
        temp.replace(note_file)
