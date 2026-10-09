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
import re
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
PROJECT_DAY_LIMIT = 30
# Products as Command Center's Platforms tab shows them; the mascot is the
# Platforms SVG symbol (cc-mascot-<mascot>). Sessions and PRs are matched by
# the checkout folder or repo name.
PRODUCTS = (
    {"id": "command-center", "name": "Command Center", "mascot": "hub", "match": ("agentdashboard", "commandcenter")},
    {"id": "financial", "name": "JobRadar / Financial OS", "mascot": "jobradar", "match": ("financial", "jobradar", "jobsradar", "propertyos")},
    {"id": "mydictionary", "name": "Lexi", "mascot": "dictionary", "match": ("lexi", "dictionary")},
    {"id": "health", "name": "Health OS", "mascot": "health", "match": ("health",)},
    {"id": "ai-singularity", "name": "AI Singularity", "mascot": "singularity", "match": ("singularity",)},
    {"id": "context-news", "name": "Context News France", "mascot": "news", "match": ("contextnews",)},
    {"id": "accountable", "name": "Accountable OS", "mascot": "accountable", "match": ("accountable",)},
    {"id": "jarvis", "name": "JARVIS", "mascot": "jarvis", "match": ("jarvis",)},
)


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


def _norm(value: object) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def product_for(project: object, repo: object) -> dict[str, Any]:
    """Map a checkout folder / repo to a Platforms product, or to itself."""
    keys = [key for key in (_norm(project), _norm(str(repo or "").rsplit("/", 1)[-1])) if key]
    for product in PRODUCTS:
        if any(match in key for key in keys for match in product["match"]):
            return {"id": product["id"], "name": product["name"], "mascot": product["mascot"]}
    name = str(project or (str(repo).rsplit("/", 1)[-1] if repo else "") or "без проекта")
    return {"id": "p-" + (_norm(name) or "other"), "name": name, "mascot": None}


def _project_portfolio(series_days: list[str], by_day: dict[str, list[dict]], github: dict | None,
                       gh_days: dict[str, dict[str, list]], loose: list[dict], now: datetime) -> dict[str, dict[str, Any]]:
    """Per-product work over the window, keyed by product id."""
    products: dict[str, dict[str, Any]] = {}

    def entry(product: dict[str, Any]) -> dict[str, Any]:
        return products.setdefault(product["id"], {
            **product, "repos": set(), "projects": set(), "sessions_by_day": defaultdict(list),
            "prs_by_day": defaultdict(lambda: {"merged": [], "opened": [], "closed_unmerged": []}),
        })

    repo_product: dict[str, str] = {}
    for day in series_days:
        for record in by_day.get(day, []):
            item = entry(product_for(record.get("project"), record.get("repo")))
            item["sessions_by_day"][day].append(record)
            item["projects"].add(str(record.get("project") or ""))
            if record.get("repo"):
                item["repos"].add(record["repo"])
                repo_product.setdefault(record["repo"], item["id"])
    # PRs count for the product of their repo, also when the work happened in
    # sessions this collector cannot see (for example claude.ai/code).
    for day in series_days:
        for kind in ("merged", "opened", "closed_unmerged"):
            for pr in gh_days[day][kind]:
                repo = pr.get("repo")
                if not repo:
                    continue
                product_id = repo_product.get(repo)
                item = products[product_id] if product_id else entry(product_for(None, repo))
                item["repos"].add(repo)
                repo_product.setdefault(repo, item["id"])
                item["prs_by_day"][day][kind].append(pr)
    open_prs: dict[str, list[dict]] = defaultdict(list)
    if isinstance(github, dict) and github.get("ok"):
        for pr in github.get("prs") or []:
            if isinstance(pr, dict) and pr.get("state") == "open" and pr.get("repo") in repo_product:
                open_prs[repo_product[pr["repo"]]].append(pr)
    for item in products.values():
        item["open_prs"] = sorted(open_prs.get(item["id"], []), key=lambda pr: pr.get("updated_at") or "", reverse=True)
        item["loose"] = [entry_ for entry_ in loose if entry_.get("repo") in item["repos"]
                         or (entry_.get("project") and entry_.get("project") in item["projects"])]
    return products


def _portfolio_summary(item: dict[str, Any], series_days: list[str]) -> dict[str, Any]:
    daily, daily_prs, claude, codex = [], [], [], []
    last_activity, last_topic = None, None
    sessions = prompts = 0
    for day in series_days:
        records = item["sessions_by_day"].get(day, [])
        pairs = [pair for record in records for pair in _session_intervals(record)]
        daily.append(_union_minutes(pairs))
        claude.append(_union_minutes(p for r in records if r["tool"] == "claude" for p in _session_intervals(r)))
        codex.append(_union_minutes(p for r in records if r["tool"] == "codex" for p in _session_intervals(r)))
        daily_prs.append(len(item["prs_by_day"][day]["merged"]) if day in item["prs_by_day"] else 0)
        sessions += len(records)
        prompts += sum(int(r.get("prompts") or 0) for r in records)
        for record in records:
            end = _ts(record.get("end"))
            if end and (last_activity is None or end > last_activity):
                last_activity, last_topic = end, record.get("topic") or last_topic
    for day, prs in item["prs_by_day"].items():
        for pr in prs["merged"] + prs["opened"]:
            moment = _ts(pr.get("merged_at")) or _ts(pr.get("created_at"))
            if moment and (last_activity is None or moment > last_activity):
                last_activity, last_topic = moment, pr.get("title") or last_topic
    complete = daily[:-1]
    return {
        "id": item["id"], "name": item["name"], "mascot": item["mascot"],
        "repos": sorted(item["repos"]), "projects": sorted(p for p in item["projects"] if p),
        "total_minutes": sum(daily), "claude_minutes": sum(claude), "codex_minutes": sum(codex),
        "last_7_minutes": sum(complete[-7:]), "previous_7_minutes": sum(complete[-14:-7]),
        "active_days": sum(1 for minutes in daily if minutes > 0),
        "sessions": sessions, "prompts": prompts,
        "daily_minutes": daily, "daily_prs_merged": daily_prs,
        "prs_merged": sum(daily_prs),
        "prs_opened": sum(len(prs["opened"]) for prs in item["prs_by_day"].values()),
        "prs_open": len(item["open_prs"]), "loose": len(item["loose"]),
        "last_activity": _iso(last_activity), "last_topic": last_topic,
    }


def _project_detail(item: dict[str, Any], series_days: list[str]) -> dict[str, Any]:
    detail = _portfolio_summary(item, series_days)
    detail["daily_claude_minutes"] = [
        _union_minutes(p for r in item["sessions_by_day"].get(day, []) if r["tool"] == "claude" for p in _session_intervals(r))
        for day in series_days]
    detail["daily_codex_minutes"] = [
        _union_minutes(p for r in item["sessions_by_day"].get(day, []) if r["tool"] == "codex" for p in _session_intervals(r))
        for day in series_days]
    timeline = []
    for index, day in reversed(list(enumerate(series_days))):
        records = item["sessions_by_day"].get(day, [])
        prs = item["prs_by_day"].get(day) or {"merged": [], "opened": [], "closed_unmerged": []}
        if not records and not any(prs.values()):
            continue
        commands = [
            {"at": action.get("at"), "command": action.get("command"), "host": action.get("host") or record.get("machine"),
             "tool": record["tool"]}
            for record in records for action in record.get("infra_actions") or [] if isinstance(action, dict)]
        timeline.append({
            "date": day,
            "minutes": detail["daily_minutes"][index],
            "claude_minutes": detail["daily_claude_minutes"][index],
            "codex_minutes": detail["daily_codex_minutes"][index],
            "sessions": _session_rows(records),
            "merged": [_pr_view(pr) for pr in prs["merged"]],
            "opened": [_pr_view(pr) for pr in prs["opened"] if pr not in prs["merged"]],
            "closed_unmerged": [_pr_view(pr) for pr in prs["closed_unmerged"]],
            "commands": sorted(commands, key=lambda c: c.get("at") or ""),
        })
        if len(timeline) >= PROJECT_DAY_LIMIT:
            break
    detail["timeline"] = timeline
    detail["open_prs_list"] = [_pr_view(pr) for pr in item["open_prs"]]
    detail["loose_list"] = item["loose"][:LIST_LIMIT]
    return detail


def _age_days(moment: datetime | None, now: datetime) -> int | None:
    return None if moment is None else max(0, (now - moment).days)


def work_projection(root: Path, *, now: datetime | None = None, days: int = DEFAULT_DAYS,
                    selected: str | None = None, owner: bool = False, project: str | None = None) -> dict[str, Any]:
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
    portfolio = _project_portfolio(series_days, by_day, github, gh_days,
                                   [{**item, "bucket": "dropped"} for item in dropped] + [{**item, "bucket": "forgot"} for item in forgot], now)
    summaries = sorted((_portfolio_summary(item, series_days) for item in portfolio.values()),
                       key=lambda item: (item["last_activity"] or "", item["total_minutes"]), reverse=True)

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
        "project_total": len(summaries),
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
        payload["projects"] = summaries
        if project:
            payload["project"] = _project_detail(portfolio[project], series_days) if project in portfolio else None
    else:
        payload["sources"] = {
            "machines": [{"machine": f"machine-{i + 1}", "collected_at": m["collected_at"]} for i, m in enumerate(sources["machines"])],
            "github": {"ok": sources["github"]["ok"], "collected_at": sources["github"]["collected_at"]},
        }
    return payload
