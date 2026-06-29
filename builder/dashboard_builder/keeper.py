"""Keeper — Subscription Tracker."""
from __future__ import annotations

import json
from datetime import datetime, date
from pathlib import Path

SUBS_FILE = Path.home() / ".agent-bridge" / "subscriptions.json"


def collect_keeper_data() -> dict:
    """Load subscriptions data."""
    subs = []
    if SUBS_FILE.exists():
        try:
            subs = json.loads(SUBS_FILE.read_text())
        except Exception:
            pass

    total_monthly = sum(s.get("cost", 0) for s in subs)

    # Auto-advance expired renewal dates
    today = date.today()
    for s in subs:
        renew_str = s.get("renews", "")
        if renew_str:
            try:
                renew_date = datetime.strptime(renew_str, "%Y-%m-%d").date()
                while renew_date < today:
                    if s.get("cycle", "monthly") == "monthly":
                        month = renew_date.month + 1
                        year = renew_date.year
                        if month > 12:
                            month = 1
                            year += 1
                        renew_date = renew_date.replace(year=year, month=month)
                    else:
                        renew_date = renew_date.replace(year=renew_date.year + 1)
                s["_renew_date"] = renew_date
                s["_days_until"] = (renew_date - today).days
            except Exception:
                s["_renew_date"] = None
                s["_days_until"] = 999

    return {"subs": subs, "total_monthly": total_monthly, "count": len(subs)}


def build_keeper_html(data: dict) -> str:
    """Build Keeper section HTML."""
    subs = data["subs"]
    total = data["total_monthly"]

    rows = ""
    for s in subs:
        days = s.get("_days_until", 999)
        renew_date = s.get("_renew_date")
        renew_label = renew_date.strftime("%b %d") if renew_date else "—"

        if days <= 3:
            renew_cls = "renew-urgent"
        elif days <= 7:
            renew_cls = "renew-soon"
        else:
            renew_cls = "renew-normal"

        rows += f"""
        <div class="sub-row">
            <span class="sub-name">{s["name"]}</span>
            <span class="sub-cost">${s.get("cost", 0)}</span>
            <span class="{renew_cls}">{renew_label}</span>
        </div>"""

    return f"""
    <div class="keeper-header">
        <div class="avatar" style="background:#2a2a1a"><span class="avatar-emoji">&#x1F4B3;</span></div>
        <div class="keeper-info">
            <div class="keeper-name">Keeper <span class="keeper-role">Subscription Tracker</span></div>
            <div class="keeper-status">{data["count"]} subscriptions &middot; ${total}/mo</div>
        </div>
    </div>
    <div class="sub-list">{rows}</div>
    <div class="sub-footer">Edit: ~/.agent-bridge/subscriptions.json</div>
    """
