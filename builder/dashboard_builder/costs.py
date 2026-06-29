"""COSTS section — subscriptions + token usage."""
from __future__ import annotations

from .keeper import collect_keeper_data
from .fraction import collect_fraction_data
from .config import fmt_tok


def collect_costs_data() -> dict:
    """Collect all cost-related data."""
    keeper = collect_keeper_data()
    fraction = collect_fraction_data()
    usage = fraction.get("usage", {})
    orch = fraction.get("orchestrator", {})

    # Calculate token costs
    token_monthly = 0
    for provider_key in ("claude", "codex"):
        pdata = usage.get(provider_key, {})
        token_monthly += pdata.get("api_equivalent_month", 0)

    return {
        "subs": keeper["subs"],
        "sub_count": keeper["count"],
        "sub_monthly": keeper["total_monthly"],
        "usage": usage,
        "orchestrator": orch,
        "token_monthly": token_monthly,
        "total_monthly": keeper["total_monthly"] + token_monthly,
    }


def build_costs_html(data: dict) -> str:
    """Build the COSTS section HTML."""
    subs = data["subs"]
    usage = data["usage"]
    orch = data.get("orchestrator", {})

    # ── Subscriptions table ──
    sub_rows = ""
    for s in subs:
        days = s.get("_days_until", 999)
        renew_date = s.get("_renew_date")
        renew_label = renew_date.strftime("%b %d") if renew_date else "—"
        renew_cls = "renew-urgent" if days <= 3 else ("renew-soon" if days <= 7 else "renew-normal")
        sub_rows += f"""
        <div class="cost-sub-row">
            <span class="cost-sub-name">{s["name"]}</span>
            <span class="cost-sub-cost">${s.get("cost", 0)}</span>
            <span class="cost-sub-renew {renew_cls}">{renew_label}</span>
        </div>"""

    # ── Token usage cards ──
    token_html = ""
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

        token_html += f"""
        <div class="cost-token-card" style="border-left: 3px solid {color}">
            <div class="cost-token-header">
                <span class="cost-token-name" style="color:{color}">{name}</span>
                <span class="cost-token-plan">{plan}</span>
            </div>
            <div class="cost-token-stats">
                <div class="cost-token-stat">
                    <div class="cost-token-val">{fmt_tok(tokens_month)}</div>
                    <div class="cost-token-lbl">tokens/mo</div>
                </div>
                <div class="cost-token-stat">
                    <div class="cost-token-val">${cost_month:,.0f}</div>
                    <div class="cost-token-lbl">API-eq</div>
                </div>
                <div class="cost-token-stat">
                    <div class="cost-token-val">{savings:.1f}x</div>
                    <div class="cost-token-lbl">savings</div>
                </div>
            </div>
        </div>"""

    # ── Orchestrator mode ──
    orch_html = ""
    mode = orch.get("mode", "")
    if mode:
        budgets = orch.get("budgets", {})
        claude_daily = budgets.get("claude", {}).get("daily", "?")
        codex_daily = budgets.get("codex", {}).get("daily", "?")
        orch_html = f"""
        <div class="cost-orch">
            <span>Mode: <strong>{mode}</strong></span>
            <span>Claude ${claude_daily}/d</span>
            <span>Codex ${codex_daily}/d</span>
        </div>"""

    # ── Total summary ──
    total_html = f"""
    <div class="cost-total">
        <div class="cost-total-item">
            <span class="cost-total-lbl">Subscriptions</span>
            <span class="cost-total-val">${data['sub_monthly']}/mo</span>
        </div>
        <div class="cost-total-item">
            <span class="cost-total-lbl">AI Token Usage</span>
            <span class="cost-total-val">${data['token_monthly']:,.0f}/mo</span>
        </div>
        <div class="cost-total-item cost-total-sum">
            <span class="cost-total-lbl">Total</span>
            <span class="cost-total-val">${data['total_monthly']:,.0f}/mo</span>
        </div>
    </div>"""

    return f"""
    {total_html}
    {orch_html}
    {token_html}
    <details class="cost-subs-details" open>
        <summary class="sys-expand-sum">Subscriptions ({data['sub_count']})</summary>
        <div class="cost-sub-list">{sub_rows}</div>
    </details>"""
