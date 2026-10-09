"""Infrastructure change log for the Command Center Infra tab.

Merges three real sources into one timeline:

- snapshot diffs written by ``infra_change_collector.py`` on each Mac
  (launchd, Docker, Homebrew services, ports, checkouts, runtime scripts,
  tunnel config, crontab);
- infra-changing shell commands run by Claude Code and Codex, extracted by
  ``daily_work_collector.py``;
- merged pull requests from the Daily Work GitHub snapshot.

The public projection carries counts only.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

DEFAULT_DAYS = 14
STALE_AFTER = timedelta(minutes=30)
EVENT_LIMIT = 600
CATEGORIES = {
    "agent": "Команды агентов",
    "pr": "Merge PR",
    "repo": "Код на машине",
    "launchd": "Сервисы launchd",
    "docker": "Docker",
    "brew": "Homebrew",
    "port": "Порты",
    "runtime": "Скрипты",
    "tunnel": "Туннель",
    "cron": "Cron",
    "baseline": "Начало записи",
}


def _ts(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else None


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _snapshot_events(root: Path, since: datetime) -> tuple[list[dict], list[dict]]:
    events: list[dict] = []
    machines: list[dict] = []
    if not root.is_dir():
        return events, machines
    for machine_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        state = _read_json(machine_dir / "state.json")
        if isinstance(state, dict):
            machines.append({"machine": state.get("machine") or machine_dir.name,
                             "collected_at": state.get("collected_at"),
                             "unavailable": state.get("unavailable") or []})
        for path in sorted(machine_dir.glob("events-*.jsonl")):
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except OSError:
                continue
            for line in lines:
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                at = _ts(event.get("at")) if isinstance(event, dict) else None
                if at is None or at < since or event.get("category") not in CATEGORIES:
                    continue
                events.append({**event, "machine": event.get("machine") or machine_dir.name, "source": "snapshot"})
    return events, machines


def _agent_events(work_root: Path, since: datetime) -> list[dict]:
    events: list[dict] = []
    sessions_dir = work_root / "sessions"
    if not sessions_dir.is_dir():
        return events
    first_day = since.date().isoformat()
    for path in sessions_dir.glob("*/*.json"):
        if path.stem < first_day:
            continue
        data = _read_json(path)
        if not isinstance(data, dict):
            continue
        machine = data.get("machine") or path.parent.name
        for session in data.get("sessions") or []:
            if not isinstance(session, dict):
                continue
            for action in session.get("infra_actions") or []:
                at = _ts(action.get("at")) if isinstance(action, dict) else None
                if at is None or at < since:
                    continue
                tool = "Claude" if session.get("tool") == "claude" else "Codex"
                target = action.get("host") or machine
                events.append({
                    "at": action["at"], "machine": machine, "category": "agent", "action": "command",
                    "subject": f"{tool} · {session.get('project') or 'без проекта'}",
                    "detail": action.get("command"), "host": target, "topic": session.get("topic"),
                    "source": "agent",
                })
    return events


def _pr_events(work_root: Path, since: datetime) -> list[dict]:
    github = _read_json(work_root / "github.json")
    if not isinstance(github, dict) or not github.get("ok"):
        return []
    events = []
    for pr in github.get("prs") or []:
        merged = _ts(pr.get("merged_at")) if isinstance(pr, dict) else None
        if merged is None or merged < since:
            continue
        events.append({
            "at": _iso(merged), "machine": "github", "category": "pr", "action": "merged",
            "subject": f"{pr.get('repo')}#{pr.get('number')}", "detail": pr.get("title"),
            "url": pr.get("url"), "source": "github",
        })
    return events


def infra_projection(root: Path, work_root: Path, *, now: datetime | None = None,
                     days: int = DEFAULT_DAYS, owner: bool = False) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    tz = now.astimezone().tzinfo
    days = max(1, min(int(days or DEFAULT_DAYS), 60))
    since = now - timedelta(days=days)
    snapshot_events, machines = _snapshot_events(root, since)
    events = snapshot_events + _agent_events(work_root, since) + _pr_events(work_root, since)
    events.sort(key=lambda event: event["at"], reverse=True)
    counts = Counter(event["category"] for event in events)
    newest = max((_ts(m["collected_at"]) for m in machines if _ts(m["collected_at"])), default=None)
    state = "empty" if newest is None else ("stale" if now - newest > STALE_AFTER else "live")

    payload: dict[str, Any] = {
        "ok": True,
        "owner_view": owner,
        "state": state,
        "generated_at": _iso(now),
        "collected_at": _iso(newest) if newest else None,
        "days": days,
        "categories": [{"id": key, "label": label, "count": counts.get(key, 0)} for key, label in CATEGORIES.items()],
        "total": len(events),
    }
    if not owner:
        payload["machines"] = [{"machine": f"machine-{i + 1}", "collected_at": m["collected_at"]} for i, m in enumerate(machines)]
        return payload
    by_day: dict[str, list[dict]] = defaultdict(list)
    for event in events[:EVENT_LIMIT]:
        by_day[_ts(event["at"]).astimezone(tz).date().isoformat()].append(event)
    payload["machines"] = machines
    payload["truncated"] = len(events) > EVENT_LIMIT
    payload["timeline"] = [{"date": day, "events": items} for day, items in sorted(by_day.items(), reverse=True)]
    return payload
