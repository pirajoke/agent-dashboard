"""Project scanning, TODO counting, LUMUS parsing."""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from .config import AGENTS, PROJECTS_DIR, LUMUS_FILE


def count_todos(todo_path: Path) -> tuple[int, int]:
    if not todo_path.exists():
        return 0, 0
    text = todo_path.read_text(encoding="utf-8")
    open_count = len(re.findall(r"- \[ \]", text))
    closed_count = len(re.findall(r"- \[x\]", text, re.IGNORECASE))
    return open_count, closed_count


def get_freshness_days(todo_path: Path) -> int:
    if not todo_path.exists():
        return 999
    mtime = datetime.fromtimestamp(todo_path.stat().st_mtime)
    return (datetime.now() - mtime).days


def parse_lumus() -> dict:
    projects = {}
    if not LUMUS_FILE.exists():
        return projects
    text = LUMUS_FILE.read_text(encoding="utf-8")
    for m in re.finditer(
        r"\|\s*\d+\s*\|\s*([A-Z0-9 -]+?)\s*\|\s*(\w+)\s*\|\s*(\d+)\s*\|\s*(.+?)\s*\|",
        text,
    ):
        name = m.group(1).strip()
        projects[name] = {
            "status": m.group(2).strip(),
            "open_todos": int(m.group(3)),
            "next_action": m.group(4).strip(),
        }
    return projects


def scan_projects() -> list[dict]:
    lumus = parse_lumus()
    results = []
    if not PROJECTS_DIR.exists():
        return results
    for d in sorted(PROJECTS_DIR.iterdir()):
        if not d.is_dir():
            continue
        name = d.name
        todo_path = d / "Tech-Base" / "TODO.md"
        open_c, closed_c = count_todos(todo_path)
        freshness = get_freshness_days(todo_path)
        ldata = lumus.get(name, {})
        agents = [a["id"] for a in AGENTS if name in a["projects"]]
        has_real_todo = todo_path.exists()
        open_todos = open_c if has_real_todo else int(ldata.get("open_todos", 0))
        results.append({
            "name": name,
            "status": ldata.get("status", "—"),
            "open_todos": open_todos,
            "closed_todos": closed_c,
            "freshness_days": freshness,
            "next_action": ldata.get("next_action", "—"),
            "agents": agents,
        })
    return results


def is_project_active(p: dict) -> bool:
    status = p.get("status", "").lower()
    if status in ("done", "completed", "archived"):
        return False
    if p["open_todos"] == 0 and p["closed_todos"] > 0:
        return False
    if p["open_todos"] > 0:
        return True
    if status in ("active", "pause", "paused"):
        return True
    return status not in ("", "—")
