"""«Здоровье каркаса» for Техника → Mac mini (Макс 2026-11-23, HQ «сделай плитку»).

``hq/scripts/frame/heartbeat.py`` in pirajoke/hq runs every hour on the Mac mini and, after each tick,
writes ``~/.agent-bridge/frame-health.json`` with ``health.py --out``: hourly tact, beads, night walk,
executor, Лорен Тан plans, review verdicts, failed launchd services and agent-autoloop rules.
This module turns that file into ``/api/frame/health``. Service names and counts stay owner only.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# The file is rewritten every hour; two missed ticks mean the frame itself stopped.
STALE_AFTER_SECONDS = 2 * 60 * 60 + 15 * 60
_FIELDS = ("ticks", "ticks_max", "beads", "plans", "night_ok", "fix_closed", "failed_services", "review",
           "green_streak", "warn", "autoloop")


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def frame_health_projection(path: Path, *, owner: bool, now: datetime | None = None) -> dict[str, Any]:
    if not owner:
        return {"ok": True, "state": "owner_only"}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"ok": True, "state": "not_installed"}
    except (OSError, json.JSONDecodeError):
        return {"ok": False, "state": "unreadable"}
    if not isinstance(data, dict):
        return {"ok": False, "state": "unreadable"}
    now = now or datetime.now(timezone.utc)
    generated = _parse_time(data.get("at"))
    age = int((now - generated).total_seconds()) if generated else None
    payload: dict[str, Any] = {
        "ok": True,
        "state": "stale" if age is None or age > STALE_AFTER_SECONDS else "fresh",
        "generated_at": data.get("at"),
        "age_seconds": age,
    }
    for key in _FIELDS:
        payload[key] = data.get(key)
    beads = payload.get("beads")
    if isinstance(beads, dict):  # bead ids are internal; the tile needs counts only
        payload["beads"] = {k: beads.get(k) for k in ("new", "closed", "open")}
    return payload
