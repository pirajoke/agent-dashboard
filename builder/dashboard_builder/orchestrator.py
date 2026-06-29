"""Orchestrator section — mode, budgets, subscriptions."""
from __future__ import annotations

import json
from datetime import datetime

from .config import ORCH_FILE, LEDGER_FILE, USAGE_FILE, fmt_tok, fmt_hours, limit_bar_color


def _load_orchestrator() -> dict:
    if not ORCH_FILE.exists():
        return {"mode": "claude-codex", "budgets": {}, "agents": {}}
    return json.loads(ORCH_FILE.read_text(encoding="utf-8"))


def _load_usage() -> dict:
    if not USAGE_FILE.exists():
        return {}
    return json.loads(USAGE_FILE.read_text(encoding="utf-8"))


def _load_token_stats() -> dict:
    today = datetime.utcnow().strftime("%Y-%m-%d")
    month = datetime.utcnow().strftime("%Y-%m")
    empty = {"cost": 0, "in": 0, "out": 0, "reqs": 0}
    stats = {}
    for agent in ("claude", "codex"):
        stats[agent] = {"today": dict(empty), "month": dict(empty), "all": dict(empty)}
    if not LEDGER_FILE.exists():
        return stats
    text = LEDGER_FILE.read_text(encoding="utf-8").strip()
    if not text:
        return stats
    for line in text.splitlines():
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        a = r.get("agent", "")
        if a not in stats:
            continue
        inp = r.get("input_tokens", 0)
        out = r.get("output_tokens", 0)
        cost = r.get("cost_usd", 0)
        stats[a]["all"]["cost"] += cost
        stats[a]["all"]["in"] += inp
        stats[a]["all"]["out"] += out
        stats[a]["all"]["reqs"] += 1
        if r.get("date") == today:
            stats[a]["today"]["cost"] += cost
            stats[a]["today"]["in"] += inp
            stats[a]["today"]["out"] += out
            stats[a]["today"]["reqs"] += 1
        if r.get("month") == month:
            stats[a]["month"]["cost"] += cost
            stats[a]["month"]["in"] += inp
            stats[a]["month"]["out"] += out
            stats[a]["month"]["reqs"] += 1
    return stats


def build_orchestrator_html() -> str:
    orch = _load_orchestrator()
    mode = orch.get("mode", "claude-codex")
    tokens = _load_token_stats()
    usage = _load_usage()
    reason = orch.get("changed_reason", "—")
    changed = orch.get("changed_at", "—")[:16].replace("T", " ")
    paused = orch.get("paused", False)

    # Mode slider
    modes = [("claude-claude", "CC", "Claude + Claude"),
             ("claude-codex", "CX", "Claude + Codex"),
             ("codex-codex", "XX", "Codex + Codex")]
    slider_items = ""
    for m, label, desc in modes:
        active = "oslider-active" if m == mode else ""
        slider_items += f'<div class="oslider-item {active}" data-mode="{m}" title="{desc}" style="cursor:pointer">{label}</div>'

    active_desc = next((d for m, l, d in modes if m == mode), mode)

    # Per-agent model selectors
    agent_models = orch.get("agent_models", {})
    agent_model_defs = [
        ("executor", "Executor", "Claude autonomous executor", [("opus", "OP"), ("sonnet", "SN"), ("haiku", "HK")]),
        ("responder", "Responder", "Claude Linear responder", [("opus", "OP"), ("sonnet", "SN"), ("haiku", "HK")]),
        ("codex", "Background", "Low-cost OpenAI background worker", [("gpt-5.4", "5.4"), ("gpt-5.4-mini", "mini"), ("gpt-5.4-nano", "nano")]),
    ]
    agent_model_cards = ""
    for agent_id, agent_name, agent_desc, model_opts in agent_model_defs:
        cur = agent_models.get(agent_id, model_opts[0][0])
        if agent_id == "codex":
            cur = {
                "gpt-4.1": "gpt-5.4",
                "gpt-4.1-mini": "gpt-5.4-mini",
                "o3": "gpt-5.4-mini",
            }.get(cur, cur)
        items = ""
        for mid, mlabel in model_opts:
            act = "oslider-active" if mid == cur else ""
            items += f'<div class="oslider-item agent-model-item {act}" data-agent="{agent_id}" data-model="{mid}" style="cursor:pointer">{mlabel}</div>'
        agent_model_cards += f"""
        <div class="agent-model-card">
            <div class="agent-model-name">{agent_name}</div>
            <div class="oslider agent-model-slider" data-agent="{agent_id}">{items}</div>
            <div class="agent-model-current">{cur}</div>
        </div>"""

    # Subscription info
    subs = [
        {
            "name": "Claude Code",
            "icon": "C",
            "plan": "Max",
            "cost": "$200/mo",
            "model": "Opus 4.6",
            "key": "claude",
            "color": "#ff6b35",
            "features": ["CLI + IDE", "Agent tool", "MCP servers", "Hooks", "Unlimited Sonnet"],
            "unit": "msgs",
        },
        {
            "name": "Codex (OpenAI)",
            "icon": "X",
            "plan": "Plus",
            "cost": "$20/mo",
            "model": "GPT-5.4 mini",
            "key": "codex",
            "color": "#3fb950",
            "features": ["Responses API", "Low-cost worker", "Git integration", "Prompt caching", "Background exec"],
            "unit": "sessions",
        },
    ]

    agent_cards = ""
    for s in subs:
        u = usage.get(s["key"], {})
        features_html = "".join(f'<span class="osub-feat">{f}</span>' for f in s["features"])

        real_updated = u.get("updated_at", "")[:16].replace("T", " ") if u.get("updated_at") else ""
        cost_mo = u.get("cost_monthly", 200)
        api_month = u.get("api_cost_month", 0)
        tok_month = u.get("tokens_month", 0)
        msgs_month = u.get("msgs_month", 0)
        msgs_today = u.get("msgs_today", 0)
        active_days = u.get("active_days", 0)
        savings = u.get("savings_multiplier", 0)

        billing_start = u.get("billing_start", "?")
        billing_renews = u.get("billing_renews", "?")
        cycle_day = u.get("cycle_day", 0)
        cycle_total = u.get("cycle_total", 30)
        days_remaining = u.get("days_remaining", 0)
        cycle_pct = cycle_day / cycle_total * 100 if cycle_total > 0 else 0

        daily_limit = u.get("daily_limit", 45 if s["key"] == "claude" else 0)
        daily_used = u.get("daily_used", msgs_today)
        daily_pct = u.get("daily_pct", 0)
        hours_reset = u.get("hours_until_reset", 0)

        if msgs_month > 0 or tok_month > 0:
            status_badge = '<span class="obadge obadge-green">ACTIVE</span>'
        else:
            status_badge = '<span class="obadge obadge-dim">IDLE</span>'

        billing_section = f"""
            <div class="osub-billing-cycle">
                <div class="osub-billing-label">BILLING CYCLE &middot; {billing_start} &rarr; {billing_renews}</div>
                <div class="osub-limit-bar">
                    <div class="osub-limit-bar-fill" style="width:{min(cycle_pct, 100):.0f}%;background:{s['color']}"></div>
                </div>
                <div class="osub-billing-info">Day {cycle_day}/{cycle_total} &middot; {days_remaining} days left &middot; ${cost_mo}/mo flat</div>
            </div>"""

        if daily_limit > 0:
            bar_color = limit_bar_color(daily_pct)
            bar_pct = min(daily_pct, 100)
            rate_section = f"""
            <div class="osub-limit-primary">
                <div class="osub-limit-bar-wrap">
                    <div class="osub-limit-bar">
                        <div class="osub-limit-bar-fill" style="width:{bar_pct:.0f}%;background:{bar_color}"></div>
                    </div>
                    <div class="osub-limit-count">{daily_used} / ~{daily_limit} {s['unit']}/day <span class="osub-rate-tag">rate limit</span></div>
                </div>
                <div class="osub-limit-reset">Resets in {fmt_hours(hours_reset)}</div>
            </div>"""
        else:
            rate_section = f"""
            <div class="osub-limit-primary">
                <div class="osub-limit-bar-wrap">
                    <div class="osub-limit-bar osub-limit-unlimited">
                        <div class="osub-limit-bar-fill" style="width:100%;background:{s['color']};opacity:0.3"></div>
                    </div>
                    <div class="osub-limit-count">unlimited &middot; {daily_used} {s['unit']} today</div>
                </div>
            </div>"""

        month_section = f"""
            <div class="osub-month-summary">
                <span class="osub-month-label">This Cycle</span>
                <span class="osub-month-stats">{fmt_tok(tok_month)} tokens &middot; {msgs_month:,} {s['unit']} &middot; {active_days} days active</span>
                <span class="osub-month-savings">${api_month:,.0f} API-eq &rarr; <strong>{savings:.0f}x ROI</strong></span>
            </div>"""

        agent_cards += f"""
        <div class="osub osub-full">
            <div class="osub-head">
                <div class="osub-icon" style="background:{s['color']}">{s['icon']}</div>
                <div class="osub-title">
                    <span class="osub-name" style="color:{s['color']}">{s['name']}</span>
                    <span class="osub-model-tag">{s['model']}</span>
                </div>
                <div class="osub-right">
                    {status_badge}
                    <span class="osub-plan">{s['plan']} {s['cost']}</span>
                </div>
            </div>
            {billing_section}
            {rate_section}
            {month_section}
            <div class="osub-features">{features_html}</div>
            <div class="osub-real-updated">auto-synced {real_updated}</div>
        </div>"""

    # Combined card
    total_tok_month = sum(usage.get(a, {}).get("tokens_month", 0) for a in ("claude", "codex"))
    total_api_month = sum(usage.get(a, {}).get("api_cost_month", 0) for a in ("claude", "codex"))
    total_sub = 220

    cl = usage.get("claude", {})
    cl_cycle_pct = cl.get("cycle_day", 0) / cl.get("cycle_total", 30) * 100 if cl.get("cycle_total", 30) > 0 else 0
    cl_days_left = cl.get("days_remaining", 0)

    cx = usage.get("codex", {})
    cx_cycle_pct = cx.get("cycle_day", 0) / cx.get("cycle_total", 30) * 100 if cx.get("cycle_total", 30) > 0 else 0
    cx_days_left = cx.get("days_remaining", 0)

    savings_x = f"{total_api_month/total_sub:.0f}x" if total_sub > 0 and total_api_month > 0 else "—"

    paused_status = "PAUSED" if paused else "RUNNING"

    return f"""
    <div class="orch-master-toggle">
        <span class="orch-master-label">Orchestrator</span>
        <span class="orch-master-status {'orch-status-off' if paused else 'orch-status-on'}">{paused_status}</span>
        <label class="toggle-switch" id="orchToggle">
            <input type="checkbox" {'checked' if not paused else ''} id="orchToggleInput">
            <span class="toggle-slider"></span>
        </label>
    </div>
    <div class="orch-grid {'orch-disabled' if paused else ''}">
        <div class="orch-card">
            <div class="orch-label">MODE</div>
            <div class="oslider">{slider_items}</div>
            <div class="orch-desc">{active_desc}</div>
            <div class="orch-meta">Changed: {changed} | {reason}</div>
            <button class="launch-btn" id="launchBtn" onclick="event.preventDefault();launchAgents();return false;" type="button">Launch Agents</button>
        </div>
        <div class="orch-card">
            <div class="orch-label">MODELS</div>
            <div class="agent-models-grid">{agent_model_cards}</div>
        </div>
        <div class="orch-card orch-budget">
            <div class="orch-label">COMBINED <span class="orch-combined-cost">${total_sub}/mo flat</span></div>
            <div class="orch-combined-limits">
                <div class="orch-combined-row">
                    <span class="orch-combined-agent" style="color:#ff6b35">Claude</span>
                    <div class="orch-combined-bar"><div class="orch-combined-bar-fill" style="width:{min(cl_cycle_pct, 100):.0f}%;background:#ff6b35"></div></div>
                    <span class="orch-combined-count">{cl_days_left}d left &middot; renews {cl.get('billing_renews', '?')}</span>
                </div>
                <div class="orch-combined-row">
                    <span class="orch-combined-agent" style="color:#3fb950">Codex</span>
                    <div class="orch-combined-bar"><div class="orch-combined-bar-fill" style="width:{min(cx_cycle_pct, 100):.0f}%;background:#3fb950"></div></div>
                    <span class="orch-combined-count">{cx_days_left}d left &middot; renews {cx.get('billing_renews', '?')}</span>
                </div>
            </div>
            <div class="orch-combined-footer">{fmt_tok(total_tok_month)} tokens &middot; ${total_api_month:,.0f} API-eq &middot; {savings_x} ROI</div>
        </div>
    </div>
    <div class="orch-agents-detail">
        {agent_cards}
    </div>"""
