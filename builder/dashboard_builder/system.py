"""SYSTEM section — agents, Atlas health, M4 status, services."""
from __future__ import annotations

from .real_agents import collect_real_agents
from .atlas import collect_atlas_data
from .live import load_live_feed, load_recent_events, load_health_files
from .fraction import collect_fraction_data


def collect_system_data() -> dict:
    """Collect all data for the SYSTEM section."""
    agents = collect_real_agents()
    atlas = collect_atlas_data()
    live_feed = load_live_feed()
    live_events = load_recent_events(10)
    fraction = collect_fraction_data()

    return {
        "agents": agents,
        "atlas": atlas,
        "live_feed": live_feed,
        "live_events": live_events,
        "fraction": fraction,
    }


def _build_topology_svg(agents: list[dict]) -> str:
    """Build SVG topology map showing agent connections with health-colored lines."""
    # Agent positions in the topology (x, y)
    # Layout: CLAUDE at top center, CODEX/JARVIS/ATLAS below, DASHBOARD under ATLAS
    health_map = {a["id"]: a["health"] for a in agents}
    color_map = {a["id"]: a["color"] for a in agents}

    nodes = [
        ("CLAUDE",    300, 40),
        ("CODEX",     100, 140),
        ("JARVIS",    300, 140),
        ("ATLAS",     500, 140),
        ("DASHBOARD", 500, 240),
    ]
    # MCP Servers node (virtual, always linked to CLAUDE)
    mcp_node = ("MCP", 520, 40)

    # Connections: (from_id, to_id)
    edges = [
        ("CLAUDE", "MCP"),
        ("CLAUDE", "CODEX"),
        ("CLAUDE", "JARVIS"),
        ("CLAUDE", "ATLAS"),
        ("ATLAS",  "DASHBOARD"),
    ]

    def _line_color(a_id: str, b_id: str) -> str:
        ha = health_map.get(a_id, "off")
        hb = health_map.get(b_id, "off") if b_id != "MCP" else health_map.get("CLAUDE", "off")
        if ha == "active" and hb == "active":
            return "rgba(34,197,94,0.6)"
        if ha == "off" and hb == "off":
            return "rgba(82,82,91,0.25)"
        return "rgba(234,179,8,0.4)"

    lines_svg = ""
    for a_id, b_id in edges:
        ax, ay = next((x, y) for n, x, y in nodes if n == a_id) if a_id != "MCP" else (mcp_node[1], mcp_node[2])
        bx, by = next((x, y) for n, x, y in nodes if n == b_id) if b_id != "MCP" else (mcp_node[1], mcp_node[2])
        color = _line_color(a_id, b_id)
        lines_svg += f'<line x1="{ax}" y1="{ay}" x2="{bx}" y2="{by}" stroke="{color}" stroke-width="2" stroke-linecap="round"/>'

    nodes_svg = ""
    all_nodes = nodes + [mcp_node]
    for nid, nx, ny in all_nodes:
        fill = color_map.get(nid, "#71717a")
        health = health_map.get(nid, "off") if nid != "MCP" else health_map.get("CLAUDE", "off")
        opacity = "1" if health != "off" else "0.35"
        r = 14 if nid != "MCP" else 10
        nodes_svg += f'<circle cx="{nx}" cy="{ny}" r="{r}" fill="{fill}" opacity="{opacity}"/>'
        # Label
        label = nid if nid != "MCP" else "MCP"
        font_size = "9" if nid != "MCP" else "7.5"
        nodes_svg += f'<text x="{nx}" y="{ny + r + 14}" text-anchor="middle" fill="rgba(228,228,231,0.7)" font-size="{font_size}" font-family="JetBrains Mono, monospace" font-weight="600">{label}</text>'
        # Pulse ring for active
        if health == "active":
            nodes_svg += f'<circle cx="{nx}" cy="{ny}" r="{r}" fill="none" stroke="{fill}" stroke-width="1.5" opacity="0.3"><animate attributeName="r" from="{r}" to="{r + 10}" dur="2s" repeatCount="indefinite"/><animate attributeName="opacity" from="0.4" to="0" dur="2s" repeatCount="indefinite"/></circle>'

    return f"""
    <div class="topo-map">
        <svg viewBox="0 0 620 290" xmlns="http://www.w3.org/2000/svg" class="topo-svg">
            {lines_svg}
            {nodes_svg}
        </svg>
    </div>"""


def build_system_html(data: dict) -> str:
    """Build the SYSTEM section HTML."""
    agents = data["agents"]
    atlas = data["atlas"]
    live_feed = data["live_feed"]
    live_events = data["live_events"]
    fraction = data["fraction"]

    # ── Topology map ──
    topology_html = _build_topology_svg(agents)

    # ── Agent cards with Atlas health embedded in Atlas card ──
    latest = atlas.get("latest")
    atlas_tiles = ""
    atlas_reports = ""

    if latest:
        for h in latest["health"]:
            color_cls = "green" if h["status"] == "ok" else ("yellow" if h["status"] == "warning" else "red")
            dot_cls = f"dot-{color_cls}"
            atlas_tiles += f"""
            <div class="sys-health-tile {color_cls}">
                <span class="status-dot {dot_cls}"></span>
                <span class="sys-tile-name">{h["label"]}</span>
                <span class="sys-tile-detail">{h["detail"]}</span>
            </div>"""

        for r in atlas.get("reports", [])[:5]:
            verdict_cls = r["verdict"]
            dot_cls = f"dot-{verdict_cls}"
            passed = sum(1 for h in r.get("health", []) if h["status"] == "ok")
            total = len(r.get("health", []))
            tldr = r["tldr"][:80] + "..." if len(r["tldr"]) > 80 else r["tldr"]
            atlas_reports += f"""
            <div class="sys-report">
                <span class="sys-rpt-date">{r["date"]}</span>
                <span class="status-dot {dot_cls}"></span>
                <span class="sys-rpt-score">{passed}/{total}</span>
                <span class="sys-rpt-tldr">{tldr}</span>
            </div>"""

    # ── Build redesigned agent cards ──
    cards = ""
    for a in agents:
        health = a["health"]
        color = a["color"]
        dot_map = {"active": "ag-dot-active", "degraded": "ag-dot-blocked", "off": "ag-dot-idle"}
        dot_cls = f"ag-dot {dot_map.get(health, 'ag-dot-idle')}"

        # Health badge for off/degraded
        health_badge = ""
        if health == "off":
            health_badge = '<span class="ag-badge-offline">OFFLINE</span>'
        elif health == "degraded":
            health_badge = '<span class="ag-badge-degraded">DEGRADED</span>'

        # Stat pills
        pills_html = ""
        for stat in a["stats"]:
            pills_html += f'<span class="ag-pill">{stat}</span>'

        # Sub-items (collapsible)
        sub_html = ""
        sub_items = a.get("sub_items", [])
        if sub_items:
            sub_rows = ""
            for item in sub_items:
                s = item["status"]
                sub_dot = "dot-green" if s == "running" else ("dot-red" if s in ("error", "off") else "dot-dim")
                sub_rows += f"""
                <div class="ag-sub-item">
                    <span class="status-dot {sub_dot}"></span>
                    <span class="ag-sub-name">{item["name"]}</span>
                    <span class="ag-sub-detail">{item["detail"]}</span>
                </div>"""
            sub_html = f"""
            <details class="ag-sub-expand">
                <summary class="ag-sub-toggle">Running processes ({len(sub_items)})</summary>
                <div class="ag-sub-items">{sub_rows}</div>
            </details>"""

        # Extra content for Atlas card
        extra = ""
        if a["id"] == "ATLAS" and atlas_tiles:
            extra = f"""
            <details class="sys-atlas-expand">
                <summary class="sys-expand-sum">Health Checks ({atlas['passed']}/{atlas['total_checks']})</summary>
                <div class="sys-health-grid">{atlas_tiles}</div>
            </details>
            <details class="sys-atlas-expand">
                <summary class="sys-expand-sum">Daily Reports ({len(atlas.get('reports', []))})</summary>
                <div class="sys-reports-list">{atlas_reports}</div>
            </details>"""

        cards += f"""
        <div class="ag ag-{health}">
            {health_badge}
            <div class="ag-top">
                <div class="ag-orb ag-orb-{health}" style="background:{color}">
                    <div class="ag-orb-ring" style="border-color:{color}"></div>
                    {a["icon"]}
                </div>
                <div class="ag-info">
                    <div class="ag-name">{a["name"]}</div>
                    <div class="ag-zone-inline">{a["zone"]}</div>
                </div>
                <div class="ag-status"><div class="{dot_cls}"></div></div>
            </div>
            <div class="ag-pills">{pills_html}</div>
            {sub_html}
            {extra}
        </div>"""

    # ── Mac Mini M4 status ──
    m4 = live_feed.get("m4") or {}
    m4_html = ""
    if m4:
        reachable = m4.get("reachable", False)
        host = m4.get("host", "maxxs-mac-mini")
        uptime = m4.get("uptime", "n/a") if reachable else "unreachable"
        launchd_running = m4.get("launchd_running", 0)
        launchd_total = m4.get("launchd_total", 0)
        containers_running = m4.get("containers_running", 0)
        containers_total = m4.get("containers_total", 0)

        reach_dot = "dot-green" if reachable else "dot-red"
        m4_html = f"""
        <div class="sys-m4">
            <div class="sys-m4-header">
                <span class="status-dot {reach_dot}"></span>
                <span class="sys-m4-host">{host}</span>
                <span class="sys-m4-uptime">{uptime}</span>
            </div>
            <div class="sys-m4-stats">
                <span>LaunchAgents: {launchd_running}/{launchd_total}</span>
                <span>Containers: {containers_running}/{containers_total}</span>
            </div>
        </div>"""

    # ── Services (running from fraction launchd, hide idle behind toggle) ──
    launchd = fraction.get("launchd", [])
    running_svcs = [s for s in launchd if s["status"] == "running"]
    idle_svcs = [s for s in launchd if s["status"] != "running"]

    svc_rows = ""
    for s in running_svcs:
        dot = "dot-green" if s["status"] == "running" else "dot-red"
        svc_rows += f'<div class="sys-svc"><span class="status-dot {dot}"></span><span class="sys-svc-name">{s["name"]}</span></div>'

    idle_rows = ""
    for s in idle_svcs:
        dot = "dot-red" if s["status"] == "error" else "dot-dim"
        idle_rows += f'<div class="sys-svc"><span class="status-dot {dot}"></span><span class="sys-svc-name">{s["name"]}</span><span class="sys-svc-status">{s["status"]}</span></div>'

    services_html = f"""
    <div class="sys-services">
        <div class="sys-svc-running">{svc_rows}</div>
    </div>"""

    if idle_svcs:
        services_html += f"""
        <details class="sys-idle-toggle">
            <summary class="sys-expand-sum">Idle/Stopped ({len(idle_svcs)})</summary>
            <div class="sys-svc-idle">{idle_rows}</div>
        </details>"""

    # ── Recent events ──
    events_html = ""
    if live_events:
        for e in live_events[:8]:
            ts = e.get("ts", e.get("iso", ""))
            ts_short = ts[11:16] if len(ts) > 16 else ts[:5]
            evt_type = e.get("event", "")
            issue = e.get("issue", "")
            agent = e.get("agent", "")
            color_map = {"task_complete": "var(--green)", "failed": "var(--red)", "task_failed": "var(--red)", "start": "var(--accent)"}
            color = color_map.get(evt_type, "var(--dim)")
            events_html += f'<div class="sys-event"><span class="sys-evt-time">{ts_short}</span><span class="sys-evt-dot" style="background:{color}"></span><span class="sys-evt-type">{evt_type}</span><span class="sys-evt-issue">{issue}</span><span class="sys-evt-agent">{agent}</span></div>'

    return f"""
    {m4_html}
    {topology_html}
    <div class="agents">{cards}</div>
    <details class="sys-section" open>
        <summary class="sys-section-sum">Services ({len(running_svcs)} running)</summary>
        {services_html}
    </details>
    <details class="sys-section">
        <summary class="sys-section-sum">Recent Events ({len(live_events)})</summary>
        <div class="sys-events">{events_html}</div>
    </details>"""
