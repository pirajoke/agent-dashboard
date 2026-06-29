"""Fraction Agent — show all running processes, sessions, MCP servers, token usage, RAM."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from .config import USAGE_FILE, ORCH_FILE, HEALTH_DIR, fmt_tok


def _run(cmd: str) -> str:
    try:
        return subprocess.check_output(cmd, shell=True, stderr=subprocess.DEVNULL, timeout=5).decode().strip()
    except Exception:
        return ""


def _get_claude_sessions() -> list[dict]:
    """Find all running Claude processes."""
    lines = _run("ps aux | grep -i '[c]laude'")
    sessions = []
    for line in lines.splitlines():
        parts = line.split()
        if len(parts) < 11:
            continue
        pid = parts[1]
        cpu = parts[2]
        mem_pct = parts[3]
        rss_kb = int(parts[5]) if parts[5].isdigit() else 0
        ram_mb = round(rss_kb / 1024)
        started = parts[8]
        cmd = " ".join(parts[10:])[:80]
        sessions.append({
            "pid": pid, "cpu": cpu, "mem_pct": mem_pct,
            "ram_mb": ram_mb, "started": started, "cmd": cmd,
            "type": "claude"
        })
    return sessions


def _get_node_processes() -> list[dict]:
    """Find all Node.js processes (MCP servers, Codex, etc)."""
    lines = _run("ps aux | grep '[n]ode'")
    procs = []
    for line in lines.splitlines():
        parts = line.split()
        if len(parts) < 11:
            continue
        pid = parts[1]
        cpu = parts[2]
        mem_pct = parts[3]
        rss_kb = int(parts[5]) if parts[5].isdigit() else 0
        ram_mb = round(rss_kb / 1024)
        started = parts[8]
        cmd_full = " ".join(parts[10:])

        # Classify
        ptype = "node"
        label = cmd_full[:60]
        if "mcp" in cmd_full.lower() or "mcp-remote" in cmd_full:
            ptype = "mcp"
            # Extract MCP server name
            if "exa-mcp" in cmd_full:
                label = "MCP: Exa Search"
            elif "obsidian-mcp" in cmd_full:
                label = "MCP: Obsidian"
            elif "linear" in cmd_full:
                label = "MCP: Linear"
            elif "magic" in cmd_full:
                label = "MCP: Magic (21st.dev)"
            elif "pencil" in cmd_full:
                label = "MCP: Pencil"
            else:
                label = f"MCP: {cmd_full[:40]}"
        elif "codex" in cmd_full.lower():
            ptype = "codex"
            label = "OpenAI Codex"
        elif "claude" in cmd_full.lower():
            ptype = "claude-node"
            label = "Claude (Node wrapper)"

        procs.append({
            "pid": pid, "cpu": cpu, "mem_pct": mem_pct,
            "ram_mb": ram_mb, "started": started, "cmd": label,
            "type": ptype
        })
    return procs


def _get_python_processes() -> list[dict]:
    """Find Python background processes."""
    lines = _run("ps aux | grep '[p]ython'")
    procs = []
    for line in lines.splitlines():
        parts = line.split()
        if len(parts) < 11:
            continue
        pid = parts[1]
        cpu = parts[2]
        mem_pct = parts[3]
        rss_kb = int(parts[5]) if parts[5].isdigit() else 0
        ram_mb = round(rss_kb / 1024)
        started = parts[8]
        cmd_full = " ".join(parts[10:])
        if "build-agent-dashboard" in cmd_full:
            continue  # Skip self
        label = cmd_full[:60]
        if "live-feed" in cmd_full:
            label = "generate-live-feed.py"
        elif "alert-monitor" in cmd_full:
            label = "alert-monitor.py"
        elif "linear" in cmd_full:
            label = "Linear worker"

        procs.append({
            "pid": pid, "cpu": cpu, "mem_pct": mem_pct,
            "ram_mb": ram_mb, "started": started, "cmd": label,
            "type": "python"
        })
    return procs


def _get_launchd_services() -> list[dict]:
    """Get all pirajoke launchd services."""
    lines = _run("launchctl list 2>/dev/null | grep pirajoke")
    services = []
    for line in lines.splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        pid = parts[0].strip()
        exit_code = parts[1].strip()
        name = parts[2].strip().replace("com.pirajoke.", "")
        status = "running" if pid != "-" and pid != "0" else ("error" if exit_code != "0" else "idle")
        services.append({
            "name": name,
            "pid": pid if pid not in ("-", "0") else "",
            "exit_code": exit_code,
            "status": status
        })
    return services


def _get_token_usage() -> dict:
    """Load token/cost usage data."""
    if not USAGE_FILE.exists():
        return {}
    try:
        return json.loads(USAGE_FILE.read_text())
    except Exception:
        return {}


def _get_orchestrator() -> dict:
    """Load orchestrator state."""
    if not ORCH_FILE.exists():
        return {}
    try:
        return json.loads(ORCH_FILE.read_text())
    except Exception:
        return {}


def collect_fraction_data() -> dict:
    """Collect all fraction data."""
    claude = _get_claude_sessions()
    node = _get_node_processes()
    python = _get_python_processes()
    launchd = _get_launchd_services()
    usage = _get_token_usage()
    orch = _get_orchestrator()

    all_procs = claude + node + python
    total_ram = sum(p["ram_mb"] for p in all_procs)

    return {
        "processes": all_procs,
        "launchd": launchd,
        "usage": usage,
        "orchestrator": orch,
        "total_ram_mb": total_ram,
        "total_processes": len(all_procs),
        "mcp_count": sum(1 for p in node if p["type"] == "mcp"),
    }


def build_fraction_html(data: dict) -> str:
    """Build the Fraction Agent HTML section."""
    procs = data["processes"]
    launchd = data["launchd"]
    usage = data.get("usage", {})
    orch = data.get("orchestrator", {})

    # Summary stats
    mcp_count = data["mcp_count"]
    total_ram = data["total_ram_mb"]
    total_procs = data["total_processes"]
    running_services = sum(1 for s in launchd if s["status"] == "running")
    idle_services = sum(1 for s in launchd if s["status"] == "idle")
    error_services = sum(1 for s in launchd if s["status"] == "error")

    # Token usage cards
    usage_html = ""
    if usage:
        for provider_key in ("claude", "codex"):
            pdata = usage.get(provider_key, {})
            if not pdata:
                continue
            name = pdata.get("name", provider_key.title())
            plan = pdata.get("plan", "")
            tokens_month = pdata.get("tokens_this_month", 0)
            cost_month = pdata.get("api_equivalent_month", 0)
            savings = pdata.get("savings_multiplier", 0)
            color = "#ff6b35" if provider_key == "claude" else "#3fb950"
            usage_html += f"""
            <div class="frac-usage-card" style="border-left: 3px solid {color}">
                <div class="frac-usage-header">
                    <span class="frac-usage-name" style="color:{color}">{name}</span>
                    <span class="frac-usage-plan">{plan}</span>
                </div>
                <div class="frac-usage-stats">
                    <div class="frac-stat">
                        <div class="frac-stat-val">{fmt_tok(tokens_month)}</div>
                        <div class="frac-stat-lbl">tokens/month</div>
                    </div>
                    <div class="frac-stat">
                        <div class="frac-stat-val">${cost_month:,.0f}</div>
                        <div class="frac-stat-lbl">API-eq cost</div>
                    </div>
                    <div class="frac-stat">
                        <div class="frac-stat-val">{savings:.1f}x</div>
                        <div class="frac-stat-lbl">savings</div>
                    </div>
                </div>
            </div>"""

    # Orchestrator mode
    mode = orch.get("mode", "unknown")
    orch_html = ""
    if mode != "unknown":
        budgets = orch.get("budgets", {})
        claude_daily = budgets.get("claude", {}).get("daily", "?")
        codex_daily = budgets.get("codex", {}).get("daily", "?")
        orch_html = f"""
        <div class="frac-orch">
            <span class="frac-orch-mode">Mode: <strong>{mode}</strong></span>
            <span class="frac-orch-budget">Claude ${claude_daily}/d &middot; Codex ${codex_daily}/d</span>
        </div>"""

    # Process table
    type_icons = {
        "claude": ("C", "#ff6b35"),
        "codex": ("X", "#3fb950"),
        "mcp": ("M", "#06b6d4"),
        "claude-node": ("N", "#ff6b35"),
        "node": ("N", "#8b949e"),
        "python": ("P", "#eab308"),
    }

    proc_rows = ""
    for p in sorted(procs, key=lambda x: x["ram_mb"], reverse=True):
        icon_letter, icon_color = type_icons.get(p["type"], ("?", "#8b949e"))
        ram_class = "frac-ram-high" if p["ram_mb"] > 200 else ("frac-ram-mid" if p["ram_mb"] > 50 else "")
        proc_rows += f"""
        <tr>
            <td><span class="frac-type-badge" style="background:{icon_color}20;color:{icon_color}">{icon_letter}</span></td>
            <td class="frac-cmd">{p["cmd"]}</td>
            <td class="frac-pid">{p["pid"]}</td>
            <td class="frac-cpu">{p["cpu"]}%</td>
            <td class="frac-ram {ram_class}">{p["ram_mb"]} MB</td>
            <td class="frac-started">{p["started"]}</td>
        </tr>"""

    # Launchd services table
    svc_rows = ""
    for s in sorted(launchd, key=lambda x: (0 if x["status"] == "running" else (1 if x["status"] == "error" else 2))):
        dot = "dot-green" if s["status"] == "running" else ("dot-red" if s["status"] == "error" else "dot-dim")
        svc_rows += f"""
        <tr>
            <td><span class="status-dot {dot}"></span></td>
            <td class="frac-svc-name">{s["name"]}</td>
            <td class="frac-pid">{s["pid"]}</td>
            <td class="frac-status frac-status-{s["status"]}">{s["status"]}</td>
        </tr>"""

    return f"""
    <div class="frac-summary">
        <div class="frac-summary-item">
            <div class="frac-summary-val accent">{total_procs}</div>
            <div class="frac-summary-lbl">Processes</div>
        </div>
        <div class="frac-summary-item">
            <div class="frac-summary-val blue">{mcp_count}</div>
            <div class="frac-summary-lbl">MCP Servers</div>
        </div>
        <div class="frac-summary-item">
            <div class="frac-summary-val yellow">{total_ram} MB</div>
            <div class="frac-summary-lbl">Total RAM</div>
        </div>
        <div class="frac-summary-item">
            <div class="frac-summary-val green">{running_services}</div>
            <div class="frac-summary-lbl">Services</div>
        </div>
        <div class="frac-summary-item">
            <div class="frac-summary-val" style="color:var(--red)">{error_services}</div>
            <div class="frac-summary-lbl">Errors</div>
        </div>
    </div>

    {orch_html}
    {usage_html}

    <details class="frac-details" open>
        <summary class="frac-details-sum">Active Processes ({total_procs})</summary>
        <div class="tbl-wrap">
        <table class="frac-table">
        <thead><tr><th></th><th>Process</th><th>PID</th><th>CPU</th><th>RAM</th><th>Since</th></tr></thead>
        <tbody>{proc_rows}</tbody>
        </table>
        </div>
    </details>

    <details class="frac-details">
        <summary class="frac-details-sum">LaunchD Services ({len(launchd)}) &mdash; {running_services} running, {idle_services} idle, {error_services} errors</summary>
        <div class="tbl-wrap">
        <table class="frac-table">
        <thead><tr><th></th><th>Service</th><th>PID</th><th>Status</th></tr></thead>
        <tbody>{svc_rows}</tbody>
        </table>
        </div>
    </details>
    """
