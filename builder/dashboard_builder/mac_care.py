"""Care status of a MacBook for Техника (Mark 2026-11-02).

``builder/mac_care_collector.py`` on the MacBook writes
``~/.agent-bridge/mac-care/<machine>.json`` on the Mac mini every 15 minutes.
This module reads it for ``/api/machines/care``. Only the owner gets the facts:
process names, firewall state and update lists are not for the public page.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

STALE_AFTER_SECONDS = 45 * 60
_MACHINE = re.compile(r"^[a-z0-9-]{1,40}$")
_SECTIONS = ("watchdog", "hygiene", "restart", "firewall", "updates", "swap", "top_processes", "disabled_agents")


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def care_projection(care_dir: Path, machine: str, *, owner: bool, now: datetime | None = None) -> dict[str, Any]:
    if not _MACHINE.match(machine or ""):
        return {"ok": False, "state": "unknown_machine"}
    if not owner:
        return {"ok": True, "state": "owner_only", "machine": machine}
    path = care_dir / f"{machine}.json"
    if not path.exists():
        # Without --machine the collector names the file after the host, e.g. «macbook-pro-de-max».
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
    return payload
