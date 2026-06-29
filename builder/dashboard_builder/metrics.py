"""Agent performance metrics loader and HTML builder."""
from __future__ import annotations

from pathlib import Path

from .config import AGENTS, AGENT_COLORS, AGENT_LEGACY_MAP


def load_metrics() -> dict[str, dict]:
    metrics_script = Path.home() / "scripts" / "agent_metrics.py"
    if not metrics_script.exists():
        return {}
    import importlib.util
    spec = importlib.util.spec_from_file_location("agent_metrics", str(metrics_script))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    stats = mod.get_all_stats()
    # Merge legacy agents into consolidated ones
    for old_id, new_id in AGENT_LEGACY_MAP.items():
        if old_id in stats and stats[old_id].get("tasks", 0) > 0:
            old = stats[old_id]
            if new_id not in stats:
                stats[new_id] = old
            else:
                new = stats[new_id]
                for k in ("tasks", "done", "blocked", "failed", "total_tokens"):
                    new[k] = new.get(k, 0) + old.get(k, 0)
                if new["tasks"] > 0:
                    new["success_rate"] = round(new["done"] / new["tasks"] * 100, 1)
                new_projs = set(new.get("projects", []))
                new_projs.update(old.get("projects", []))
                new["projects"] = sorted(new_projs)
            del stats[old_id]
    for agent_id, s in stats.items():
        s["efficiency"] = mod.efficiency_score(s)
    return stats


def build_metrics_html(metrics: dict[str, dict]) -> str:
    if not metrics or all(s.get("tasks", 0) == 0 for s in metrics.values()):
        return '<div class="section-empty">No metrics data yet. Metrics accumulate as agents complete tasks.</div>'

    ranked = sorted(metrics.items(), key=lambda x: x[1].get("efficiency", 0), reverse=True)
    active_agents = [(a, s) for a, s in ranked if s.get("tasks", 0) > 0]

    if not active_agents:
        return '<div class="section-empty">No metrics data yet.</div>'

    rows = ""
    for rank, (agent_id, s) in enumerate(active_agents, 1):
        color = AGENT_COLORS.get(agent_id, "#8b949e")
        eff = s.get("efficiency", 0)
        sr = s.get("success_rate", 0)
        bar_w = min(eff, 100)
        bar_color = "#ef4444" if eff < 40 else ("#eab308" if eff < 70 else "#22c55e")
        rank_badge = ["", "#1", "#2", "#3"][rank] if rank <= 3 else f"#{rank}"

        rows += f"""
        <div class="mt-row">
            <div class="mt-rank">{rank_badge}</div>
            <div class="mt-agent">
                <div class="mt-orb" style="background:{color}">{agent_id[:2]}</div>
                <span class="mt-name" style="color:{color}">{agent_id}</span>
            </div>
            <div class="mt-stat"><span class="mt-num">{s['tasks']}</span><span class="mt-lbl">tasks</span></div>
            <div class="mt-stat"><span class="mt-num" style="color:#22c55e">{s['done']}</span><span class="mt-lbl">done</span></div>
            <div class="mt-stat"><span class="mt-num" style="color:#ef4444">{s['blocked']}</span><span class="mt-lbl">blocked</span></div>
            <div class="mt-stat"><span class="mt-num">{sr:.0f}%</span><span class="mt-lbl">rate</span></div>
            <div class="mt-stat"><span class="mt-num">{s['avg_duration_s']:.0f}s</span><span class="mt-lbl">avg</span></div>
            <div class="mt-bar-wrap">
                <div class="mt-bar" style="width:{bar_w}%;background:{bar_color}"></div>
                <span class="mt-score">{eff:.1f}</span>
            </div>
        </div>"""

    total_tasks = sum(s.get("tasks", 0) for s in metrics.values())
    total_done = sum(s.get("done", 0) for s in metrics.values())
    avg_eff = sum(s.get("efficiency", 0) for _, s in active_agents) / max(len(active_agents), 1)

    summary = f"""
    <div class="mt-summary">
        <div class="mt-s"><span class="mt-sv">{total_tasks}</span><span class="mt-sl">total tasks</span></div>
        <div class="mt-s"><span class="mt-sv" style="color:#22c55e">{total_done}</span><span class="mt-sl">completed</span></div>
        <div class="mt-s"><span class="mt-sv">{len(active_agents)}</span><span class="mt-sl">active agents</span></div>
        <div class="mt-s"><span class="mt-sv">{avg_eff:.1f}</span><span class="mt-sl">avg efficiency</span></div>
    </div>"""

    return summary + '<div class="mt-board">' + rows + '</div>'
