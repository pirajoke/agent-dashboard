"""Real Agents — detect and display actually running agents/services."""
from __future__ import annotations

import json
import subprocess
from datetime import datetime
from pathlib import Path

from .config import HEALTH_DIR, ORCH_FILE


def _run(cmd: str) -> str:
    try:
        return subprocess.check_output(cmd, shell=True, stderr=subprocess.DEVNULL, timeout=5).decode().strip()
    except Exception:
        return ""


def _parse_ps_line(line: str) -> dict | None:
    parts = line.split()
    if len(parts) < 11:
        return None
    return {
        "pid": parts[1],
        "cpu": parts[2],
        "mem_pct": parts[3],
        "rss_kb": int(parts[5]) if parts[5].isdigit() else 0,
        "ram_mb": round(int(parts[5]) / 1024) if parts[5].isdigit() else 0,
        "started": parts[8],
        "cmd": " ".join(parts[10:]),
    }


def _get_launchd_status(label: str) -> str:
    """Check if a launchd service is running."""
    out = _run(f"launchctl list 2>/dev/null | grep '{label}'")
    if not out:
        return "off"
    parts = out.split("\t")
    if len(parts) >= 3:
        pid = parts[0].strip()
        if pid not in ("-", "0", ""):
            return "running"
        exit_code = parts[1].strip()
        return "error" if exit_code != "0" else "idle"
    return "off"


def _count_mcp_servers() -> list[dict]:
    """Find MCP server processes."""
    lines = _run("ps aux | grep '[n]ode'")
    servers = []
    for line in lines.splitlines():
        cmd = " ".join(line.split()[10:])
        if "mcp" in cmd.lower() or "mcp-remote" in cmd:
            p = _parse_ps_line(line)
            if not p:
                continue
            if "exa-mcp" in cmd:
                name = "Exa Search"
            elif "obsidian-mcp" in cmd:
                name = "Obsidian"
            elif "linear" in cmd:
                name = "Linear"
            elif "magic" in cmd:
                name = "Magic"
            elif "pencil" in cmd:
                name = "Pencil"
            else:
                name = cmd[:30]
            servers.append({"name": name, "pid": p["pid"], "ram_mb": p["ram_mb"]})
    return servers


def _get_health_age(name: str) -> str | None:
    """Get last health check time."""
    f = HEALTH_DIR / f"{name}.json"
    if not f.exists():
        return None
    try:
        data = json.loads(f.read_text())
        ts = data.get("timestamp", "")
        if ts:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            age = (datetime.now(dt.tzinfo) - dt).total_seconds() / 3600
            if age < 1:
                return f"{int(age * 60)}m ago"
            elif age < 24:
                return f"{int(age)}h ago"
            else:
                return f"{int(age / 24)}d ago"
    except Exception:
        pass
    return None


def collect_real_agents() -> list[dict]:
    """Detect all real running agents."""
    agents = []

    # ── 1. Claude Code sessions ──
    claude_lines = _run("ps aux | grep -i '[c]laude'")
    claude_procs = []
    for line in claude_lines.splitlines():
        p = _parse_ps_line(line)
        if p and "claude" in p["cmd"].lower():
            claude_procs.append(p)

    mcp_servers = _count_mcp_servers()
    total_claude_ram = sum(p["ram_mb"] for p in claude_procs)

    agents.append({
        "id": "CLAUDE",
        "name": "Claude Code",
        "icon": "C",
        "color": "#ff6b35",
        "zone": "AI coding sessions + MCP servers",
        "health": "active" if claude_procs else "off",
        "stats": [
            f"{len(claude_procs)} session{'s' if len(claude_procs) != 1 else ''}",
            f"{len(mcp_servers)} MCP servers",
            f"{total_claude_ram} MB RAM",
        ],
        "sub_items": [
            {"name": f"Session PID {p['pid']}", "detail": f"CPU {p['cpu']}% · {p['ram_mb']} MB", "status": "running"}
            for p in claude_procs
        ] + [
            {"name": f"MCP: {s['name']}", "detail": f"PID {s['pid']} · {s['ram_mb']} MB", "status": "running"}
            for s in mcp_servers
        ],
    })

    # ── 2. OpenAI Codex ──
    codex_lines = _run("ps aux | grep '[c]odex'")
    codex_procs = []
    for line in codex_lines.splitlines():
        p = _parse_ps_line(line)
        if p:
            codex_procs.append(p)

    codex_ram = sum(p["ram_mb"] for p in codex_procs)
    agents.append({
        "id": "CODEX",
        "name": "OpenAI Codex",
        "icon": "X",
        "color": "#3fb950",
        "zone": "AI code execution + task runner",
        "health": "active" if codex_procs else "off",
        "stats": [
            f"{len(codex_procs)} process{'es' if len(codex_procs) != 1 else ''}",
            f"{codex_ram} MB RAM",
        ],
        "sub_items": [
            {"name": f"Codex PID {p['pid']}", "detail": f"CPU {p['cpu']}% · {p['ram_mb']} MB", "status": "running"}
            for p in codex_procs
        ],
    })

    # ── 3. JARVIS (voice + menubar + bridge) ──
    jarvis_parts = []
    for label, display in [
        ("jarvis-voice", "Voice Engine"),
        ("jarvis-menubar", "Menu Bar"),
        ("bridge-api", "Bridge API"),
        ("bridge-worker", "Bridge Worker"),
        ("bridge-tunnel", "Bridge Tunnel"),
    ]:
        status = _get_launchd_status(label)
        jarvis_parts.append({"name": display, "detail": f"launchd: {label}", "status": status})

    running_parts = sum(1 for p in jarvis_parts if p["status"] == "running")
    total_parts = len(jarvis_parts)
    jarvis_health = "active" if running_parts >= 3 else ("degraded" if running_parts > 0 else "off")

    agents.append({
        "id": "JARVIS",
        "name": "JARVIS",
        "icon": "J",
        "color": "#58a6ff",
        "zone": "Voice assistant + bridge infrastructure",
        "health": jarvis_health,
        "stats": [
            f"{running_parts}/{total_parts} services",
            _get_health_age("morning-brief") or "no heartbeat",
        ],
        "sub_items": jarvis_parts,
    })

    # ── 4. Atlas (daily hygiene) ──
    atlas_status = _get_launchd_status("daily-hygiene")
    atlas_health_age = None
    hygiene_dir = Path.home() / "ObsidianVault" / "90-Operations" / "HYGIENE" / "reports"
    if hygiene_dir.exists():
        reports = sorted(hygiene_dir.glob("*daily-hygiene.md"), reverse=True)
        if reports:
            try:
                fname = reports[0].stem
                date_str = fname[:10]
                dt = datetime.strptime(date_str, "%Y-%m-%d")
                days_ago = (datetime.now() - dt).days
                atlas_health_age = "today" if days_ago == 0 else (f"{days_ago}d ago" if days_ago > 0 else "future")
            except Exception:
                pass

    atlas_health = "active" if atlas_status in ("running", "idle") and atlas_health_age in ("today", None) else "degraded"
    if atlas_status == "off":
        atlas_health = "off"

    agents.append({
        "id": "ATLAS",
        "name": "Atlas",
        "icon": "A",
        "color": "#79c0ff",
        "zone": "Mac Mini M4 system monitor · daily hygiene",
        "health": atlas_health,
        "stats": [
            f"launchd: {atlas_status}",
            f"last report: {atlas_health_age or 'never'}",
        ],
        "sub_items": [
            {"name": "Daily Hygiene Cron", "detail": f"09:00 KL time · {atlas_status}", "status": atlas_status if atlas_status != "idle" else "running"},
        ],
    })

    # ── 5. Dashboard (live-feed + rebuild) ──
    feed_status = _get_launchd_status("generate-live-feed")
    rebuild_status = _get_launchd_status("dashboard-rebuild")
    dash_running = sum(1 for s in [feed_status, rebuild_status] if s in ("running", "idle"))
    dash_health = "active" if dash_running == 2 else ("degraded" if dash_running > 0 else "off")

    agents.append({
        "id": "DASHBOARD",
        "name": "Dashboard",
        "icon": "D",
        "color": "#ffa657",
        "zone": "Self-update pipeline · live feed + rebuild",
        "health": dash_health,
        "stats": [
            f"feed: {feed_status}",
            f"rebuild: {rebuild_status}",
        ],
        "sub_items": [
            {"name": "Live Feed Generator", "detail": f"launchd · {feed_status}", "status": feed_status if feed_status != "idle" else "running"},
            {"name": "Dashboard Rebuild", "detail": f"launchd · 3x/day", "status": rebuild_status if rebuild_status != "idle" else "running"},
        ],
    })

    return agents


def build_real_agents_html(agents: list[dict]) -> str:
    """Build agent cards HTML using v1 orb design."""
    cards = ""
    for a in agents:
        health = a["health"]
        color = a["color"]
        dot_map = {"active": "ag-dot-active", "degraded": "ag-dot-blocked", "off": "ag-dot-idle"}
        dot_cls = f"ag-dot {dot_map.get(health, 'ag-dot-idle')}"

        # Stats line
        stats_line = " · ".join(a["stats"])

        # Sub-items
        sub_html = ""
        for item in a.get("sub_items", []):
            s = item["status"]
            if s == "running":
                sub_dot = "dot-green"
            elif s in ("error", "off"):
                sub_dot = "dot-red"
            else:
                sub_dot = "dot-dim"
            sub_html += f"""
            <div class="ag-sub-item">
                <span class="status-dot {sub_dot}"></span>
                <span class="ag-sub-name">{item["name"]}</span>
                <span class="ag-sub-detail">{item["detail"]}</span>
            </div>"""

        cards += f"""
        <div class="ag ag-{health}">
            <div class="ag-top">
                <div class="ag-orb" style="background:{color}">
                    <div class="ag-orb-ring" style="border-color:{color}"></div>
                    {a["icon"]}
                </div>
                <div class="ag-info">
                    <div class="ag-id" style="color:{color}">{a["id"]}</div>
                    <div class="ag-name">{a["name"]}</div>
                </div>
                <div class="ag-status"><div class="{dot_cls}"></div></div>
            </div>
            <div class="ag-zone">{a["zone"]}</div>
            <div class="ag-stats-line">{stats_line}</div>
            <div class="ag-sub-items">{sub_html}</div>
        </div>"""

    return cards
