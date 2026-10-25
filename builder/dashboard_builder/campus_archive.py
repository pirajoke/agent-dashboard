"""Campus archive: projects Mark is not working on leave the campus map.

Mark 2026-10-25: «Проекты, над которыми я сейчас не работаю, не удаляются с карты, они идут в
архивную какую-то историю. Здесь они мусорят просто». A project agent goes to the archive when it
has had no work for ``IDLE_DAYS`` days, or when Mark puts it there himself. Nothing is deleted:
the archive lists them and «Вернуть» puts one back on the map. Any new work brings a project back
on its own. The store lives on the Mac mini, so every device shows the same map.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import tempfile
import threading
from typing import Any

IDLE_DAYS = 7
MAX_BODY_BYTES = 1024
MAX_ROUTES = 64
# The coordinator is the campus itself, never «a project Mark is not working on».
ALWAYS_ON_MAP = frozenset({"main-manager"})

_STORE_LOCK = threading.Lock()  # The server is threaded; one archive change at a time.
_ROUTE_ID = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$")
_FIELDS = ("last_seen", "archived_at", "restored_at")


def _utc(moment: datetime) -> datetime:
    return (moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


def _iso(moment: datetime) -> str:
    return _utc(moment).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return _utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
    except ValueError:
        return None


def _clean_store(data: object) -> dict[str, dict[str, str]]:
    clean: dict[str, dict[str, str]] = {field: {} for field in _FIELDS}
    if not isinstance(data, dict):
        return clean
    for field in _FIELDS:
        entries = data.get(field)
        if not isinstance(entries, dict):
            continue
        for route_id, value in list(entries.items())[:MAX_ROUTES]:
            moment = _parse(value)
            if isinstance(route_id, str) and _ROUTE_ID.fullmatch(route_id) and moment is not None:
                clean[field][route_id] = _iso(moment)
    return clean


def load_archive(path: Path) -> dict[str, dict[str, str]]:
    """Read the store; anything unreadable counts as an empty archive rather than an error."""
    try:
        return _clean_store(json.loads(Path(path).read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError):
        return _clean_store(None)


def _write(path: Path, store: dict[str, dict[str, str]], now: datetime) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=".campus-archive.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump({**store, "updated_at": _iso(now)}, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.chmod(temp, 0o600)
        os.replace(temp, path)
    except BaseException:
        try:
            os.unlink(temp)
        except OSError:
            pass
        raise


def remember_activity(path: Path, agents: object, *, now: datetime) -> dict[str, dict[str, str]]:
    """Keep the newest work time seen per project agent; the live checkpoint only covers recent sessions."""
    now = _utc(now)
    with _STORE_LOCK:
        store = load_archive(path)
        changed = False
        for agent in agents if isinstance(agents, list) else []:
            if not isinstance(agent, dict):
                continue
            route_id, seen = agent.get("route_id"), _parse(agent.get("state_at"))
            if not isinstance(route_id, str) or not _ROUTE_ID.fullmatch(route_id) or seen is None or seen > now:
                continue
            known = _parse(store["last_seen"].get(route_id))
            if known is None or seen > known:
                store["last_seen"][route_id] = _iso(seen)
                changed = True
        if changed:
            _write(path, store, now)
        return store


def archive_reason(route_id: str, store: dict[str, dict[str, str]], *, now: datetime) -> str | None:
    """``"manual"`` or ``"idle"`` when the project belongs in the archive, otherwise ``None``."""
    if route_id in ALWAYS_ON_MAP:
        return None
    now = _utc(now)
    times = [_parse(store["last_seen"].get(route_id)), _parse(store["restored_at"].get(route_id))]
    latest = max((moment for moment in times if moment is not None), default=None)
    archived_at = _parse(store["archived_at"].get(route_id))
    if archived_at is not None and (latest is None or archived_at >= latest):
        return "manual"
    if latest is None or now - latest > timedelta(days=IDLE_DAYS):
        return "idle"
    return None


def split_agents(agents: list[dict], store: dict[str, dict[str, str]], *, now: datetime) -> tuple[list[dict], list[dict]]:
    """Return (agents on the map, archive rows) in the roster's own order."""
    on_map: list[dict] = []
    archived: list[dict] = []
    for agent in agents:
        route_id = agent.get("route_id") if isinstance(agent, dict) else None
        reason = archive_reason(route_id, store, now=now) if isinstance(route_id, str) else None
        if reason is None:
            on_map.append(agent)
        else:
            archived.append({"route_id": route_id, "project": agent.get("project"), "reason": reason})
    return on_map, archived


def change_archive(path: Path, payload: object, *, known_routes: set[str], now: datetime) -> dict[str, dict[str, str]]:
    """Apply ``{"route": id, "archived": bool}`` from Mark's «В архив» or «Вернуть» button."""
    if not isinstance(payload, dict) or set(payload) != {"route", "archived"}:
        raise ValueError("archive_change_expected")
    route_id, archived = payload["route"], payload["archived"]
    if not isinstance(route_id, str) or route_id not in known_routes or type(archived) is not bool:
        raise ValueError("invalid_route")
    if route_id in ALWAYS_ON_MAP:
        raise ValueError("always_on_map")
    now = _utc(now)
    with _STORE_LOCK:
        store = load_archive(path)
        if archived:
            store["archived_at"][route_id] = _iso(now)
            store["restored_at"].pop(route_id, None)
        else:
            store["archived_at"].pop(route_id, None)
            store["restored_at"][route_id] = _iso(now)
        _write(path, store, now)
        return store


def activity_counts(agents: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "enabled": len(agents),
        "running": sum(agent["state"] == "running" for agent in agents),
        "idle": sum(agent["state"] == "idle" for agent in agents),
        "waiting": sum(agent["state"] == "waiting" for agent in agents),
        "blocked": sum(agent["state"] == "blocked" for agent in agents),
        "done": sum(agent["state"] == "done" for agent in agents),
        "unavailable": sum(agent["availability"] != "available" for agent in agents),
        "turn_completed": sum(agent["outcome_stage"] == "turn_completed" for agent in agents),
    }


def apply_campus_archive(payload: dict, path: Path, *, now: datetime) -> dict:
    """Move archived project agents off the campus payload into ``payload["archive"]``."""
    agents = payload.get("agents")
    if not isinstance(agents, list):
        return payload
    try:
        store = remember_activity(path, agents, now=now)
    except OSError:
        store = load_archive(path)
    on_map, archived = split_agents(agents, store, now=now)
    payload["agents"] = on_map
    payload["activity_counts"] = activity_counts(on_map)
    payload["archive"] = archived
    payload["archive_idle_days"] = IDLE_DAYS
    return payload
