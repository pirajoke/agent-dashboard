"""Agent health logic and network SVG builder."""
from __future__ import annotations

from datetime import datetime

from .config import AGENTS, AGENT_COLORS, CHAINS


def _agent_has_recent_comms(agent_id: str, comms: list[dict], hours: float = 1.0) -> bool:
    if not comms:
        return False
    cutoff = datetime.utcnow().timestamp() - (hours * 3600)
    for m in comms:
        ts_str = m.get("ts", "")
        try:
            msg_ts = datetime.strptime(ts_str, "%Y-%m-%dT%H:%M:%SZ").timestamp()
        except ValueError:
            continue
        if msg_ts >= cutoff and (m.get("from") == agent_id or m.get("to") == agent_id):
            return True
    return False


def agent_health(agent: dict, projects: list[dict], comms: list[dict] | None = None) -> str:
    if comms and _agent_has_recent_comms(agent["id"], comms):
        return "active"
    agent_projects = [p for p in projects if p["name"] in agent["projects"]]
    if not agent_projects:
        return "idle"
    has_active = any(p["status"] == "active" for p in agent_projects)
    total_open = sum(p["open_todos"] for p in agent_projects)
    max_fresh = min((p.get("freshness_days", 999) for p in agent_projects), default=999)
    if has_active and max_fresh <= 7:
        return "active"
    if total_open > 0 and max_fresh <= 30:
        return "idle"
    return "blocked" if total_open > 0 else "idle"


def build_network_svg(healths: dict) -> str:
    positions = {
        "COORDINATOR": (280, 50),
        "RESEARCHER":  (80, 170),
        "ANALYST":     (230, 170),
        "VAULT":       (380, 170),
        "BUILDER":     (480, 170),
    }

    edges = ""
    for src, tgt in CHAINS:
        x1, y1 = positions[src]
        x2, y2 = positions[tgt]
        src_color = AGENT_COLORS.get(src, "#8b949e")
        edges += (
            f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" '
            f'stroke="{src_color}" stroke-width="1.5" opacity="0.25"/>'
            f'<circle r="2.5" fill="{src_color}" opacity="0.8">'
            f'<animateMotion dur="{3 + hash(src+tgt) % 4}s" repeatCount="indefinite" '
            f'path="M{x1},{y1} L{x2},{y2}"/>'
            f'</circle>'
        )

    nodes = ""
    for agent_id, (x, y) in positions.items():
        color = AGENT_COLORS.get(agent_id, "#8b949e")
        health = healths.get(agent_id, "idle")
        glow = ""
        if health == "active":
            glow = (
                f'<circle cx="{x}" cy="{y}" r="24" fill="none" stroke="{color}" '
                f'stroke-width="1" opacity="0.3">'
                f'<animate attributeName="r" values="24;28;24" dur="2s" repeatCount="indefinite"/>'
                f'<animate attributeName="opacity" values="0.3;0.1;0.3" dur="2s" repeatCount="indefinite"/>'
                f'</circle>'
            )
        nodes += f"""
        {glow}
        <circle cx="{x}" cy="{y}" r="20" fill="{color}18" stroke="{color}" stroke-width="1.5"/>
        <text x="{x}" y="{y-3}" text-anchor="middle" fill="{color}" font-size="7" font-weight="800"
              font-family="JetBrains Mono,monospace" letter-spacing="0.05em">{agent_id[:4]}</text>
        <text x="{x}" y="{y+8}" text-anchor="middle" fill="#64748b" font-size="5.5"
              font-family="Inter,sans-serif" font-weight="600">{health}</text>"""

    return (
        f'<svg viewBox="0 0 580 260" width="100%" height="260" '
        f'xmlns="http://www.w3.org/2000/svg" style="display:block">'
        f'{edges}{nodes}</svg>'
    )
