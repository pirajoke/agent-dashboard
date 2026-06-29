"""Atlas — System Monitor: M4 health, hygiene reports, services."""
from __future__ import annotations

import re
from datetime import datetime, date
from pathlib import Path

HYGIENE_DIR = Path.home() / "ObsidianVault" / "90-Operations" / "HYGIENE" / "reports"

_HEALTH_ICONS = {
    "disk": ("💾", "Storage", "Place for files", "SSD storage on Mac mini. If full, nothing works."),
    "memory": ("🧠", "Memory", "Speed for apps", "RAM for running apps. macOS compresses unused data automatically."),
    "docker": ("🐳", "Database", "Data storage", "PostgreSQL database container. Stores project data (bots, APIs)."),
    "tailscale": ("🔗", "Network", "Remote access", "VPN tunnel for remote access from anywhere in the world."),
    "launchd": ("⚙️", "Services", "Background tasks", "Auto-start tasks: tunnel, backups, bots. Runs 24/7."),
    "backup": ("📦", "Backup", "Data safety net", "Nightly database copy. Insurance against data loss."),
    "git": ("📂", "Code Sync", "Notes sync", "Obsidian vault sync with GitHub. Ensures notes are backed up."),
    "locks": ("🔒", "Locks", "Cleanup check", "Stale temp files from crashed scripts. Auto-cleaned if found."),
}


def _parse_hygiene_report(path: Path) -> dict:
    """Parse a daily-hygiene.md report."""
    text = path.read_text(errors="replace")
    result = {"date": "", "tldr": "", "health": [], "fixed": [], "blocked": [], "verdict": "green"}

    # Date from filename
    fname = path.stem
    m = re.match(r"(\d{4}-\d{2}-\d{2})", fname)
    if m:
        result["date"] = m.group(1)

    # TL;DR
    tldr_m = re.search(r"TL;DR:\s*(.+)", text)
    if tldr_m:
        result["tldr"] = tldr_m.group(1).strip()

    # System Health table
    for line in text.splitlines():
        parts = [p.strip() for p in line.split("|") if p.strip()]
        if len(parts) >= 4 and parts[0].lower() not in ("check", "---", ""):
            check_name = parts[0].lower()
            status = parts[1].lower()
            detail = parts[2]
            icon, label, short, desc = _HEALTH_ICONS.get(check_name, ("❓", check_name.title(), "", ""))
            result["health"].append({
                "key": check_name, "status": status, "detail": detail,
                "icon": icon, "label": label, "short": short, "desc": desc
            })

    # Fixed items
    in_fixed = False
    in_blocked = False
    for line in text.splitlines():
        if "## Executed" in line or "## Fixed" in line:
            in_fixed = True
            in_blocked = False
            continue
        if "## Blocked" in line:
            in_blocked = True
            in_fixed = False
            continue
        if line.startswith("## "):
            in_fixed = False
            in_blocked = False
            continue
        if in_fixed and line.strip().startswith("- ") and "TRACK_ONLY" not in line:
            result["fixed"].append(line.strip().lstrip("- "))
        if in_blocked and line.strip().startswith("- ") and line.strip() != "- none":
            result["blocked"].append(line.strip().lstrip("- "))

    if result["blocked"]:
        result["verdict"] = "red"
    elif not result["health"] or any(h["status"] != "ok" for h in result["health"]):
        result["verdict"] = "yellow"

    return result


def collect_atlas_data() -> dict:
    """Collect Atlas data from hygiene reports."""
    reports = []
    if HYGIENE_DIR.exists():
        for f in sorted(HYGIENE_DIR.glob("*daily-hygiene.md"), reverse=True)[:7]:
            reports.append(_parse_hygiene_report(f))

    latest = reports[0] if reports else None
    total_checks = len(latest["health"]) if latest else 0
    passed = sum(1 for h in latest["health"] if h["status"] == "ok") if latest else 0

    # Uptime (days since first report)
    if reports:
        try:
            first_date = datetime.strptime(reports[-1]["date"], "%Y-%m-%d").date()
            uptime_days = (date.today() - first_date).days
        except Exception:
            uptime_days = 0
    else:
        uptime_days = 0

    return {
        "latest": latest,
        "reports": reports,
        "total_checks": total_checks,
        "passed": passed,
        "uptime_days": uptime_days,
    }


def build_atlas_html(data: dict) -> str:
    """Build Atlas section HTML in v1 glassmorphism style."""
    latest = data["latest"]
    reports = data["reports"]
    passed = data["passed"]
    total = data["total_checks"]
    uptime = data["uptime_days"]

    if not latest:
        return '<div class="empty-state">No hygiene reports found</div>'

    # Health tiles
    tiles_html = ""
    for h in latest["health"]:
        color_cls = "green" if h["status"] == "ok" else ("yellow" if h["status"] == "warning" else "red")
        dot_cls = f"dot-{color_cls}"
        tiles_html += f"""
        <details class="health-tile {color_cls}">
          <summary class="health-tile-summary">
            <div class="health-tile-icon">{h["icon"]}</div>
            <div class="health-tile-info">
              <div class="health-tile-name">{h["label"]}</div>
              <div class="health-tile-detail">{h["short"]}</div>
            </div>
            <div class="health-tile-dot"><span class="status-dot {dot_cls}"></span></div>
          </summary>
          <div class="health-tile-expand">
            <div class="health-tile-desc">{h["desc"]}</div>
            <div class="health-tile-tech">{h["detail"]}</div>
          </div>
        </details>"""

    # Workflow
    workflow_html = """
    <div class="workflow-steps">
      <div class="wf-step"><div class="wf-num">1</div><div class="wf-text"><b>Connect</b> to Mac mini via SSH</div></div>
      <div class="wf-arrow">&darr;</div>
      <div class="wf-step"><div class="wf-num">2</div><div class="wf-text"><b>Check</b> 8 health metrics (disk, RAM, database, network, services, backup, git, locks)</div></div>
      <div class="wf-arrow">&darr;</div>
      <div class="wf-step"><div class="wf-num">3</div><div class="wf-text"><b>Auto-fix</b> safe issues (restart crashed DB, clean stale locks)</div></div>
      <div class="wf-arrow">&darr;</div>
      <div class="wf-step"><div class="wf-num">4</div><div class="wf-text"><b>Report</b> to Obsidian + GitHub with findings and conclusions</div></div>
    </div>"""

    # Reports history
    rpt_html = ""
    for r in reports:
        try:
            dt = datetime.strptime(r["date"], "%Y-%m-%d")
            date_label = dt.strftime("%b %d")
        except Exception:
            date_label = r["date"]

        verdict_cls = r["verdict"]
        verdict_label = "All clear" if verdict_cls == "green" else ("Warning" if verdict_cls == "yellow" else f"{len(r['blocked'])} issue{'s' if len(r['blocked']) != 1 else ''}")
        dot_cls = f"dot-{verdict_cls}"
        tldr_short = r["tldr"][:90] + "..." if len(r["tldr"]) > 90 else r["tldr"]

        fixed_html = ""
        if r["fixed"]:
            items = "".join(f"<li>{f}</li>" for f in r["fixed"])
            fixed_html = f'<div class="rpt-fixed"><span class="rpt-fixed-label">Fixed:</span><ul>{items}</ul></div>'

        blocked_html = ""
        if r["blocked"]:
            items = "".join(f"<li>{b}</li>" for b in r["blocked"])
            blocked_html = f'<div class="rpt-blocked"><span class="rpt-blocked-label">Blocked:</span><ul>{items}</ul></div>'

        rpt_html += f"""
        <details class="rpt-entry">
          <summary class="rpt-summary">
            <span class="rpt-date">{date_label}</span>
            <span class="rpt-verdict {verdict_cls}"><span class="status-dot {dot_cls}"></span> {verdict_label}</span>
            <span class="rpt-tldr">{tldr_short}</span>
          </summary>
          <div class="rpt-detail">
            <div class="rpt-tldr-full">{r["tldr"]}</div>
            {fixed_html}
            {blocked_html}
          </div>
        </details>"""

    verdict_dot = "dot-green" if passed == total else "dot-yellow"
    verdict_text = "All clear" if passed == total else f"{total - passed} issues"
    verdict_cls = "ok" if passed == total else "yellow"

    return f"""
    <div class="atlas-header">
        <div class="atlas-mascot">
            <div class="avatar" style="background:#1a3a2a"><span class="avatar-emoji">&#x1F6E1;</span></div>
        </div>
        <div class="atlas-info">
            <div class="atlas-name">Atlas <span class="atlas-role">System Monitor</span></div>
            <div class="atlas-status">
                <span class="status-dot {verdict_dot}"></span> Online &middot; {uptime} days
                &middot; <span class="status-dot {verdict_dot}"></span> {passed}/{total} checks passed
                &middot; Next: <span id="hygiene-timer">...</span>
            </div>
        </div>
        <div class="agent-alert {verdict_cls}"><span class="status-dot {verdict_dot}"></span> {verdict_text}</div>
    </div>

    <details class="atlas-section" open>
        <summary class="atlas-section-sum">System Health ({passed}/{total})</summary>
        <div class="health-grid">{tiles_html}</div>
    </details>

    <details class="atlas-section">
        <summary class="atlas-section-sum">How Atlas Works</summary>
        {workflow_html}
    </details>

    <details class="atlas-section">
        <summary class="atlas-section-sum">Daily Reports ({len(reports)})</summary>
        <div class="rpt-list">{rpt_html}</div>
    </details>
    """
