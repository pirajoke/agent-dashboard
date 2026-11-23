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
    if generated is None:  # without a time we cannot say how old it is
        return {"ok": False, "state": "unreadable"}
    age = int((now - generated).total_seconds())
    payload: dict[str, Any] = {
        "ok": True,
        "state": "stale" if age > STALE_AFTER_SECONDS else "fresh",
        "generated_at": data.get("at"),
        "age_seconds": age,
    }
    for key in _FIELDS:
        payload[key] = data.get(key)
    # Schema check: a field of the wrong shape becomes unknown (None), never a guess.
    for key in ("ticks", "ticks_max", "plans", "fix_closed", "green_streak"):
        if not _is_int(payload[key]):
            payload[key] = None
    for key in ("night_ok", "warn"):
        if not isinstance(payload[key], bool):
            payload[key] = None
    payload["beads"] = _counts(payload["beads"], ("new", "closed", "open"))  # bead ids are internal
    payload["review"] = _counts(payload["review"], ("green", "yellow", "red"))
    payload["autoloop"] = _counts(payload["autoloop"], ("total", "scheduled"))
    services = payload["failed_services"]
    payload["failed_services"] = ([str(x) for x in services if isinstance(x, str)]
                                  if isinstance(services, list) else None)
    return payload


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _counts(value: Any, keys: tuple[str, ...]) -> dict[str, int] | None:
    if not isinstance(value, dict) or not all(_is_int(value.get(k)) for k in keys):
        return None
    return {k: value[k] for k in keys}
