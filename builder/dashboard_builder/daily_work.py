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
TODO_LIMIT = 8
FEED_DAYS = 14  # the summarizer writes the last 14 days
# A project with fewer minutes than this and no PR that day was a quick look, not work: it is
# not retold (daily_work_summarizer.py) and not listed in «По дням», only counted in the numbers.
NOISE_MINUTES = 3
# «Дела» takes next steps only from a summary this recent; older ones are probably done or stale.
TODO_NEXT_DAYS = 7
PROJECT_DAY_LIMIT = 30
# Products as Command Center's Platforms tab shows them; the mascot is the
# Platforms SVG symbol (cc-mascot-<mascot>). Sessions and PRs are matched by
# the checkout folder or repo name.
PRODUCTS = (
    {"id": "command-center", "name": "Command Center", "mascot": "hub", "match": ("agentdashboard", "commandcenter"),
     "description": "Командный центр: продукты, серверы и работа агентов на одном экране."},
    {"id": "financial", "name": "JobRadar / Financial OS", "mascot": "jobradar", "match": ("financial", "jobradar", "jobsradar", "propertyos"),
     "description": "Поиск работы и личные финансы: JobRadar, Financial OS и Property OS для недвижимости."},
    {"id": "mydictionary", "name": "Lexi", "mascot": "dictionary", "match": ("lexi", "dictionary"),
     "description": "Telegram-бот для изучения языков с личным словарём и админкой."},
    {"id": "health", "name": "Health OS", "mascot": "health", "match": ("health",),
     "description": "Личное пространство для здоровья."},
    # The news bot repo is ai-singularity-news-bot, so Context News is matched before AI Singularity.
    {"id": "context-news", "name": "Context News France", "mascot": "news", "match": ("contextnews", "singularitynews"),
     "description": "Telegram-бот с персональными подборками новостей."},
    {"id": "ai-singularity", "name": "AI Singularity", "mascot": "singularity", "match": ("singularity",),
     "description": "Закрытое приложение на Mac mini."},
    {"id": "accountable", "name": "Accountable OS", "mascot": "accountable", "match": ("accountable", "urssaf"),
     "description": "Учёт и налоги своей компании во Франции: URSSAF и отчётность EURL."},
    {"id": "jarvis", "name": "JARVIS", "mascot": "jarvis", "match": ("jarvis",),
     "description": "Личный ассистент в Telegram, который управляет остальными системами."},
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


def load_summaries(root: Path, days: Iterable[str]) -> dict[str, dict[str, Any]]:
    """Plain-language day summaries written by daily_work_summarizer.py, by day."""
    summaries: dict[str, dict[str, Any]] = {}
    for day in days:
        data = _read_json(root / "summaries" / f"{day}.json")
        if isinstance(data, dict) and data.get("date") == day and isinstance(data.get("projects"), dict):
            summaries[day] = data
    return summaries


def _bullets(summary: dict[str, Any] | None, product_id: str) -> list[str] | None:
    bullets = (summary or {}).get("projects", {}).get(product_id)
    if not isinstance(bullets, list):
        return None
    clean = [bullet.strip() for bullet in bullets if isinstance(bullet, str) and bullet.strip()]
    return clean or None


def _details(summary: dict[str, Any] | None, product_id: str) -> dict[str, Any] | None:
    """Lead, what Mark did, what agents did, next steps and deadlines (summaries schema 2)."""
    entry = ((summary or {}).get("details") or {}).get(product_id)
    if not isinstance(entry, dict):
        return None

    def lines(key: str) -> list[str]:
        value = entry.get(key)
        return [line.strip() for line in value if isinstance(line, str) and line.strip()] if isinstance(value, list) else []

    deadlines = [{"date": item["date"], "what": item["what"].strip()} for item in entry.get("deadlines") or []
                 if isinstance(item, dict) and isinstance(item.get("date"), str) and isinstance(item.get("what"), str)
                 and re.fullmatch(r"\d{4}-\d{2}-\d{2}", item["date"]) and item["what"].strip()]
    lead = entry.get("lead")
    return {"lead": lead.strip() if isinstance(lead, str) and lead.strip() else None,
            "you": lines("you"), "agents": lines("agents"), "next": lines("next"), "deadlines": deadlines}


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


def _issue_view(issue: dict) -> dict[str, Any]:
    return {key: issue.get(key) for key in ("repo", "number", "title", "url", "updated_at")}


def _latest_next(summaries: dict[str, dict[str, Any]] | None, product_id: str, days: list[str]) -> list[str]:
    """Next steps from the newest summary of these days that named any."""
    for day in reversed(days):
        details = _details((summaries or {}).get(day), product_id)
        if details and details["next"]:
            return details["next"]
    return []


def _quick_look(records: list[dict], prs: dict[str, list]) -> bool:
    """Nothing to retell: no PR, and under NOISE_MINUTES of work or no session with a title, an ask or
    a reply. The summarizer skips these and «По дням» does not list them."""
    if any(prs.values()):
        return False
    minutes = _union_minutes(p for r in records for p in _session_intervals(r))
    return minutes < NOISE_MINUTES or not any(r.get(key) for r in records for key in ("topic", "asks", "outcome"))


def _current_next(summaries: dict[str, dict[str, Any]], product_id: str, days: list[str]) -> tuple[str | None, list[str]]:
    """Next steps from the project's newest summary in the last TODO_NEXT_DAYS days, with its day.

    Unlike _latest_next, an older list is not reached for: when the newest summary names no next
    step, nothing is pending from the summaries."""
    for day in reversed(days[-TODO_NEXT_DAYS:]):
        details = _details(summaries.get(day), product_id)
        if details:
            return (day, details["next"]) if details["next"] else (None, [])
    return None, []


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
            return {key: product[key] for key in ("id", "name", "mascot", "description")}
    name = str(project or (str(repo).rsplit("/", 1)[-1] if repo else "") or "без проекта")
    return {"id": "p-" + (_norm(name) or "other"), "name": name, "mascot": None, "description": None}


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
    # A known product whose only news is an open issue still gets its to-do; unknown repos stay out.
    known = {product["id"] for product in PRODUCTS}
    if isinstance(github, dict) and github.get("ok"):
        for issue in github.get("open_issues") or []:
            repo = issue.get("repo") if isinstance(issue, dict) else None
            if not repo or repo in repo_product:
                continue
            product = product_for(None, repo)
            if product["id"] in known or product["id"] in products:
                item = entry(product)
                item["repos"].add(repo)
                repo_product[repo] = item["id"]
    open_prs: dict[str, list[dict]] = defaultdict(list)
    if isinstance(github, dict) and github.get("ok"):
        for pr in github.get("prs") or []:
            if isinstance(pr, dict) and pr.get("state") == "open" and pr.get("repo") in repo_product:
                open_prs[repo_product[pr["repo"]]].append(pr)
    # Open GitHub issues are the project's to-do list (the vault routes tasks to the owning repo's issues).
    open_issues: dict[str, list[dict]] = defaultdict(list)
    if isinstance(github, dict) and github.get("ok"):
        for issue in github.get("open_issues") or []:
            repo = issue.get("repo") if isinstance(issue, dict) else None
            product_id = repo_product.get(repo)
            if product_id in products:
                open_issues[product_id].append(issue)
    for item in products.values():
        item["open_prs"] = sorted(open_prs.get(item["id"], []), key=lambda pr: pr.get("updated_at") or "", reverse=True)
        item["open_issues"] = sorted(open_issues.get(item["id"], []), key=lambda issue: issue.get("updated_at") or "", reverse=True)
        item["loose"] = [entry_ for entry_ in loose if entry_.get("repo") in item["repos"]
                         or (entry_.get("project") and entry_.get("project") in item["projects"])]
    return products


def _portfolio_summary(item: dict[str, Any], series_days: list[str],
                       summaries: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
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
    last_summary = None
    for day in reversed(series_days):
        bullets = _bullets((summaries or {}).get(day), item["id"])
        if bullets:
            last_summary = {"date": day, "bullets": bullets}
            break
    return {
        "id": item["id"], "name": item["name"], "mascot": item["mascot"],
        "description": item.get("description"), "last_summary": last_summary,
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


def _project_detail(item: dict[str, Any], series_days: list[str],
                    summaries: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    detail = _portfolio_summary(item, series_days, summaries)
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
            "summary": _bullets((summaries or {}).get(day), item["id"]),
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
    detail["open_issues_list"] = [_issue_view(issue) for issue in item["open_issues"][:TODO_LIMIT]]
    detail["open_issues_count"] = len(item["open_issues"])
    detail["next_steps"] = _latest_next(summaries, item["id"], series_days)
    detail["loose_list"] = item["loose"][:LIST_LIMIT]
    return detail


def _day_summary(summary: dict[str, Any] | None, portfolio: dict[str, dict[str, Any]], day: str) -> dict[str, Any] | None:
    """The selected day's summary, one entry per product, busiest first."""
    if not summary:
        return None
    projects = []
    for product_id, item in portfolio.items():
        bullets = _bullets(summary, product_id)
        if not bullets:
            continue
        minutes = _union_minutes(p for r in item["sessions_by_day"].get(day, []) for p in _session_intervals(r))
        projects.append({"id": product_id, "name": item["name"], "mascot": item["mascot"],
                         "minutes": minutes, "bullets": bullets})
    projects.sort(key=lambda entry: entry["minutes"], reverse=True)
    headline = summary.get("day") if isinstance(summary.get("day"), str) else None
    return {"headline": headline, "generated_at": summary.get("generated_at"), "projects": projects}


def _has_activity(item: dict[str, Any], day: str) -> bool:
    prs = item["prs_by_day"].get(day)
    return bool(item["sessions_by_day"].get(day)) or bool(prs and any(prs.values()))


def _upcoming_deadlines(summaries: dict[str, dict[str, Any]], portfolio: dict[str, dict[str, Any]],
                        series_days: list[str], today: str) -> list[dict[str, Any]]:
    """Dated deadlines Claude found in the window's summaries that have not passed yet."""
    deadlines: dict[tuple, dict[str, Any]] = {}
    for product_id, item in portfolio.items():
        for day in series_days:
            for deadline in (_details(summaries.get(day), product_id) or {}).get("deadlines", []):
                if deadline["date"] >= today:
                    deadlines[(product_id, deadline["date"], deadline["what"])] = {**deadline, "project_id": product_id,
                                                                                   "project": item["name"]}
    return sorted(deadlines.values(), key=lambda d: (d["date"], d["project"]))[:8]


def _feed(series: list[dict[str, Any]], portfolio: dict[str, dict[str, Any]],
          summaries: dict[str, dict[str, Any]], today: str) -> list[dict[str, Any]]:
    """«По дням», the first screen: each day with work, newest first, in Claude's plain words per project.

    Only real activity: a day without sessions or PRs, or with quick looks only, is left out. Projects
    Claude has not retold yet are only named; quick looks and projects with nothing concrete are
    ``quiet`` and appear only in the technical details, with the PRs and numbers.
    """
    feed = []
    for totals in reversed(series[-FEED_DAYS:]):
        day = totals["date"]
        summary = summaries.get(day)
        projects = []
        for product_id, item in portfolio.items():
            # A summary left over after its sessions were re-attributed is not news on its own.
            if not _has_activity(item, day):
                continue
            bullets = _bullets(summary, product_id) or []
            records = item["sessions_by_day"].get(day, [])
            prs = item["prs_by_day"].get(day) or {"merged": [], "opened": [], "closed_unmerged": []}
            minutes = _union_minutes(p for r in records for p in _session_intervals(r))
            # Not news: a quick look without a PR, or a project Claude found nothing concrete to say about.
            quiet = not bullets and (_quick_look(records, prs) or product_id in ((summary or {}).get("quiet") or []))
            projects.append({
                "id": product_id, "name": item["name"], "mascot": item["mascot"],
                "minutes": minutes,
                "sessions": len(records),
                "bullets": bullets,
                "quiet": quiet,
                "merged": [_pr_view(pr) for pr in prs["merged"]],
                "opened": [_pr_view(pr) for pr in prs["opened"] if pr not in prs["merged"]],
                "closed": [_pr_view(pr) for pr in prs["closed_unmerged"]],
                "commands": sum(1 for r in records for action in r.get("infra_actions") or [] if isinstance(action, dict)),
            })
        # A day of quick looks only is not news either; the project pages still list it.
        if all(project["quiet"] for project in projects):
            continue
        projects.sort(key=lambda p: (p["minutes"], len(p["merged"]), p["sessions"]), reverse=True)
        headline = (summary or {}).get("day")
        feed.append({
            "date": day, "is_today": day == today,
            "headline": headline.strip() if isinstance(headline, str) and headline.strip() else None,
            "written_at": (summary or {}).get("generated_at"),
            "in_progress": bool((summary or {}).get("in_progress")),
            **{key: totals[key] for key in ("total_minutes", "claude_minutes", "codex_minutes", "sessions",
                                            "prs_merged", "prs_opened", "prs_closed_unmerged")},
            "projects": projects,
        })
    return feed


def _todo(portfolio: dict[str, dict[str, Any]], summaries: dict[str, dict[str, Any]],
          series_days: list[str], today: str) -> list[dict[str, Any]]:
    """MAIN MANAGER «Дела»: per project, what waits on Mark now. No day history, that is «По дням».

    Next steps come from the newest recent summary, deadlines from the summaries, PRs waiting for
    a merge (not drafts) from GitHub; loose ends are only counted here, «Хвосты» lists them.
    """
    deadlines = _upcoming_deadlines(summaries, portfolio, series_days, today)
    items = []
    for product_id, item in portfolio.items():
        since, steps = _current_next(summaries, product_id, series_days)
        # Drafts are still being worked on; only PRs marked ready wait for a merge.
        ready = [pr for pr in item["open_prs"] if not pr.get("draft")]
        entry = {
            "id": product_id, "name": item["name"], "mascot": item["mascot"],
            "next": steps, "next_from": since,
            "deadlines": [{"date": d["date"], "what": d["what"]} for d in deadlines if d["project_id"] == product_id],
            "open_prs": [_pr_view(pr) for pr in ready[:TODO_LIMIT]],
            "open_prs_count": len(ready),
            "drafts": len(item["open_prs"]) - len(ready),
            "loose": len(item["loose"]),
        }
        if entry["next"] or entry["deadlines"] or entry["open_prs"]:
            items.append(entry)
    # Nearest deadline first, then the projects with the most waiting.
    items.sort(key=lambda e: (e["deadlines"][0]["date"] if e["deadlines"] else "9999-12-31",
                              -(len(e["next"]) + e["open_prs_count"]), e["name"]))
    return items


def _age_days(moment: datetime | None, now: datetime) -> int | None:
    return None if moment is None else max(0, (now - moment).days)


def work_projection(root: Path, *, now: datetime | None = None, days: int = DEFAULT_DAYS,
                    selected: str | None = None, owner: bool = False, project: str | None = None,
                    edition: bool = False) -> dict[str, Any]:
    """MAIN MANAGER payload. ``edition`` asks for «По дням», the first screen: the last days with
    work in plain words; without a chosen day ``day`` is the newest day with work."""
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
    if edition and not selected:
        selected_day = next((day["date"] for day in reversed(series)
                             if day["sessions"] or day["prs_merged"] or day["prs_opened"] or day["prs_closed_unmerged"]),
                            today.isoformat())
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
    day_summaries = load_summaries(root, series_days) if owner else {}
    summaries = sorted((_portfolio_summary(item, series_days, day_summaries) for item in portfolio.values()),
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
        day_view["summary"] = _day_summary(day_summaries.get(selected_day), portfolio, selected_day)
        payload["summaries_status"] = _read_json(root / "summaries" / "status.json")
        payload["dropped"] = dropped[:LIST_LIMIT]
        payload["forgot"] = forgot[:LIST_LIMIT]
        payload["sources"] = sources
        payload["projects"] = summaries
        payload["todo"] = _todo(portfolio, day_summaries, series_days, today.isoformat())
        if edition:
            payload["feed"] = _feed(series, portfolio, day_summaries, today.isoformat())
            payload["deadlines"] = _upcoming_deadlines(day_summaries, portfolio, series_days, today.isoformat())
        if project:
            payload["project"] = _project_detail(portfolio[project], series_days, day_summaries) if project in portfolio else None
    else:
        payload["sources"] = {
            "machines": [{"machine": f"machine-{i + 1}", "collected_at": m["collected_at"]} for i, m in enumerate(sources["machines"])],
            "github": {"ok": sources["github"]["ok"], "collected_at": sources["github"]["collected_at"]},
        }
    return payload
