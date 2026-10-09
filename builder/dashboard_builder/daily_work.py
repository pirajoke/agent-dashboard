"""Daily work projection for the Command Center Work section.

Reads what ``daily_work_collector.py`` wrote (per-machine session days plus a
GitHub snapshot) and turns it into one JSON payload: a day series for the
traction chart, the selected day's breakdown, and the dropped / forgotten
lists. Time is an estimate from session activity, with breaks over 30
minutes left out, and is labelled as such in the UI.

The public projection (no owner token) carries numbers only: no project
names, PR titles, branches or session topics.
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

TOOLS = ("claude", "codex")
DEFAULT_DAYS = 30
STALE_AFTER = timedelta(hours=6)
DROPPED_AFTER = timedelta(hours=48)
FORGOTTEN_AFTER = timedelta(days=7)
BRANCH_LOOKBACK = timedelta(days=30)
MAIN_BRANCHES = {"main", "master", "head", "develop", "dev", "trunk"}
LIST_LIMIT = 12


def _ts(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else None


def _iso(moment: datetime | None) -> str | None:
    if moment is None:
        return None
    return moment.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _local_day(moment: datetime, tz) -> str:
    return moment.astimezone(tz).date().isoformat()


def _union_minutes(intervals: Iterable[tuple[datetime, datetime]]) -> int:
    total = 0.0
    current: list[datetime] | None = None
    for start, end in sorted(intervals):
        if current is None or start > current[1]:
            if current is not None:
                total += (current[1] - current[0]).total_seconds()
            current = [start, end]
        else:
            current[1] = max(current[1], end)
    if current is not None:
        total += (current[1] - current[0]).total_seconds()
    return round(total / 60)


def _session_intervals(record: dict[str, Any]) -> list[tuple[datetime, datetime]]:
    result = []
    for pair in record.get("intervals") or []:
        if isinstance(pair, list) and len(pair) == 2:
            start, end = _ts(pair[0]), _ts(pair[1])
            if start and end and end >= start:
                result.append((start, end))
    return result


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def load_sessions(root: Path, first_day: str, last_day: str) -> tuple[dict[str, list[dict]], dict[str, dict]]:
    """Return sessions by day (all machines) and the latest status per machine."""
    by_day: dict[str, list[dict]] = defaultdict(list)
    machines: dict[str, dict] = {}
    sessions_dir = root / "sessions"
    if not sessions_dir.is_dir():
        return by_day, machines
    for machine_dir in sorted(p for p in sessions_dir.iterdir() if p.is_dir()):
        for path in sorted(machine_dir.glob("*.json")):
            data = _read_json(path)
            if not isinstance(data, dict) or not isinstance(data.get("date"), str):
                continue
            machine = str(data.get("machine") or machine_dir.name)
            collected = _ts(data.get("collected_at"))
            known = machines.get(machine)
            if collected and (known is None or (_ts(known["collected_at"]) or collected) <= collected):
                machines[machine] = {"machine": machine, "collected_at": _iso(collected),
                                     "sources": data.get("sources") if isinstance(data.get("sources"), dict) else {}}
            if not first_day <= data["date"] <= last_day:
                continue
            for record in data.get("sessions") or []:
                if isinstance(record, dict) and record.get("tool") in TOOLS:
                    by_day[data["date"]].append({**record, "machine": machine})
    return by_day, machines


def _bucket_github(github: dict | None, tz) -> dict[str, dict[str, list]]:
    buckets: dict[str, dict[str, list]] = defaultdict(lambda: {"opened": [], "merged": [], "closed_unmerged": [], "commits": []})
    if not isinstance(github, dict) or not github.get("ok"):
        return buckets
    for pr in github.get("prs") or []:
        if not isinstance(pr, dict):
            continue
        created, merged, closed = _ts(pr.get("created_at")), _ts(pr.get("merged_at")), _ts(pr.get("closed_at"))
        if created:
            buckets[_local_day(created, tz)]["opened"].append(pr)
        if merged:
            buckets[_local_day(merged, tz)]["merged"].append(pr)
        elif closed and pr.get("state") == "closed":
            buckets[_local_day(closed, tz)]["closed_unmerged"].append(pr)
    for commit in github.get("commits") or []:
        moment = _ts(commit.get("date")) if isinstance(commit, dict) else None
        if moment:
            buckets[_local_day(moment, tz)]["commits"].append(commit)
    return buckets


def _day_totals(sessions: list[dict], gh: dict[str, list]) -> dict[str, Any]:
    tool_intervals: dict[str, list] = {tool: [] for tool in TOOLS}
    for record in sessions:
        tool_intervals[record["tool"]].extend(_session_intervals(record))
    all_intervals = [pair for pairs in tool_intervals.values() for pair in pairs]
    return {
        "claude_minutes": _union_minutes(tool_intervals["claude"]),
        "codex_minutes": _union_minutes(tool_intervals["codex"]),
        "total_minutes": _union_minutes(all_intervals),
        "sessions": len(sessions),
        "prompts": sum(int(record.get("prompts") or 0) for record in sessions),
        "project_count": len({record.get("project") for record in sessions}),
        "prs_opened": len(gh["opened"]),
        "prs_merged": len(gh["merged"]),
        "prs_closed_unmerged": len(gh["closed_unmerged"]),
        "commits": len(gh["commits"]),
    }


def _pr_view(pr: dict) -> dict[str, Any]:
    return {key: pr.get(key) for key in ("repo", "number", "title", "url", "draft", "created_at", "updated_at", "merged_at", "closed_at")}


def _project_rows(sessions: list[dict], gh: dict[str, list]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for record in sessions:
        grouped[str(record.get("project") or "без проекта")].append(record)
    repo_of = {name: next((r.get("repo") for r in records if r.get("repo")), None) for name, records in grouped.items()}
    rows = []
    for name, records in grouped.items():
        repo = repo_of[name]
        per_tool = {tool: _union_minutes(p for r in records if r["tool"] == tool for p in _session_intervals(r)) for tool in TOOLS}
        rows.append({
            "project": name,
            "repo": repo,
            "claude_minutes": per_tool["claude"],
            "codex_minutes": per_tool["codex"],
            "total_minutes": _union_minutes(p for r in records for p in _session_intervals(r)),
            "sessions": len(records),
            "prompts": sum(int(r.get("prompts") or 0) for r in records),
            "merged": [_pr_view(pr) for pr in gh["merged"] if repo and pr.get("repo") == repo],
            "opened": [_pr_view(pr) for pr in gh["opened"] if repo and pr.get("repo") == repo],
            "branches": sorted({r["branch"] for r in records if isinstance(r.get("branch"), str) and r["branch"].lower() not in MAIN_BRANCHES}),
        })
    rows.sort(key=lambda row: row["total_minutes"], reverse=True)
    return rows


def _session_rows(sessions: list[dict]) -> list[dict[str, Any]]:
    rows = [
        {key: record.get(key) for key in ("tool", "machine", "project", "repo", "branch", "start", "end", "active_minutes", "prompts", "topic")}
        for record in sessions
    ]
    rows.sort(key=lambda row: row.get("start") or "")
    return rows


def _branches_without_pr(by_day: dict[str, list[dict]], github: dict | None) -> list[dict[str, Any]]:
    if not isinstance(github, dict) or not github.get("ok"):
        return []
    heads = github.get("pr_heads") if isinstance(github.get("pr_heads"), dict) else {}
    pr_branches = {(repo, pull.get("head")) for repo, pulls in heads.items() for pull in pulls or [] if isinstance(pull, dict)}
    latest: dict[tuple[str, str], dict[str, Any]] = {}
    for records in by_day.values():
        for record in records:
            repo, branch = record.get("repo"), record.get("branch")
            if not isinstance(repo, str) or not isinstance(branch, str) or branch.lower() in MAIN_BRANCHES:
                continue
            if repo not in heads or (repo, branch) in pr_branches:
                continue
            end = _ts(record.get("end"))
            key = (repo, branch)
            item = latest.setdefault(key, {"repo": repo, "branch": branch, "project": record.get("project"),
                                           "last_activity": None, "minutes": 0, "tools": set(), "topic": None})
            item["minutes"] += int(record.get("active_minutes") or 0)
            item["tools"].add(record["tool"])
            if end and (item["last_activity"] is None or end > item["last_activity"]):
                item["last_activity"] = end
                item["topic"] = record.get("topic") or item["topic"]
    result = []
    for item in latest.values():
        if item["last_activity"] is None:
            continue
        result.append({**item, "tools": sorted(item["tools"])})
    return result


def _age_days(moment: datetime | None, now: datetime) -> int | None:
    return None if moment is None else max(0, (now - moment).days)


def work_projection(root: Path, *, now: datetime | None = None, days: int = DEFAULT_DAYS,
                    selected: str | None = None, owner: bool = False) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    tz = now.astimezone().tzinfo
    today = now.astimezone(tz).date()
    days = max(7, min(int(days or DEFAULT_DAYS), 90))
    series_days = [(today - timedelta(days=offset)).isoformat() for offset in range(days - 1, -1, -1)]
    default_day = (today - timedelta(days=1)).isoformat()
    try:
        selected_day = date.fromisoformat(selected).isoformat() if selected else default_day
    except ValueError:
        selected_day = default_day
    if selected_day not in series_days:
        selected_day = default_day

    lookback_first = min(series_days[0], (today - BRANCH_LOOKBACK).isoformat())
    by_day, machines = load_sessions(root, lookback_first, today.isoformat())
    github = _read_json(root / "github.json")
    github_error = _read_json(root / "github-error.json")
    gh_days = _bucket_github(github, tz)

    series = [{"date": day, **_day_totals(by_day.get(day, []), gh_days[day])} for day in series_days]
    selected_sessions = by_day.get(selected_day, [])
    selected_gh = gh_days[selected_day]
    day_view: dict[str, Any] = {"date": selected_day, "is_today": selected_day == today.isoformat(),
                                **_day_totals(selected_sessions, selected_gh)}

    # Dropped: work that ended without an outcome in the last 7 days.
    # Forgot: still open, untouched for 7+ days.
    branches = _branches_without_pr(by_day, github)
    dropped: list[dict[str, Any]] = []
    forgot: list[dict[str, Any]] = []
    for item in branches:
        age = now - item["last_activity"]
        entry = {"kind": "branch", "repo": item["repo"], "project": item["project"], "branch": item["branch"],
                 "tools": item["tools"], "minutes": item["minutes"], "topic": item["topic"],
                 "last_activity": _iso(item["last_activity"]), "age_days": _age_days(item["last_activity"], now)}
        if DROPPED_AFTER <= age < FORGOTTEN_AFTER:
            dropped.append(entry)
        elif age >= FORGOTTEN_AFTER:
            forgot.append(entry)
    if isinstance(github, dict) and github.get("ok"):
        week_ago = now - FORGOTTEN_AFTER
        for pr in github.get("prs") or []:
            closed, updated = _ts(pr.get("closed_at")), _ts(pr.get("updated_at"))
            if pr.get("state") == "closed" and not pr.get("merged_at") and closed and closed >= week_ago:
                dropped.append({"kind": "pr_closed", **_pr_view(pr), "age_days": _age_days(closed, now)})
            elif pr.get("state") == "open" and updated and updated < week_ago:
                forgot.append({"kind": "pr_open", **_pr_view(pr), "age_days": _age_days(updated, now)})
        for issue in github.get("open_issues") or []:
            updated = _ts(issue.get("updated_at")) if isinstance(issue, dict) else None
            if updated and updated < week_ago:
                forgot.append({"kind": "issue_open", **{k: issue.get(k) for k in ("repo", "number", "title", "url", "updated_at")},
                               "age_days": _age_days(updated, now)})
    dropped.sort(key=lambda item: item.get("age_days") or 0)
    forgot.sort(key=lambda item: item.get("age_days") or 0, reverse=True)

    def window_sum(offset: int) -> dict[str, int]:
        # Complete days only: the 7 days before today, then the 7 before those.
        chunk = series[-1 - offset - 7: len(series) - 1 - offset]
        return {key: sum(day[key] for day in chunk) for key in ("total_minutes", "claude_minutes", "codex_minutes", "sessions", "prs_merged", "commits")}

    streak = 0
    for day in reversed(series[:-1]):
        if day["total_minutes"] <= 0:
            break
        streak += 1

    newest = max((_ts(m["collected_at"]) for m in machines.values() if _ts(m["collected_at"])), default=None)
    gh_collected = _ts(github.get("collected_at")) if isinstance(github, dict) else None
    sources = {
        "machines": sorted(machines.values(), key=lambda m: m["machine"]),
        "github": {
            "ok": bool(isinstance(github, dict) and github.get("ok")),
            "collected_at": _iso(gh_collected),
            "last_error": github_error.get("reason") if isinstance(github_error, dict)
            and (_ts(github_error.get("collected_at")) or now) > (gh_collected or now - timedelta(days=999)) else None,
        },
    }
    state = "empty" if newest is None else ("stale" if now - newest > STALE_AFTER else "live")

    payload: dict[str, Any] = {
        "ok": True,
        "owner_view": owner,
        "state": state,
        "generated_at": _iso(now),
        "collected_at": _iso(newest),
        "timezone": str(tz),
        "time_estimate_note": "Оценка по активности сессий: перерывы больше 30 минут не считаются.",
        "selected_date": selected_day,
        "series": series,
        "traction": {"last_7": window_sum(0), "previous_7": window_sum(7), "streak_days": streak},
        "day": day_view,
        "dropped_count": len(dropped),
        "forgot_count": len(forgot),
    }
    if owner:
        day_view["projects"] = _project_rows(selected_sessions, selected_gh)
        day_view["sessions_detail"] = _session_rows(selected_sessions)
        day_view["merged"] = [_pr_view(pr) for pr in selected_gh["merged"]]
        day_view["opened"] = [_pr_view(pr) for pr in selected_gh["opened"]]
        day_view["closed_unmerged"] = [_pr_view(pr) for pr in selected_gh["closed_unmerged"]]
        payload["dropped"] = dropped[:LIST_LIMIT]
        payload["forgot"] = forgot[:LIST_LIMIT]
        payload["sources"] = sources
    else:
        payload["sources"] = {
            "machines": [{"machine": f"machine-{i + 1}", "collected_at": m["collected_at"]} for i, m in enumerate(sources["machines"])],
            "github": {"ok": sources["github"]["ok"], "collected_at": sources["github"]["collected_at"]},
        }
    return payload
