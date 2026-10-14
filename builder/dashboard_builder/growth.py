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

Progress is the share of ticked steps. Time is the real work of the last 30 days in
the projects an area names, taken from the Daily Work session files; an area with
no linked project has no time, never a made-up zero.
"""
from __future__ import annotations

import json
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any

NOTE_FILE = Path.home() / "ObsidianVault" / "AMBITIONS-DREAMS" / "ТОЧКИ-РОСТА.md"
PICTURES = {"pe", "digital", "research", "podcast", "design", "coworking", "growth"}
TIME_WINDOW_DAYS = 30
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


def parse_note(text: str) -> list[dict[str, Any]]:
    areas: list[dict[str, Any]] = []
    used: set[str] = set()
    current: dict[str, Any] | None = None
    for line in text.splitlines():
        if line.startswith("## "):
            title = _clean(line[3:], 80)
            current = {"id": _slug(title, used), "title": title, "why": "", "picture": "growth",
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
            current["picture"] = picture if picture in PICTURES else "growth"
        elif name == "зачем":
            current["why"] = _clean(value)
        elif name == "проекты":
            current["projects"] = [_key(item) for item in value.split(",") if _key(item)]
    return areas


def _minutes_by_project(daily_work_dir: Path, today: date) -> dict[str, int]:
    """Active minutes per normalised project name over the last TIME_WINDOW_DAYS days."""
    since = (today - timedelta(days=TIME_WINDOW_DAYS - 1)).isoformat()
    totals: dict[str, int] = {}
    sessions_dir = daily_work_dir / "sessions"
    if not sessions_dir.is_dir():
        return totals
    for path in sessions_dir.glob("*/*.json"):
        if path.stem < since or path.stem > today.isoformat():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for session in payload.get("sessions") or []:
            name = _key(str(session.get("project") or ""))
            minutes = session.get("active_minutes")
            if name and isinstance(minutes, (int, float)) and minutes > 0:
                totals[name] = totals.get(name, 0) + int(minutes)
    return totals


def growth_projection(note_file: Path, daily_work_dir: Path, *, owner: bool, today: date | None = None) -> dict[str, Any]:
    try:
        text = note_file.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {"ok": True, "state": "empty", "owner_view": owner, "areas": [], "count": 0}
    except OSError:
        return {"ok": False, "state": "unavailable", "owner_view": owner, "areas": [], "count": 0}
    areas = parse_note(text)
    if not owner:
        # The public view says how many areas exist, never what they are.
        return {"ok": True, "state": "live", "owner_view": False, "areas": [], "count": len(areas)}
    minutes = _minutes_by_project(daily_work_dir, today or date.today())
    for area in areas:
        total = len(area["steps"])
        done = sum(1 for step in area["steps"] if step["done"])
        area["progress"] = {"done": done, "total": total}
        if area["projects"]:
            area["minutes_30d"] = sum(value for name, value in minutes.items()
                                      if any(key and key in name for key in area["projects"]))
        else:
            area["minutes_30d"] = None
        area.pop("projects")
    return {"ok": True, "state": "live", "owner_view": True, "areas": areas, "count": len(areas),
            "source": "Obsidian · AMBITIONS-DREAMS/ТОЧКИ-РОСТА.md", "window_days": TIME_WINDOW_DAYS}
