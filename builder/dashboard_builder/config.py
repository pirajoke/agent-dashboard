"""Shared constants, paths, agent definitions, and SVG avatars."""
from __future__ import annotations

from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────
VAULT = Path.home() / "ObsidianVault"
PROJECTS_DIR = VAULT / "20-Projects"
LUMUS_FILE = VAULT / "LUMUS-CONTEXT.md"
COMMS_FILE = Path.home() / ".agent-bridge" / "comms.jsonl"
HTML_OUT = Path.home() / "agent-dashboard.html"
ASSETS_DIR = Path(__file__).resolve().parent.parent / "dashboard-assets"
LIVE_FEED_FILE = Path.home() / "scripts" / "live-feed.json"
EVENTS_FILE = Path.home() / ".agent-bridge" / "events.jsonl"
HEALTH_DIR = Path.home() / ".agent-bridge" / "health"
ORCH_FILE = Path.home() / ".agent-bridge" / "orchestrator.json"
LEDGER_FILE = Path.home() / ".agent-bridge" / "token_ledger.jsonl"
USAGE_FILE = Path.home() / ".agent-bridge" / "usage_snapshots.json"
CODEXBAR_SNAPSHOT = Path.home() / "Library/Group Containers/group.com.steipete.codexbar/widget-snapshot.json"
METRICS_CSV = Path.home() / ".agent-bridge" / "daily-metrics.csv"

# ── Agent definitions (consolidated 10 → 5) ──────────────────────
AGENTS = [
    {"id": "RESEARCHER", "name": "Researcher", "zone": "Deep search, synthesis, content, editing",
     "projects": ["AI-SINGULARITY-CHANNEL", "INSTANT PRESENTATION", "MY-DICTIONARY", "STOCK-CONTENT-BOT"],
     "merged": ["EDITOR"]},
    {"id": "COORDINATOR", "name": "Coordinator", "zone": "Task flow, delegation, planning, comms, bridge",
     "projects": ["AGENT-MEMORY", "LINEAR", "AGENTS-MD", "SECOND-BRAIN", "MESHLY", "MAXIM-SITE"],
     "merged": ["PLANNER", "COMMS", "BRIDGE"]},
    {"id": "ANALYST", "name": "Analyst", "zone": "Data → structured insights",
     "projects": ["FASTDATA-VOICE-AGENT", "HEALTH"],
     "merged": []},
    {"id": "VAULT", "name": "Vault Keeper", "zone": "Obsidian routing, hygiene, Tech-Base",
     "projects": ["MY-OBSIDIAN", "SKILLS"],
     "merged": []},
    {"id": "BUILDER", "name": "Builder", "zone": "Code, features, MVP, deploy, infra",
     "projects": ["FASTDATA-VOICE-AGENT", "MAXIM-SITE", "MESHLY", "STOCK-CONTENT-BOT", "RELOCATION-TO-M4", "MY-OBSIDIAN"],
     "merged": ["DEVOPS"]},
]

# Legacy agent ID mapping for metrics compatibility (old → new)
AGENT_LEGACY_MAP = {
    "EDITOR": "RESEARCHER",
    "PLANNER": "COORDINATOR",
    "COMMS": "COORDINATOR",
    "BRIDGE": "COORDINATOR",
    "DEVOPS": "BUILDER",
}

AGENT_COLORS = {
    "RESEARCHER": "#ff6b35",
    "COORDINATOR": "#58a6ff",
    "ANALYST": "#3fb950",
    "VAULT": "#79c0ff",
    "BUILDER": "#ffa657",
}

# ── Delegation chains ─────────────────────────────────────────────
CHAINS = [
    ("COORDINATOR", "RESEARCHER"),
    ("COORDINATOR", "ANALYST"),
    ("COORDINATOR", "VAULT"),
    ("ANALYST", "BUILDER"),
    ("VAULT", "COORDINATOR"),
]

# ── SVG avatars (inline, 56x56) ──────────────────────────────────
_S = 56
_R = 26
_C = 28


def _wrap(inner: str, bg: str = "#1e1e2e") -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{_S}" height="{_S}" viewBox="0 0 {_S} {_S}" fill="none">'
        f'<circle cx="{_C}" cy="{_C}" r="{_R}" fill="{bg}"/>'
        f'{inner}</svg>'
    )


AVATARS = {
    "RESEARCHER": _wrap(
        '<circle cx="25" cy="24" r="8" stroke="#ff6b35" stroke-width="2.2" fill="none"/>'
        '<line x1="31" y1="30" x2="38" y2="37" stroke="#ff6b35" stroke-width="2.5" stroke-linecap="round"/>'
        '<circle cx="25" cy="24" r="3" fill="#ff6b35" opacity="0.3"/>'
    ),
    "COORDINATOR": _wrap(
        '<circle cx="28" cy="28" r="5" fill="#ff6b35" opacity="0.3" stroke="#ff6b35" stroke-width="2"/>'
        '<circle cx="16" cy="18" r="3" stroke="#ff6b35" stroke-width="1.8" fill="none"/>'
        '<circle cx="40" cy="18" r="3" stroke="#ff6b35" stroke-width="1.8" fill="none"/>'
        '<circle cx="16" cy="38" r="3" stroke="#ff6b35" stroke-width="1.8" fill="none"/>'
        '<circle cx="40" cy="38" r="3" stroke="#ff6b35" stroke-width="1.8" fill="none"/>'
        '<line x1="24" y1="25" x2="18" y2="20" stroke="#ff6b35" stroke-width="1.5" opacity="0.6"/>'
        '<line x1="32" y1="25" x2="38" y2="20" stroke="#ff6b35" stroke-width="1.5" opacity="0.6"/>'
        '<line x1="24" y1="31" x2="18" y2="36" stroke="#ff6b35" stroke-width="1.5" opacity="0.6"/>'
        '<line x1="32" y1="31" x2="38" y2="36" stroke="#ff6b35" stroke-width="1.5" opacity="0.6"/>'
    ),
    "ANALYST": _wrap(
        '<rect x="16" y="30" width="5" height="8" rx="1" fill="#ff6b35" opacity="0.5"/>'
        '<rect x="23" y="24" width="5" height="14" rx="1" fill="#ff6b35" opacity="0.7"/>'
        '<rect x="30" y="18" width="5" height="20" rx="1" fill="#ff6b35"/>'
        '<rect x="37" y="26" width="5" height="12" rx="1" fill="#ff6b35" opacity="0.6"/>'
        '<line x1="14" y1="39" x2="44" y2="39" stroke="#ff6b35" stroke-width="1.5" opacity="0.4"/>'
    ),
    "VAULT": _wrap(
        '<path d="M28 15L17 20V28C17 34 21.5 39.5 28 41C34.5 39.5 39 34 39 28V20Z" '
        'stroke="#ff6b35" stroke-width="2" fill="none"/>'
        '<path d="M28 15L17 20V28C17 34 21.5 39.5 28 41C34.5 39.5 39 34 39 28V20Z" '
        'fill="#ff6b35" opacity="0.1"/>'
        '<rect x="24" y="26" width="8" height="7" rx="1.5" stroke="#ff6b35" stroke-width="1.8" fill="none"/>'
        '<path d="M25.5 26V23.5C25.5 22.1 26.6 21 28 21C29.4 21 30.5 22.1 30.5 23.5V26" '
        'stroke="#ff6b35" stroke-width="1.8" fill="none"/>'
        '<circle cx="28" cy="29.5" r="1.2" fill="#ff6b35"/>'
    ),
    "BUILDER": _wrap(
        '<path d="M34 18L22 30" stroke="#ff6b35" stroke-width="2.5" stroke-linecap="round"/>'
        '<path d="M36 16C37.5 14.5 40 14.5 41 16C42 17.5 41.5 19.5 40 21L37 18Z" fill="#ff6b35" opacity="0.5"/>'
        '<path d="M20 32L16 40L18 42L24 36Z" fill="#ff6b35" opacity="0.7"/>'
        '<path d="M20 32L16 40L18 42L24 36Z" stroke="#ff6b35" stroke-width="1.5" stroke-linejoin="round" fill="none"/>'
    ),
}

# ── Message type icons for comms ──────────────────────────────────
MSG_TYPE_ICONS = {
    "dispatch": ("DISPATCH", "#3fb950", "&#9654;"),
    "report":   ("REPORT",   "#58a6ff", "&#9632;"),
    "blocked":  ("BLOCKED",  "#f85149", "&#9888;"),
    "ack":      ("ACK",      "#8b949e", "&#10003;"),
    "question": ("QUESTION", "#d29922", "&#63;"),
    "answer":   ("ANSWER",   "#bc8cff", "&#10140;"),
}

# ── Platform capabilities ─────────────────────────────────────────
PLATFORM_CAPABILITIES = [
    {"name": "Smart Routing", "file": "agent_router.py",
     "desc": "Dynamic task-to-agent matching based on skills and load",
     "icon": '<path d="M3 12h4l3-9 4 18 3-9h4" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"/>'},
    {"name": "Circuit Breaker", "file": "agent_dispatch.py",
     "desc": "Auto-disable failing agents, prevent cascade failures",
     "icon": '<circle cx="12" cy="12" r="9" stroke="currentColor" stroke-width="2" fill="none"/><path d="M12 8v4l3 3" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>'},
    {"name": "Performance Metrics", "file": "agent_metrics.py",
     "desc": "Track efficiency, success rate, and throughput per agent",
     "icon": '<rect x="3" y="12" width="4" height="9" rx="1" stroke="currentColor" stroke-width="1.5" fill="none"/><rect x="10" y="6" width="4" height="15" rx="1" stroke="currentColor" stroke-width="1.5" fill="none"/><rect x="17" y="3" width="4" height="18" rx="1" stroke="currentColor" stroke-width="1.5" fill="none"/>'},
    {"name": "Auto-Retrospective", "file": "agent_retro.py",
     "desc": "Generate weekly insights and improvement suggestions",
     "icon": '<path d="M12 3v3m0 12v3m-9-9h3m12 0h3m-4.2-7.8l-2.1 2.1m-5.4 5.4l-2.1 2.1m0-9.6l2.1 2.1m5.4 5.4l2.1 2.1" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>'},
    {"name": "Comms Bus", "file": "agent_comms.py",
     "desc": "Structured agent-to-agent messaging with typed channels",
     "icon": '<path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z" stroke="currentColor" stroke-width="2" fill="none"/>'},
    {"name": "Linear Sync", "file": "autopilot",
     "desc": "Auto-detect and respond to Linear issue assignments",
     "icon": '<path d="M4 4h16v16H4z" stroke="currentColor" stroke-width="2" fill="none" rx="2"/><path d="M9 12l2 2 4-4" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>'},
]

# ── CodexBar provider config ─────────────────────────────────────
CODEXBAR_PROVIDERS = {
    "codex":       {"name": "Codex",       "icon": "X",  "color": "#3fb950", "plan": "Plus $20/mo"},
    "claude":      {"name": "Claude",      "icon": "C",  "color": "#ff6b35", "plan": "Max $200/mo"},
    "cursor":      {"name": "Cursor",      "icon": "Cu", "color": "#06b6d4", "plan": "Pro Plus"},
    "antigravity": {"name": "Antigravity", "icon": "A",  "color": "#a855f7", "plan": ""},
    "openrouter":  {"name": "OpenRouter",  "icon": "OR", "color": "#ec4899", "plan": "Credits"},
}

CODEXBAR_BAR_LABELS = {
    "codex":  ["Session", "Weekly"],
    "claude": ["Session", "Weekly", "Sonnet"],
    "cursor": ["Total", "Auto", "API"],
}


# ── Formatting helpers ────────────────────────────────────────────

def fmt_tok(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


def fmt_hours(h: float) -> str:
    hrs = int(h)
    mins = int((h - hrs) * 60)
    if hrs > 0:
        return f"{hrs}h {mins:02d}m"
    return f"{mins}m"


def limit_bar_color(pct: float) -> str:
    if pct >= 90:
        return "#ef4444"
    if pct >= 70:
        return "#eab308"
    return "#22c55e"
