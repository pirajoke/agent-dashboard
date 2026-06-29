"""CodexBar provider usage — loading and HTML rendering."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from .config import CODEXBAR_SNAPSHOT, CODEXBAR_PROVIDERS, CODEXBAR_BAR_LABELS


def _load_codexbar() -> list[dict]:
    try:
        with open(CODEXBAR_SNAPSHOT) as f:
            return json.load(f).get("entries", [])
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _time_left(resets_at: str) -> str:
    try:
        reset = datetime.fromisoformat(resets_at.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        delta = reset - now
        if delta.total_seconds() <= 0:
            return "now"
        total_min = int(delta.total_seconds() / 60)
        if total_min < 60:
            return f"{total_min}m"
        hours = total_min // 60
        mins = total_min % 60
        if hours < 24:
            return f"{hours}h {mins}m" if mins else f"{hours}h"
        days = hours // 24
        rem_h = hours % 24
        return f"{days}d {rem_h}h" if rem_h else f"{days}d"
    except (ValueError, TypeError):
        return "?"


def _bar_color(used_pct: float) -> str:
    if used_pct > 90:
        return "var(--red)"
    if used_pct > 70:
        return "var(--accent)"
    if used_pct > 40:
        return "var(--yellow)"
    return "var(--green)"


def _render_bar(label: str, tier: dict | None, color: str) -> str:
    if not tier:
        return ""
    used = tier.get("usedPercent", 0)
    left = max(100 - used, 0)
    resets = _time_left(tier.get("resetsAt", ""))
    bar_color = _bar_color(used)
    overflow = "cbar-overflow" if used > 100 else ""
    fill_w = min(used, 100)
    return f'''<div class="cbar-bar-row">
        <div class="cbar-bar-meta">
            <span class="cbar-bar-label">{label}</span>
            <span class="cbar-bar-pct" style="color:{bar_color}">{left:.0f}% left</span>
        </div>
        <div class="cbar-bar {overflow}">
            <div class="cbar-bar-fill" style="width:{fill_w:.1f}%;background:{bar_color}"></div>
        </div>
        <div class="cbar-bar-reset">resets in {resets}</div>
    </div>'''


def build_codexbar_html() -> str:
    entries = _load_codexbar()
    if not entries:
        return '<div class="cbar-empty">No CodexBar data available</div>'

    cards = []
    for entry in entries:
        pid = entry.get("provider", "")
        meta = CODEXBAR_PROVIDERS.get(pid)
        if not meta:
            continue

        color = meta["color"]
        labels = CODEXBAR_BAR_LABELS.get(pid, ["Primary", "Secondary", "Tertiary"])

        updated = entry.get("updatedAt", "")
        try:
            upd_dt = datetime.fromisoformat(updated.replace("Z", "+00:00"))
            upd_str = upd_dt.strftime("%H:%M")
        except (ValueError, TypeError):
            upd_str = "?"

        bars_html = ""
        for i, tier_key in enumerate(["primary", "secondary", "tertiary"]):
            tier = entry.get(tier_key)
            if tier and i < len(labels):
                bars_html += _render_bar(labels[i], tier, color)

        tok = entry.get("tokenUsage", {})
        session_tok = tok.get("sessionTokens", 0)
        cost_30d = tok.get("last30DaysCostUSD", 0)
        footer = ""
        if session_tok or cost_30d:
            def _fmt_t(n):
                if n >= 1_000_000:
                    return f"{n / 1_000_000:.1f}M"
                if n >= 1_000:
                    return f"{n / 1_000:.0f}K"
                return str(n)
            footer = f'''<div class="cbar-footer">
                <span>{_fmt_t(session_tok)} session tok</span>
                <span>${cost_30d:,.0f} / 30d</span>
            </div>'''

        plan_badge = f'<span class="cbar-plan">{meta["plan"]}</span>' if meta["plan"] else ""

        cards.append(f'''<div class="cbar-card">
            <div class="cbar-head">
                <div class="cbar-icon" style="background:{color}">{meta["icon"]}</div>
                <div class="cbar-title">{meta["name"]}</div>
                {plan_badge}
                <div class="cbar-updated">{upd_str}</div>
            </div>
            <div class="cbar-bars">{bars_html}</div>
            {footer}
        </div>''')

    return f'<div class="cbar-grid">{"".join(cards)}</div>'
