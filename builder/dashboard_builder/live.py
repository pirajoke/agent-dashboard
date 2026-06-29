"""Live task tracking — feed, events, health, Mac Mini panel."""
from __future__ import annotations

import json
import time as _time
from datetime import datetime

from .config import LIVE_FEED_FILE, EVENTS_FILE, HEALTH_DIR


def load_live_feed() -> dict:
    if not LIVE_FEED_FILE.exists():
        return {"active_tasks": [], "services": [], "in_progress": [], "feed": [], "m4": {}}
    try:
        return json.loads(LIVE_FEED_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"active_tasks": [], "services": [], "in_progress": [], "feed": [], "m4": {}}


def load_recent_events(n: int = 15) -> list[dict]:
    if not EVENTS_FILE.exists():
        return []
    try:
        lines = EVENTS_FILE.read_text(encoding="utf-8").strip().splitlines()
    except OSError:
        return []
    recent = lines[-n:] if len(lines) > n else lines
    events = []
    for line in reversed(recent):
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def load_health_files() -> list[dict]:
    if not HEALTH_DIR.exists():
        return []
    now = _time.time()
    results = []
    for f in sorted(HEALTH_DIR.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            ts = data.get("ts", 0)
            age_min = max(0, round((now - ts) / 60)) if ts else 9999
            data["_age_min"] = age_min
            data["_fresh"] = age_min < 15
            data["_name"] = f.stem
            results.append(data)
        except (json.JSONDecodeError, OSError):
            continue
    return results


def build_live_html(live_feed: dict, events: list[dict], health: list[dict]) -> str:
    services = live_feed.get("services", [])
    m4 = live_feed.get("m4") or {}

    def dot_cls_for_status(status: str, ok: bool | None = None) -> str:
        if ok is not None:
            return "live-health-ok" if ok else "live-health-err"
        norm = (status or "").lower()
        if norm in {"running", "ok", "healthy"} or norm.startswith("up"):
            return "live-health-ok"
        if norm in {"idle", "starting", "created"}:
            return "live-health-warn"
        return "live-health-err"

    # ── Active Tasks panel (deduplicated) ──
    seen_issues = set()
    merged_tasks = []
    for t in live_feed.get("active_tasks", []) + live_feed.get("in_progress", []):
        key = t.get("issue", t.get("id", t.get("key", "")))
        if key and key in seen_issues:
            continue
        seen_issues.add(key)
        merged_tasks.append(t)

    if merged_tasks:
        task_rows = ""
        for t in merged_tasks:
            issue = t.get("issue", t.get("id", t.get("key", "")))
            title = t.get("title", t.get("detail", t.get("msg", "")))[:40]
            agent = t.get("agent", "")
            status = t.get("status", t.get("state", "running"))
            st_cls = "live-st-done" if status.lower() == "done" else ("live-st-blocked" if "block" in status.lower() else "live-st-active")
            task_rows += f'<div class="live-task"><span class="live-pulse"></span><span class="live-issue">{issue}</span><span class="live-title">{title}</span><span class="live-agent">{agent}</span><span class="live-status {st_cls}">{status}</span></div>'
        tasks_html = task_rows
    else:
        tasks_html = '<div class="live-empty">No active tasks</div>'

    # ── Services panel ──
    PRIORITY_SERVICES = [
        "light-linear-worker", "claude-linear-responder", "claude-autonomous-executor", "codex-linear-executor",
        "jarvis", "linear-bot", "handy-voice-router", "dashboard-server", "generate-live-feed",
    ]
    running = [s for s in services if s.get("status") == "running"]
    total_svc = len(services)
    running_count = len(running)

    svc_map = {s.get("name"): s for s in services}
    health_map = {h.get("_name"): h for h in health}

    shown = set()
    ordered_names = []
    for name in PRIORITY_SERVICES:
        if name in svc_map:
            ordered_names.append(name)
            shown.add(name)
    for s in services:
        name = s.get("name", "")
        if name not in shown:
            ordered_names.append(name)
            shown.add(name)

    svc_rows = ""
    for name in ordered_names:
        svc = svc_map.get(name)
        h = health_map.get(name)

        if svc:
            status = svc.get("status", "unknown")
            pid = svc.get("pid")
            if status == "running":
                dot_cls = "live-health-ok"
                age_str = f"PID {pid}" if pid else "running"
            elif status == "idle":
                dot_cls = "live-health-warn"
                age_str = "idle"
            else:
                dot_cls = "live-health-err"
                age_str = status
        else:
            dot_cls = "live-health-err"
            age_str = "stopped"

        if h and h.get("_fresh"):
            dot_cls = "live-health-ok"
            age_str = f"{h['_age_min']}m ago"

        svc_rows += f'<div class="live-svc"><span class="live-dot-sm {dot_cls}"></span><span class="live-svc-name">{name}</span><span class="live-svc-age">{age_str}</span></div>'

    services_html = f'<div class="live-svc-summary">{running_count}/{total_svc} running</div>{svc_rows}'

    # ── Mac Mini M4 panel ──
    reachable = m4.get("reachable", False)
    launchd = m4.get("launchd", [])
    containers = m4.get("containers", [])
    public_endpoints = m4.get("public_endpoints", [])
    backup = m4.get("latest_backup") or {}
    alerts = m4.get("alerts", [])
    host = m4.get("host", "maxxs-mac-mini")
    reach_text = "reachable" if reachable else "unreachable"
    m4_meta = [
        ("Target", m4.get("target", "maxx@100.77.209.73")),
        ("LaunchAgents", f'{m4.get("launchd_running", 0)}/{m4.get("launchd_total", len(launchd))} running'),
        ("Containers", f'{m4.get("containers_running", 0)}/{m4.get("containers_total", len(containers))} up'),
        ("Public", f'{m4.get("public_healthy", 0)}/{m4.get("public_total", len(public_endpoints))} healthy'),
        ("Uptime", m4.get("uptime", "n/a") if reachable else (m4.get("error", "SSH unavailable")[:80])),
        ("Backup", backup.get("name", "n/a")),
        ("Backup age", f'{backup.get("age_hours")}h' if backup.get("age_hours") is not None else "n/a"),
    ]
    m4_meta_html = ''.join(
        f'<div class="live-m4-line"><span class="live-m4-key">{label}</span><span class="live-m4-val">{value}</span></div>'
        for label, value in m4_meta
    )

    def build_group(title: str, rows: list[str]) -> str:
        if not rows:
            return f'<div class="live-svc-group"><div class="live-svc-group-title">{title}</div><div class="live-empty">No data</div></div>'
        return f'<div class="live-svc-group"><div class="live-svc-group-title">{title}</div>{"".join(rows)}</div>'

    launchd_rows = [
        f'<div class="live-svc"><span class="live-dot-sm {dot_cls_for_status(item.get("status", ""))}"></span><span class="live-svc-name">{item.get("label", "")}</span><span class="live-svc-age">{item.get("pid") or item.get("status", "")}</span></div>'
        for item in launchd
    ]
    container_rows = [
        f'<div class="live-svc"><span class="live-dot-sm {dot_cls_for_status(item.get("status", ""))}"></span><span class="live-svc-name">{item.get("name", "")}</span><span class="live-svc-age">{item.get("status", "")}</span></div>'
        for item in containers
    ]
    public_rows = [
        f'<div class="live-svc"><span class="live-dot-sm {dot_cls_for_status(item.get("status", ""), item.get("ok"))}"></span><span class="live-svc-name">{item.get("name", "")}</span><span class="live-svc-age">{item.get("status") or item.get("error", "down")}</span></div>'
        for item in public_endpoints
    ]

    alert_badges = ''.join(
        f'<span class="live-alert live-alert-{item.get("severity", "warning")}">{item.get("label", "Alert")}</span>'
        for item in alerts
    )
    alert_details = ''.join(
        f'<div class="live-alert-detail"><span class="live-alert-detail-label">{item.get("label", "Alert")}</span><span class="live-alert-detail-text">{item.get("detail", "")}</span></div>'
        for item in alerts if item.get("detail")
    )

    m4_html = f'<div class="live-svc-summary">{host} · {reach_text}</div><div class="live-alerts">{alert_badges}</div><div class="live-m4-meta">{m4_meta_html}</div><div class="live-alert-details">{alert_details}</div>'
    m4_html += build_group("LaunchAgents", launchd_rows)
    m4_html += build_group("Containers", container_rows)
    m4_html += build_group("Public endpoints", public_rows)

    # ── Events panel ──
    evt_colors = {"task_complete": "#3fb950", "canary_rejected": "#d29922", "failed": "#f85149",
                  "task_failed": "#f85149", "start": "#58a6ff", "cycle_start": "#58a6ff"}
    evt_labels = {"task_complete": "done", "canary_rejected": "rejected", "failed": "failed",
                  "task_failed": "failed", "start": "start", "cycle_start": "start"}

    if events:
        evt_rows = ""
        today = datetime.utcnow().strftime("%Y-%m-%d")
        for e in events:
            ts = e.get("ts", e.get("iso", ""))
            evt_date = ""
            if "T" in ts:
                try:
                    t_obj = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ")
                    ts_short = t_obj.strftime("%H:%M")
                    evt_date = t_obj.strftime("%Y-%m-%d")
                except ValueError:
                    ts_short = ts[:5]
            else:
                ts_short = ts[11:16] if len(ts) > 16 else ts[:5]
                evt_date = ts[:10] if len(ts) >= 10 else ""
            date_prefix = f'{evt_date[5:]} ' if evt_date and evt_date != today else ""
            evt_type = e.get("event", "")
            label = evt_labels.get(evt_type, evt_type)
            color = evt_colors.get(evt_type, "#8b949e")
            issue = e.get("issue", "")
            agent = e.get("agent", "")
            project = e.get("project", "")
            dur = e.get("duration")
            dur_str = f"{int(dur)}s" if dur else ""
            reason = e.get("reason", "")[:40] if e.get("reason") else ""
            detail = f"{agent} {project}".strip() if agent or project else reason
            evt_rows += f'<div class="live-event"><span class="live-evt-time">{date_prefix}{ts_short}</span><span class="live-evt-dot" style="background:{color}"></span><span class="live-evt-label" style="color:{color}">{label}</span><span class="live-evt-issue">{issue}</span><span class="live-evt-detail">{detail}</span><span class="live-evt-dur">{dur_str}</span></div>'
        events_html = evt_rows
    else:
        events_html = '<div class="live-empty">No recent events</div>'

    local_services_html = """
        <div class="live-panel">
            <div class="live-panel-title">Local Services</div>
            <div class="live-svc-summary" id="local-services-summary">Loading local status…</div>
            <div id="local-services-list">
                <div class="live-empty">Querying launchd and local processes…</div>
            </div>
        </div>"""

    return f"""
    <div class="live-grid">
        <div class="live-panel">
            <div class="live-panel-title">Active Tasks</div>
            {tasks_html}
        </div>
        <div class="live-panel">
            <div class="live-panel-title">Services</div>
            {services_html}
        </div>
        <div class="live-panel">
            <div class="live-panel-title">Mac Mini M4</div>
            {m4_html}
        </div>
        {local_services_html}
    </div>
    <div class="live-panel-wide">
        <div class="live-panel-title">Recent Events</div>
        {events_html}
    </div>"""
