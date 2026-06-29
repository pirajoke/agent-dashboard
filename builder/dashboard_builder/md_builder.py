"""Markdown dashboard builder for Obsidian."""
from __future__ import annotations

from datetime import datetime

from .config import AGENTS, CHAINS
from .agents import agent_health


def build_md(projects: list[dict], snapshot_label: str, comms: list[dict] | None = None) -> str:
    total_open = sum(p["open_todos"] for p in projects)
    total_closed = sum(p["closed_todos"] for p in projects)
    overall_pct = round(total_closed / max(total_open + total_closed, 1) * 100)

    lines = [
        "---",
        "type: dashboard",
        f"date: {datetime.now().strftime('%Y-%m-%d')}",
        "status: active",
        "tags: [agents, dashboard, second-brain]",
        "---",
        "",
        "# Agents Dashboard",
        "",
        f"> Auto-generated: {snapshot_label}",
        "",
        f"> **{len(AGENTS)} agents** | **{len(projects)} projects** | **{total_open} open** | **{total_closed} done** | **{overall_pct}% overall**",
        "",
        "## Agents",
        "",
        "| | ID | Name | Zone | Projects | Open | Health |",
        "|---|---|---|---|---|---|---|",
    ]
    for a in AGENTS:
        a_open = sum(p["open_todos"] for p in projects if p["name"] in a["projects"])
        health = agent_health(a, projects, comms)
        health_icon = {"active": "\U0001f7e2", "idle": "\U0001f7e1", "blocked": "\U0001f534"}[health]
        proj_list = ", ".join(a["projects"])
        lines.append(f"| {health_icon} | {a['id']} | {a['name']} | {a['zone']} | {proj_list} | {a_open} | {health} |")

    lines += [
        "",
        "## Delegation Chains",
        "",
    ]
    for src, tgt in CHAINS:
        lines.append(f"- **{src}** \u2192 {tgt}")

    lines += [
        "",
        "## Projects",
        "",
        "| Project | Status | Open | Progress | Freshness | Next Action | Agents |",
        "|---|---|---|---|---|---|---|",
    ]
    for p in projects:
        total = p["open_todos"] + p["closed_todos"]
        pct = f"{round(p['closed_todos'] / total * 100)}%" if total > 0 else "\u2014"
        agents_str = ", ".join(p["agents"]) if p["agents"] else "\u2014"
        na = p["next_action"]
        if len(na) > 55:
            na = na[:52] + "..."
        fresh = p.get("freshness_days", 999)
        fresh_label = f"{fresh}d" if fresh < 999 else "\u2014"
        lines.append(
            f"| {p['name']} | {p['status']} | {p['open_todos']} | {pct} | {fresh_label} | {na} | {agents_str} |"
        )

    lines += [
        "",
        "---",
        f"*Last updated: {snapshot_label}*",
    ]
    return "\n".join(lines)
