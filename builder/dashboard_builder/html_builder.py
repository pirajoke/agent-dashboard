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
from .department_campus import build_department_campus_html
from .platforms import build_platform_hub_html


def _is_project_finished(p: dict) -> bool:
    """Finished only when the vault says so: a done status, or every TODO closed."""
    if p.get("status", "").lower() in ("done", "completed", "archived"):
        return True
    return p["open_todos"] == 0 and p["closed_todos"] > 0


def _build_projects_section(active_count: int, finished_count: int, unknown_count: int) -> str:
    """The Projects section of the page, which is also published on GitHub Pages.

    It holds counts only. Project names, task text and Obsidian vault paths are private
    (AGENTS.md §10): Mark sees them in MAIN MANAGER on command.meshly.fr after sign-in.
    A project with no status and no TODOs is counted as unknown, never as finished.
    """
    counts = f"В работе {active_count}, завершено {finished_count}"
    if unknown_count:
        counts += f", без статуса {unknown_count}"
    return f"""<!-- Projects Section -->
<div class="section" id="projects">
    <div class="section-head">
        <div class="section-dot" style="background:var(--green)"></div>
        <div class="section-title">Projects</div>
        <div class="section-count">{active_count} active</div>
    </div>
    <div class="proj-details">
        <p style="margin:0;padding:0.9rem 1.2rem;color:var(--dim);font-size:0.8rem;line-height:1.5">{counts}. Названия и задачи проектов видны только в MAIN MANAGER на command.meshly.fr после входа.</p>
    </div>
</div>"""


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
    campus_html = build_department_campus_html()
    platform_html = build_platform_hub_html()

    # Projects
    active_projs = [p for p in projects if is_project_active(p)]
    finished_count = sum(1 for p in projects if not is_project_active(p) and _is_project_finished(p))
    unknown_count = len(projects) - len(active_projs) - finished_count
    projects_html = _build_projects_section(len(active_projs), finished_count, unknown_count)

    css_text = (ASSETS_DIR / "style.css").read_text()
    js_text = (ASSETS_DIR / "script.js").read_text()
    js_text += "\n" + (ASSETS_DIR / "media.js").read_text()

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Common Center</title>
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
        <h1>Common Center</h1>
        <div class="sb-sub">portfolio operations</div>
    </div>
    <ul class="sidebar-nav">
        <li><a data-target="#common-center" href="#common-center" class="active">
            <svg class="nav-icon" viewBox="0 0 16 16"><rect x="2" y="2" width="5" height="5" rx="1" stroke="currentColor" fill="none" stroke-width="1.2"/><rect x="9" y="2" width="5" height="5" rx="1" stroke="currentColor" fill="none" stroke-width="1.2"/><rect x="2" y="9" width="5" height="5" rx="1" stroke="currentColor" fill="none" stroke-width="1.2"/><rect x="9" y="9" width="5" height="5" rx="1" stroke="currentColor" fill="none" stroke-width="1.2"/></svg>
            Common Center
        </a></li>
        <li><a data-target="#theater" href="#theater">
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

<!-- Common Center platform switchboard -->
{platform_html}

<!-- Theater Section -->
<div class="topbar" id="theater-top">
    <div class="topbar-title">Agent Theater</div>
    <div class="topbar-meta">
        <span class="tm-item"><span class="live-dot"></span> Live</span>
        <span class="tm-item">{timestamp}</span>
    </div>
</div>

{theater_html}

<!-- Department Campus -->
{campus_html}

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

{projects_html}

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

<div class="footer">common center v1 // {now_data['total_agents']} agents // {timestamp}</div>

</main>
</div>
<script>
{js_text}
</script>
</body>
</html>"""

