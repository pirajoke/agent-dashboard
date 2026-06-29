"""NOW section — status bar, alerts, pulse mini, quick glance."""
from __future__ import annotations

from .atlas import collect_atlas_data
from .jarvis_pipeline import collect_jarvis_pipeline_data, build_jarvis_pipeline_html
from .pulse import collect_pulse_data
from .real_agents import collect_real_agents


def collect_now_data() -> dict:
    """Collect all data for the NOW section."""
    atlas = collect_atlas_data()
    pulse = collect_pulse_data()
    agents = collect_real_agents()
    jarvis_pipeline = collect_jarvis_pipeline_data()

    # Status dots from Atlas health checks
    latest = atlas.get("latest")
    health_dots = []
    if latest:
        for h in latest.get("health", []):
            color = "ok" if h["status"] == "ok" else ("warn" if h["status"] == "warning" else "error")
            health_dots.append({"label": h["label"], "color": color, "detail": h["detail"]})

    # Alerts: any agent down or degraded
    alerts = []
    for a in agents:
        if a["health"] == "off":
            alerts.append({"level": "error", "text": f"{a['name']} is offline"})
        elif a["health"] == "degraded":
            alerts.append({"level": "warn", "text": f"{a['name']} is degraded"})

    # Alerts from Atlas blocked items
    if latest:
        for b in latest.get("blocked", []):
            alerts.append({"level": "error", "text": b})

    # Agent summary
    active_count = sum(1 for a in agents if a["health"] == "active")
    total_agents = len(agents)

    return {
        "health_dots": health_dots,
        "alerts": alerts,
        "pulse": pulse,
        "active_agents": active_count,
        "total_agents": total_agents,
        "atlas_passed": atlas.get("passed", 0),
        "atlas_total": atlas.get("total_checks", 0),
        "last_report_date": latest["date"] if latest else "never",
        "jarvis_pipeline": jarvis_pipeline,
    }


def build_now_html(data: dict) -> str:
    """Build the NOW section HTML."""
    # Status bar dots
    dots_html = ""
    for d in data["health_dots"]:
        dot_cls = {"ok": "dot-green", "warn": "dot-yellow", "error": "dot-red"}.get(d["color"], "dot-dim")
        dots_html += f'<div class="now-dot-item"><span class="status-dot {dot_cls}"></span><span class="now-dot-label">{d["label"]}</span></div>'

    status_bar = f"""
    <div class="now-status-bar">
        <div class="now-dots">{dots_html}</div>
        <div class="now-check-time">checked: {data["last_report_date"]}</div>
    </div>"""

    # Alerts
    alerts_html = ""
    if data["alerts"]:
        items = ""
        for a in data["alerts"]:
            cls = "now-alert-error" if a["level"] == "error" else "now-alert-warn"
            dot = "dot-red" if a["level"] == "error" else "dot-yellow"
            items += f'<div class="now-alert {cls}"><span class="status-dot {dot}"></span> {a["text"]}</div>'
        alerts_html = f'<div class="now-alerts">{items}</div>'

    # Quick stats
    pulse = data["pulse"]
    stats_html = f"""
    <div class="now-stats">
        <div class="now-stat">
            <span class="now-stat-val">{data["active_agents"]}/{data["total_agents"]}</span>
            <span class="now-stat-lbl">agents</span>
        </div>
        <div class="now-stat">
            <span class="now-stat-val">{data["atlas_passed"]}/{data["atlas_total"]}</span>
            <span class="now-stat-lbl">checks</span>
        </div>
        <div class="now-stat">
            <span class="now-stat-val">{pulse["today_hours"]}h</span>
            <span class="now-stat-lbl">today</span>
        </div>
        <div class="now-stat">
            <span class="now-stat-val">{pulse["week_total"]}h</span>
            <span class="now-stat-lbl">week</span>
        </div>
        <div class="now-stat">
            <span class="now-stat-val">{pulse["avg_daily"]}h</span>
            <span class="now-stat-lbl">avg/day</span>
        </div>
    </div>"""

    # Pulse mini bar chart
    daily = pulse.get("daily", [])
    max_hours = max((d["hours"] for d in daily), default=1) or 1
    bars = ""
    for d in daily:
        pct = round(d["hours"] / max_hours * 100)
        active = " active" if d["is_today"] else ""
        bars += f"""<div class="now-bar-col">
            <div class="now-bar-val">{d["hours"]}</div>
            <div class="now-bar"><div class="now-bar-fill{active}" style="height:{max(pct, 3)}%"></div></div>
            <div class="now-bar-day">{d["day_label"]}</div>
        </div>"""

    projects_html = ""
    if pulse.get("today_projects"):
        badges = "".join(f'<span class="now-proj">{p}</span>' for p in pulse["today_projects"])
        projects_html = f'<div class="now-projects">{badges}</div>'

    pulse_html = f"""
    <div class="now-pulse">
        <div class="now-pulse-chart">{bars}</div>
        {projects_html}
    </div>"""

    jarvis_pipeline_html = build_jarvis_pipeline_html(data["jarvis_pipeline"])

    return f"{status_bar}{alerts_html}{jarvis_pipeline_html}{stats_html}{pulse_html}"
