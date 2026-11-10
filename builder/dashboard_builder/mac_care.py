"""Care status of a MacBook for Техника (Mark 2026-11-02).

``builder/mac_care_collector.py`` on the MacBook writes
``~/.agent-bridge/mac-care/<machine>.json`` on the Mac mini every 15 minutes.
This module reads it for ``/api/machines/care``. Only the owner gets the facts:
process names, firewall state and update lists are not for the public page.

Temperature (Mark 2026-11-08): the collector keeps 7 days of readings; the page
gets the last 24 hours point by point and one line per day for the week, so the
answer stays small. The Mac mini writes its own file as ``mac-mini.json``.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

STALE_AFTER_SECONDS = 45 * 60
_MACHINE = re.compile(r"^[a-z0-9-]{1,40}$")
_SECTIONS = ("watchdog", "hygiene", "restart", "firewall", "updates", "swap", "top_processes", "disabled_agents",
             "thermal")
_PRESSURE_RANK = {"nominal": 0, "moderate": 1, "heavy": 2, "trapping": 3, "sleeping": 4}


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def thermal_projection(history: Any, now: datetime) -> dict[str, Any]:
    """7 days of readings → last 24 h of points + per-day peak/average (server's local days)."""
    points = []
    for point in history if isinstance(history, list) else []:
        if not isinstance(point, dict):
            continue
        moment = _parse_time(point.get("t"))
        cpu = point.get("cpu")
        if moment is None or moment > now + timedelta(minutes=5):
            continue
        points.append((moment, cpu if isinstance(cpu, (int, float)) else None, point.get("p")))
    points.sort(key=lambda item: item[0])
    day_ago = now - timedelta(hours=24)
    last_day = [{"t": moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"), "cpu": cpu, "p": pressure}
                for moment, cpu, pressure in points if moment >= day_ago]
    days: dict[str, dict[str, Any]] = {}
    for moment, cpu, pressure in points:
        key = moment.astimezone().date().isoformat()
        day = days.setdefault(key, {"day": key, "max": None, "sum": 0.0, "count": 0, "worst_pressure": None})
        if cpu is not None:
            day["max"] = cpu if day["max"] is None else max(day["max"], cpu)
            day["sum"] += cpu
            day["count"] += 1
        if pressure in _PRESSURE_RANK and (day["worst_pressure"] is None
                                          or _PRESSURE_RANK[pressure] > _PRESSURE_RANK[day["worst_pressure"]]):
            day["worst_pressure"] = pressure
    week = []
    for key in sorted(days)[-7:]:
        day = days[key]
        week.append({"day": key, "max": day["max"], "avg": round(day["sum"] / day["count"], 1) if day["count"] else None,
                     "worst_pressure": day["worst_pressure"]})
    return {"last_24h": last_day, "days": week}


def care_projection(care_dir: Path, machine: str, *, owner: bool, now: datetime | None = None) -> dict[str, Any]:
    if not _MACHINE.match(machine or ""):
        return {"ok": False, "state": "unknown_machine"}
    if not owner:
        return {"ok": True, "state": "owner_only", "machine": machine}
    path = care_dir / f"{machine}.json"
    if not path.exists():
        # Without --machine the collector names the file after the host, e.g. «macbook-pro-example».
        others = sorted(care_dir.glob(f"{machine}-*.json"), key=lambda item: item.stat().st_mtime, reverse=True)
        path = others[0] if others else path
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"ok": True, "state": "not_installed", "machine": machine}
    except (OSError, json.JSONDecodeError):
        return {"ok": False, "state": "unreadable", "machine": machine}
    if not isinstance(data, dict):
        return {"ok": False, "state": "unreadable", "machine": machine}
    now = now or datetime.now(timezone.utc)
    generated = _parse_time(data.get("generated_at"))
    age = int((now - generated).total_seconds()) if generated else None
    payload: dict[str, Any] = {
        "ok": True,
        "state": "stale" if age is None or age > STALE_AFTER_SECONDS else "fresh",
        "machine": machine,
        "generated_at": data.get("generated_at"),
        "age_seconds": age,
    }
    for key in _SECTIONS:
        payload[key] = data.get(key)
    payload["thermal_history"] = thermal_projection(data.get("thermal_history"), now)
    return payload
