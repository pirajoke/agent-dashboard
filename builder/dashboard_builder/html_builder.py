"""Main HTML dashboard assembly — 4-section structure: NOW, Projects, System, Costs."""
from __future__ import annotations

from .config import ASSETS_DIR
from .projects import is_project_active
from .now import collect_now_data, build_now_html
from .system import collect_system_data, build_system_html
from .costs import collect_costs_data, build_costs_html
from .command_center import build_command_center_html
from .agent_theater import build_agent_theater_html
from .agent_workshop import build_agent_workshop_html


def _build_project_row(p: dict, completed: bool = False) -> str:
    if completed:
        status_class = "done"
    else:
        s = p["status"].lower()
        if s == "active":
            status_class = "active"
        elif s in ("idea", "planned"):
            status_class = "idea"
        else:
            status_class = "other"
    agents_str = ", ".join(p["agents"]) if p["agents"] else "—"
    na = p["next_action"]
    if len(na) > 80:
        na = na[:77] + "..."
    progress = 0
    total = p["open_todos"] + p["closed_todos"]
    if total > 0:
        progress = round(p["closed_todos"] / total * 100)
    if progress >= 75:
        pfill_class = "pfill pfill-high"
    elif progress >= 40:
        pfill_class = "pfill pfill-mid"
    else:
        pfill_class = "pfill pfill-low"
    fresh = p.get("freshness_days", 999)
    fresh_label = f"{fresh}d" if fresh < 999 else "—"
    fresh_class = "fresh-hot" if fresh <= 3 else ("fresh-warm" if fresh <= 14 else "fresh-cold")
    actions = ""
    if not completed:
        actions = f"""<td class="actions-col">
                <button class="qa-btn" onclick="window.open('obsidian://open?vault=ObsidianVault&file=20-Projects/{p["name"]}/Tech-Base/TODO.md')" title="Open TODO">📋</button>
            </td>"""
    else:
        actions = '<td class="actions-col"></td>'

    return f"""
        <tr>
            <td class="proj-name">{p["name"]}</td>
            <td><span class="status-pill status-{status_class}">{p["status"]}</span></td>
            <td style="font-family:'JetBrains Mono',monospace;font-size:0.75rem">{p["open_todos"] if not completed else p["closed_todos"]}</td>
            <td>
                <div class="pbar"><div class="{pfill_class}" style="width:{progress}%"></div></div>
                <span class="ptxt">{progress}%</span>
            </td>
            <td class="{fresh_class}">{fresh_label}</td>
            <td class="next-action">{na}</td>
            <td class="agents-col">{agents_str}</td>
            {actions}
    </tr>"""


def _build_builder_dialogue_html() -> str:
    return """
<div class="section" id="builder">
    <div class="section-head">
        <div class="section-dot" style="background:var(--blue)"></div>
        <div class="section-title">Builder Dialogue</div>
        <div class="section-count" id="builder-status">loading</div>
    </div>
    <div class="builder-panel">
        <div class="builder-feed" id="builder-feed">
            <div class="builder-empty">Loading Builder queue...</div>
        </div>
        <form class="builder-form" id="builder-form">
            <input class="builder-input" name="description" autocomplete="off" placeholder="Send a task to Builder...">
            <button class="builder-send" type="submit">Send</button>
        </form>
    </div>
</div>"""


def build_html(projects: list[dict], timestamp: str) -> str:
    # Collect data for all 4 sections
    now_data = collect_now_data()
    system_data = collect_system_data()
    costs_data = collect_costs_data()

    # Build section HTML
    now_html = build_now_html(now_data)
    system_html = build_system_html(system_data)
    costs_html = build_costs_html(costs_data)
    command_html = build_command_center_html()
    theater_html = build_agent_theater_html()
    workshop_html = build_agent_workshop_html()

    # Projects
    active_projs = [p for p in projects if is_project_active(p)]
    completed_projs = [p for p in projects if not is_project_active(p)]
    project_rows = "".join(_build_project_row(p) for p in active_projs)
    completed_rows = "".join(_build_project_row(p, completed=True) for p in completed_projs)

    css_text = (ASSETS_DIR / "style.css").read_text()
    js_text = (ASSETS_DIR / "script.js").read_text()

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Command Center</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">
<style>
{css_text}
</style>
</head>
<body>
<div class="bg-noise"></div>
<div class="bg-gradient"></div>

<div class="shell">

<!-- Sidebar -->
<nav class="sidebar">
    <div class="sidebar-brand">
        <h1>Command Center</h1>
        <div class="sb-sub">agent orchestration</div>
    </div>
    <ul class="sidebar-nav">
        <li><a data-target="#theater" href="javascript:void(0)" class="active">
            <svg class="nav-icon" viewBox="0 0 16 16"><path d="M3 12c2-4 8-4 10 0" stroke="currentColor" fill="none" stroke-width="1.2" stroke-linecap="round"/><circle cx="5" cy="6" r="2" stroke="currentColor" fill="none" stroke-width="1.2"/><circle cx="11" cy="6" r="2" stroke="currentColor" fill="none" stroke-width="1.2"/><path d="M8 8v5" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/></svg>
            Theater
        </a></li>
        <li><a data-target="#command-center" href="javascript:void(0)">
            <svg class="nav-icon" viewBox="0 0 16 16"><rect x="2" y="3" width="12" height="9" rx="2" stroke="currentColor" fill="none" stroke-width="1.2"/><path d="M5 12v2M11 12v2M5 7h6M5 10h3" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/></svg>
            Command
        </a></li>
        <li><a data-target="#now" href="javascript:void(0)">
            <svg class="nav-icon" viewBox="0 0 16 16"><circle cx="8" cy="8" r="6" stroke="currentColor" fill="none" stroke-width="1.3"/><line x1="8" y1="4" x2="8" y2="8" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/><line x1="8" y1="8" x2="11" y2="10" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/></svg>
            NOW
        </a></li>
        <li><a data-target="#projects" href="javascript:void(0)">
            <svg class="nav-icon" viewBox="0 0 16 16"><path d="M2 4l5-2 5 2v8l-5 2-5-2V4z" stroke="currentColor" fill="none" stroke-width="1.2"/><line x1="7" y1="2" x2="7" y2="14" stroke="currentColor" stroke-width="1.2"/></svg>
            Projects <span class="nav-count">{len(active_projs)}</span>
        </a></li>
        <li><a data-target="#system" href="javascript:void(0)">
            <svg class="nav-icon" viewBox="0 0 16 16"><rect x="2" y="2" width="12" height="12" rx="2" stroke="currentColor" fill="none" stroke-width="1.2"/><circle cx="8" cy="8" r="2" stroke="currentColor" fill="none" stroke-width="1.2"/><line x1="8" y1="2" x2="8" y2="6" stroke="currentColor" stroke-width="1"/><line x1="8" y1="10" x2="8" y2="14" stroke="currentColor" stroke-width="1"/><line x1="2" y1="8" x2="6" y2="8" stroke="currentColor" stroke-width="1"/><line x1="10" y1="8" x2="14" y2="8" stroke="currentColor" stroke-width="1"/></svg>
            System <span class="nav-count">{now_data['active_agents']}/{now_data['total_agents']}</span>
        </a></li>
        <li><a data-target="#builder" href="javascript:void(0)">
            <svg class="nav-icon" viewBox="0 0 16 16"><path d="M4 11l-1 3 3-1 7-7-2-2-7 7z" stroke="currentColor" fill="none" stroke-width="1.2"/><path d="M10 3l3 3" stroke="currentColor" stroke-width="1.2"/></svg>
            Builder
        </a></li>
        <li><a data-target="#workshop" href="javascript:void(0)">
            <svg class="nav-icon" viewBox="0 0 16 16"><rect x="2" y="3" width="12" height="10" rx="2" stroke="currentColor" fill="none" stroke-width="1.2"/><path d="M5 10h2M9 10h2M5 7h6" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/></svg>
            Workshop
        </a></li>
        <li><a data-target="#costs" href="javascript:void(0)">
            <svg class="nav-icon" viewBox="0 0 16 16"><rect x="2" y="4" width="12" height="9" rx="1.5" stroke="currentColor" fill="none" stroke-width="1.2"/><line x1="2" y1="7" x2="14" y2="7" stroke="currentColor" stroke-width="1.2"/></svg>
            Costs <span class="nav-count">${costs_data['total_monthly']:,.0f}/mo</span>
        </a></li>
    </ul>
    <div class="sidebar-footer">
        <div class="sf-live">
            <span class="live-dot"></span>
            <span>{timestamp}</span>
        </div>
    </div>
</nav>

<!-- Main content -->
<main class="main">

<!-- Theater Section -->
<div class="topbar" id="theater-top">
    <div class="topbar-title">Agent Theater</div>
    <div class="topbar-meta">
        <span class="tm-item"><span class="live-dot"></span> Live</span>
        <span class="tm-item">{timestamp}</span>
    </div>
</div>

{theater_html}

<!-- Command Center Section -->
<div class="topbar topbar-secondary" id="command-top">
    <div class="topbar-title">Systems Command Center</div>
    <div class="topbar-meta">
        <span class="tm-item"><span class="live-dot"></span> Live</span>
        <span class="tm-item">{timestamp}</span>
    </div>
</div>

{command_html}

<!-- NOW Section -->
<div class="topbar topbar-secondary" id="now">
    <div class="topbar-title">NOW</div>
    <div class="topbar-meta">
        <span class="tm-item"><span class="live-dot"></span> Live</span>
        <span class="tm-item">{timestamp}</span>
    </div>
</div>

{now_html}

{_build_builder_dialogue_html()}

{workshop_html}

<!-- Projects Section -->
<div class="section" id="projects">
    <div class="section-head">
        <div class="section-dot" style="background:var(--green)"></div>
        <div class="section-title">Projects</div>
        <div class="section-count">{len(active_projs)} active</div>
    </div>
    <details class="proj-details" open>
        <summary class="proj-summary">
            <span class="section-title">Active</span>
            <span class="section-count">{len(active_projs)}</span>
            <span class="proj-chevron"></span>
        </summary>
        <div class="tbl-wrap">
        <table>
        <thead><tr><th>Project</th><th>Status</th><th>Open</th><th>Progress</th><th>Fresh</th><th>Next Action</th><th>Agents</th><th></th></tr></thead>
        <tbody>{project_rows}</tbody>
        </table>
        </div>
    </details>
    <details class="proj-details">
        <summary class="proj-summary">
            <div class="section-dot" style="background:var(--dim)"></div>
            <span class="section-title">Done</span>
            <span class="section-count">{len(completed_projs)}</span>
            <span class="proj-chevron"></span>
        </summary>
        <div class="tbl-wrap">
        <table>
        <thead><tr><th>Project</th><th>Status</th><th>Done</th><th>Progress</th><th>Last</th><th>Final State</th><th>Agents</th><th></th></tr></thead>
        <tbody>{completed_rows}</tbody>
        </table>
        </div>
    </details>
</div>

<!-- System Section -->
<div class="section" id="system">
    <div class="section-head">
        <div class="section-dot" style="background:var(--accent)"></div>
        <div class="section-title">System</div>
        <div class="section-count">{now_data['active_agents']}/{now_data['total_agents']} agents</div>
    </div>
    {system_html}
</div>

<!-- Costs Section -->
<div class="section" id="costs">
    <div class="section-head">
        <div class="section-dot" style="background:var(--yellow)"></div>
        <div class="section-title">Costs</div>
        <div class="section-count">${costs_data['total_monthly']:,.0f}/mo</div>
    </div>
    {costs_html}
</div>

<div class="footer">command center v4 // {now_data['total_agents']} agents // {timestamp}</div>

</main>
</div>
<script>
{js_text}
</script>
</body>
</html>"""
