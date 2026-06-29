"""Pulse — Time Tracker based on git commit history."""
from __future__ import annotations

import subprocess
from datetime import datetime, timedelta, date
from pathlib import Path
from collections import defaultdict


def _run(cmd: str) -> str:
    try:
        return subprocess.check_output(cmd, shell=True, stderr=subprocess.DEVNULL, timeout=10).decode().strip()
    except Exception:
        return ""


def _get_git_hours(repo_path: Path, target_date: date) -> float:
    """Estimate hours worked based on git commits for a given date."""
    date_str = target_date.strftime("%Y-%m-%d")
    next_date = (target_date + timedelta(days=1)).strftime("%Y-%m-%d")
    cmd = f'git -C "{repo_path}" log --format="%aI" --after="{date_str}" --before="{next_date}" 2>/dev/null'
    output = _run(cmd)
    if not output:
        return 0.0

    times = []
    for line in output.splitlines():
        try:
            dt = datetime.fromisoformat(line.strip())
            times.append(dt)
        except Exception:
            continue

    if not times:
        return 0.0

    times.sort()
    if len(times) == 1:
        return 0.3  # Single commit = ~20min session

    # Estimate: sum gaps between commits (max 2h gap = new session)
    total_hours = 0.0
    for i in range(1, len(times)):
        gap = (times[i] - times[i - 1]).total_seconds() / 3600
        if gap <= 2.0:
            total_hours += gap
        else:
            total_hours += 0.3  # New session start
    total_hours += 0.3  # Initial session
    return round(total_hours, 1)


def _get_today_projects(repos: list[Path]) -> list[str]:
    """Get projects with commits today."""
    today = date.today().strftime("%Y-%m-%d")
    projects = []
    for repo in repos:
        cmd = f'git -C "{repo}" log --format="%H" --after="{today}" --before="{(date.today() + timedelta(days=1)).strftime("%Y-%m-%d")}" 2>/dev/null'
        if _run(cmd):
            projects.append(repo.name)
    return projects


def collect_pulse_data() -> dict:
    """Collect time tracking data from git repos."""
    home = Path.home()

    # Scan for git repos in home dir
    repos = []
    for d in sorted(home.iterdir()):
        if d.is_dir() and (d / ".git").exists() and not d.name.startswith("."):
            repos.append(d)

    # Also check ObsidianVault and scripts
    for extra in ["ObsidianVault", "scripts"]:
        p = home / extra
        if p.exists() and (p / ".git").exists() and p not in repos:
            repos.append(p)

    # Last 7 days
    today = date.today()
    daily_hours = []
    for i in range(6, -1, -1):
        d = today - timedelta(days=i)
        total = 0.0
        for repo in repos:
            total += _get_git_hours(repo, d)
        total = min(total, 12.0)  # Cap at 12h
        daily_hours.append({
            "date": d,
            "day_label": d.strftime("%a")[:2],
            "hours": round(total, 1),
            "is_today": d == today,
        })

    today_projects = _get_today_projects(repos)
    week_total = sum(d["hours"] for d in daily_hours)
    today_hours = daily_hours[-1]["hours"] if daily_hours else 0
    avg_daily = round(week_total / 7, 1) if daily_hours else 0

    return {
        "daily": daily_hours,
        "today_hours": today_hours,
        "week_total": round(week_total, 1),
        "avg_daily": avg_daily,
        "today_projects": today_projects,
    }


def build_pulse_html(data: dict) -> str:
    """Build Pulse time tracker HTML."""
    daily = data["daily"]
    max_hours = max((d["hours"] for d in daily), default=1) or 1

    bars_html = ""
    for d in daily:
        pct = round(d["hours"] / max_hours * 100)
        active_cls = " active" if d["is_today"] else ""
        bars_html += f"""
        <div class="pulse-bar-col">
            <div class="pulse-bar-value">{d["hours"]}</div>
            <div class="pulse-bar"><div class="pulse-bar-fill{active_cls}" style="height:{max(pct, 3)}%"></div></div>
            <div class="pulse-bar-label">{d["day_label"]}</div>
        </div>"""

    projects_html = ""
    if data["today_projects"]:
        badges = "".join(f'<span class="pulse-proj">{p}</span>' for p in data["today_projects"])
        projects_html = f"""
        <div class="pulse-section-label">Today's Projects</div>
        <div class="pulse-projects">{badges}</div>"""

    return f"""
    <div class="pulse-header">
        <div class="avatar" style="background:#1a2a3a"><span class="avatar-emoji">&#x23F1;</span></div>
        <div class="pulse-info">
            <div class="pulse-name">Pulse <span class="pulse-role">Time Tracker</span></div>
            <div class="pulse-status">{data["today_hours"]}h today &middot; {data["week_total"]}h this week &middot; avg {data["avg_daily"]}h/day</div>
        </div>
    </div>
    <div class="pulse-section-label">Last 7 Days</div>
    <div class="pulse-chart">{bars_html}</div>
    {projects_html}
    """
