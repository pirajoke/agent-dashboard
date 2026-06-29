"""Agent communications bus — read and render chat-style HTML."""
from __future__ import annotations

import json

from .config import COMMS_FILE, AGENT_COLORS, MSG_TYPE_ICONS


def read_comms(n: int = 50) -> list[dict]:
    if not COMMS_FILE.exists():
        return []
    lines = COMMS_FILE.read_text(encoding="utf-8").strip().splitlines()
    recent = lines[-n:] if len(lines) > n else lines
    msgs = []
    for line in recent:
        try:
            msgs.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return msgs


def build_comms_html(comms: list[dict], limit: int = 25) -> str:
    if not comms:
        return '<div class="chat-empty">No communications recorded yet.</div>'

    recent = comms[-limit:] if len(comms) > limit else comms
    recent_display = list(reversed(recent))

    html = ""
    prev_sender = None
    for m in recent_display:
        from_id = m.get("from", "?")
        to_id = m.get("to", "?")
        msg_type = m.get("type", "?")
        from_color = AGENT_COLORS.get(from_id, "#8b949e")
        to_color = AGENT_COLORS.get(to_id, "#8b949e")
        type_label, type_color, type_icon = MSG_TYPE_ICONS.get(msg_type, ("?", "#8b949e", ""))
        ts = m.get("ts", "")
        ts_short = ts[11:16] if len(ts) >= 16 else ts
        ts_date = ts[:10] if len(ts) >= 10 else ""
        body = m.get("body", "")
        if len(body) > 300:
            body = body[:297] + "..."
        task = m.get("task_id", "")
        project = m.get("project", "")

        is_grouped = (from_id == prev_sender)
        prev_sender = from_id

        tags = ""
        if task:
            tags += f'<span class="chat-chip" style="--chip-color:#60a5fa">{task}</span>'
        if project:
            tags += f'<span class="chat-chip" style="--chip-color:{from_color}">{project}</span>'

        if is_grouped:
            html += f"""
            <div class="chat-msg chat-grouped">
                <div class="chat-avatar-space"></div>
                <div class="chat-content">
                    <div class="chat-bubble" style="--bubble-accent:{from_color}">
                        <div class="chat-body">{body}</div>
                        {f'<div class="chat-chips">{tags}</div>' if tags else ''}
                    </div>
                </div>
            </div>"""
        else:
            html += f"""
            <div class="chat-msg">
                <div class="chat-avatar" style="background:{from_color}">{from_id[:2]}</div>
                <div class="chat-content">
                    <div class="chat-meta">
                        <span class="chat-sender" style="color:{from_color}">{from_id}</span>
                        <svg class="chat-arrow" viewBox="0 0 16 16" width="12" height="12"><path d="M1 8h12m-4-4l4 4-4 4" stroke="{to_color}" stroke-width="1.5" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg>
                        <span class="chat-receiver" style="color:{to_color}">{to_id}</span>
                        <span class="chat-type-badge" style="background:{type_color}18;color:{type_color};border-color:{type_color}30">{type_icon} {type_label}</span>
                        <span class="chat-time">{ts_date} {ts_short}</span>
                    </div>
                    <div class="chat-bubble" style="--bubble-accent:{from_color}">
                        <div class="chat-body">{body}</div>
                        {f'<div class="chat-chips">{tags}</div>' if tags else ''}
                    </div>
                </div>
            </div>"""

    return html
