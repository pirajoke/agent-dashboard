"""Sessions open right now on Mark's Macs, for «Сессии» in Агенты (Mark 2026-10-25).

Each Mac writes ``~/.agent-bridge/live-sessions/<machine>.json`` every minute
(``live_sessions_collector.py``); the Mac mini serves them together to the owner only.
A Mac whose file is older than ``MACHINE_STALE`` is shown as out of touch and its sessions are left out:
they may long be closed.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

MACHINE_STALE = timedelta(minutes=10)
# A session with no step for this long folds under «Затихли».
QUIET_AFTER = timedelta(hours=2)
MACHINE_LABELS = {"mac-mini": "Mac mini", "macbook-pro": "MacBook Pro", "macbook-air": "MacBook Air"}
STATES = ("approve", "waiting", "working")
LINK_RE = re.compile(r"^(?:https://claude\.ai/code/session_[A-Za-z0-9_-]+|codex://threads/[A-Za-z0-9_.-]+)$")
FIELDS = ("id", "tool", "app", "title", "project", "branch", "started_at", "last_at", "reply", "resume")


def _parse(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else None


def machine_label(machine: str) -> str:
    return MACHINE_LABELS.get(machine, machine.replace("-", " ").title())


def projection(directory: Path, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    sessions: list[dict[str, Any]] = []
    machines: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.json")) if directory.is_dir() else []:
        if path.name.startswith("."):
            continue
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(record, dict) or not isinstance(record.get("sessions"), list):
            continue
        machine = str(record.get("machine") or path.stem)
        collected = _parse(record.get("collected_at"))
        fresh = collected is not None and now - collected <= MACHINE_STALE
        machines.append({"machine": machine, "label": machine_label(machine), "fresh": fresh,
                         "collected_at": record.get("collected_at")})
        if not fresh:
            continue
        for raw in record["sessions"]:
            if not isinstance(raw, dict) or raw.get("state") not in STATES or raw.get("tool") not in {"claude", "codex"}:
                continue
            last = _parse(raw.get("last_at"))
            if last is None:
                continue
            session = {key: raw.get(key) for key in FIELDS}
            session["machine"] = machine_label(machine)
            session["state"] = raw["state"]
            session["quiet"] = raw["state"] == "waiting" and now - last >= QUIET_AFTER
            link = raw.get("link")
            session["link"] = link if isinstance(link, str) and LINK_RE.match(link) else None
            sessions.append(session)
    order = {state: index for index, state in enumerate(STATES)}
    sessions.sort(key=lambda s: s["last_at"] or "", reverse=True)
    sessions.sort(key=lambda s: (s["quiet"], order[s["state"]]))
    return {"state": "ready", "sessions": sessions, "machines": machines}
