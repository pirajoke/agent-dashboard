"""Canonical Common Center platform registry and safe HTML renderer.

The registry deliberately contains navigation metadata only.  Runtime health,
credentials, deploy controls, and private filesystem details do not belong in
the static dashboard snapshot.
"""
from __future__ import annotations

from html import escape
import re
from urllib.parse import urlsplit


PLATFORM_REGISTRY = (
    {
        "id": "financial-os",
        "name": "JobRadar / Financial OS",
        "description": "Job discovery and the financial operations workspace.",
        "tier": "primary",
        "status": "Private Mac mini + Telegram",
        "actions": (
            {"label": "Open workspace", "url": "http://127.0.0.1:8792", "access": "private"},
            {"label": "Open JobRadar bot", "url": "https://t.me/JobsRadarS_bot", "access": "telegram"},
        ),
    },
    {
        "id": "mydictionary",
        "name": "Lexi",
        "description": "Language-learning administration and the Lexi learner bot.",
        "tier": "primary",
        "status": "Private Mac mini + Telegram",
        "actions": (
            {"label": "Open admin", "url": "http://127.0.0.1:8791/admin", "access": "private"},
            {"label": "Open learner bot", "url": "https://t.me/my_dictionnary_tg_bot", "access": "telegram"},
        ),
    },
    {
        "id": "health-os",
        "name": "Health OS",
        "description": "Stable public destination for the personal health workspace.",
        "tier": "active",
        "status": "Public HTTPS destination",
        "actions": (
            {"label": "Open Health OS", "url": "https://health.meshly.fr/", "access": "public"},
        ),
    },
    {
        "id": "ai-singularity",
        "name": "AI Singularity",
        "description": "Context News web app and admin surface.",
        "tier": "active",
        "status": "Private Mac mini",
        "actions": (
            {"label": "Open workspace", "url": "http://127.0.0.1:8790", "access": "private"},
        ),
    },
    {
        "id": "context-news",
        "name": "Context News France",
        "description": "Personalized news digests delivered in Telegram.",
        "tier": "active",
        "status": "Telegram",
        "actions": (
            {"label": "Open news bot", "url": "https://t.me/contextnews_bot", "access": "telegram"},
        ),
    },
    {
        "id": "accountable-os",
        "name": "Accountable OS",
        "description": "Private accountability and operating-rhythm workspace.",
        "tier": "active",
        "status": "Private Mac mini",
        "actions": (
            {"label": "Open workspace", "url": "http://127.0.0.1:4174", "access": "private"},
        ),
    },
    {
        "id": "jarvis",
        "name": "JARVIS",
        "description": "Telegram-only personal operator and memory interface.",
        "tier": "active",
        "status": "Telegram",
        "actions": (
            {"label": "Open JARVIS", "url": "https://t.me/max_jarvis_hoian_bot", "access": "telegram"},
        ),
    },
)


_PLATFORM_FIELDS = ("id", "name", "description", "tier", "status", "actions")
_ACTION_FIELDS = ("label", "url", "access")
_APPROVED_HTTPS_HOSTS = {"t.me", "health.meshly.fr"}
_APPROVED_ACCESS = {"private", "public", "telegram"}
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")
_SENSITIVE_COPY = re.compile(
    r"(?:/Users/|/home/|/srv/|(?:^|/)\.ssh/|\.env\b|"
    r"\b(?:BOT_TOKEN|API_KEY|PASSWORD)\s*=|\b\d{8,12}:[A-Za-z0-9_-]{30,}\b)",
    re.IGNORECASE,
)


def _require_safe_copy(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TypeError(f"{field} must be a non-empty string")
    if _CONTROL_CHARS.search(value):
        raise ValueError(f"{field} contains control characters")
    if _SENSITIVE_COPY.search(value):
        raise ValueError(f"{field} contains private or credential-shaped content")
    return value


def _validate_url(value: object) -> str:
    url = _require_safe_copy(value, "action.url")
    parsed = urlsplit(url)
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("credential-bearing URLs are not permitted")
    if parsed.query or parsed.fragment:
        raise ValueError("query strings and fragments are not permitted")
    if parsed.scheme == "http":
        if parsed.hostname not in {"127.0.0.1", "localhost"}:
            raise ValueError("HTTP destinations must be loopback-only")
        if parsed.port is None:
            raise ValueError("loopback destinations require an explicit port")
    elif parsed.scheme == "https":
        if parsed.hostname not in _APPROVED_HTTPS_HOSTS:
            raise ValueError("HTTPS destination host is not approved")
        if parsed.port is not None:
            raise ValueError("approved HTTPS destinations use the default port")
    else:
        raise ValueError("only approved HTTP and HTTPS destinations are permitted")
    return url


def validate_platform_registry(registry=PLATFORM_REGISTRY) -> None:
    """Fail closed when navigation metadata violates the Common Center contract."""
    if not isinstance(registry, (tuple, list)) or not registry:
        raise TypeError("registry must be a non-empty tuple or list")

    ids: set[str] = set()
    primary_count = 0
    for index, platform in enumerate(registry):
        if not isinstance(platform, dict):
            raise TypeError(f"platform {index} must be a mapping")
        for field in _PLATFORM_FIELDS:
            if field not in platform:
                raise ValueError(f"platform {index} is missing {field}")

        platform_id = _require_safe_copy(platform["id"], "platform.id")
        if platform_id in ids:
            raise ValueError(f"duplicate platform id: {platform_id}")
        ids.add(platform_id)
        for field in ("name", "description", "status"):
            _require_safe_copy(platform[field], f"platform.{field}")

        tier = _require_safe_copy(platform["tier"], "platform.tier")
        if tier not in {"primary", "active"}:
            raise ValueError("platform.tier must be primary or active")
        primary_count += tier == "primary"

        actions = platform["actions"]
        if not isinstance(actions, (tuple, list)) or not actions:
            raise ValueError(f"platform {platform_id} must expose at least one action")
        for action in actions:
            if not isinstance(action, dict):
                raise TypeError("platform actions must be mappings")
            for field in _ACTION_FIELDS:
                if field not in action:
                    raise ValueError(f"platform action is missing {field}")
            _require_safe_copy(action["label"], "action.label")
            url = _validate_url(action["url"])
            access = _require_safe_copy(action["access"], "action.access")
            if access not in _APPROVED_ACCESS:
                raise ValueError("action.access is not recognised")
            parsed = urlsplit(url)
            expected_access = (
                "private"
                if parsed.scheme == "http"
                else "telegram"
                if parsed.hostname == "t.me"
                else "public"
            )
            if access != expected_access:
                raise ValueError("action.access does not match its destination")

    if primary_count != 2:
        raise ValueError("the registry must contain exactly two primary products")


def build_tunnel_command(registry=PLATFORM_REGISTRY) -> str:
    """Return one reusable tunnel command for every private Common Center port."""
    validate_platform_registry(registry)
    ports = [7777]
    for platform in registry:
        for action in platform["actions"]:
            parsed = urlsplit(action["url"])
            if parsed.scheme == "http" and parsed.port not in ports:
                ports.append(parsed.port)
    forwards = " ".join(f"-L {port}:127.0.0.1:{port}" for port in ports)
    return f"ssh -N {forwards} pirajoke@maxxs-mac-mini"


def _access_label(access: str) -> str:
    return {
        "private": "Private Mac mini",
        "public": "Public HTTPS",
        "telegram": "Telegram",
    }[access]


def _build_actions(actions) -> str:
    return "".join(
        f'''<a class="platform-action platform-action-{escape(action["access"], quote=True)}"
                href="{escape(action["url"], quote=True)}" target="_blank" rel="noopener noreferrer">
                <span>{escape(action["label"])}</span>
                <span class="platform-action-access">{escape(_access_label(action["access"]))}</span>
            </a>'''
        for action in actions
    )


def _build_platform(platform: dict, index: int) -> str:
    tier = escape(platform["tier"], quote=True)
    number = f"{index:02d}" if platform["tier"] == "primary" else "—"
    return f'''<article class="platform-entry platform-entry-{tier}"
            data-platform-id="{escape(platform["id"], quote=True)}"
            data-platform-tier="{tier}">
        <div class="platform-index" aria-hidden="true">{number}</div>
        <div class="platform-copy">
            <p class="platform-status">{escape(platform["status"])}</p>
            <h3>{escape(platform["name"])}</h3>
            <p class="platform-description">{escape(platform["description"])}</p>
        </div>
        <div class="platform-actions">{_build_actions(platform["actions"])}</div>
    </article>'''


def build_platform_hub_html(registry=PLATFORM_REGISTRY) -> str:
    """Render the first, static and read-only Common Center section."""
    validate_platform_registry(registry)
    primary = [platform for platform in registry if platform["tier"] == "primary"]
    active = [platform for platform in registry if platform["tier"] == "active"]
    primary_html = "".join(_build_platform(platform, index) for index, platform in enumerate(primary, 1))
    active_html = "".join(_build_platform(platform, index + 2) for index, platform in enumerate(active, 1))
    tunnel = escape(build_tunnel_command(registry))
    return f'''<section class="platform-hub section" id="common-center" aria-labelledby="common-center-title">
    <header class="platform-hero">
        <div>
            <p class="platform-eyebrow">Portfolio switchboard · 7 surfaces</p>
            <h2 id="common-center-title">Common Center</h2>
        </div>
        <p class="platform-intro">One calm entry point for the products that matter now and the systems that keep them moving.</p>
    </header>

    <div class="platform-group">
        <div class="platform-group-head">
            <h3>Primary products</h3>
            <span>2 current lanes</span>
        </div>
        <div class="platform-primary-grid">{primary_html}</div>
    </div>

    <div class="platform-group platform-group-active">
        <div class="platform-group-head">
            <h3>Active systems</h3>
            <span>5 maintained surfaces</span>
        </div>
        <div class="platform-system-list">{active_html}</div>
    </div>

    <aside class="platform-access" aria-labelledby="secure-access-title">
        <div class="platform-access-copy">
            <p class="platform-eyebrow">Secure access</p>
            <h3 id="secure-access-title">One SSH tunnel for every private Mac mini surface</h3>
            <p>Public HTTPS and Telegram links open directly. Start this tunnel before using links marked Private Mac mini.</p>
        </div>
        <div class="platform-command">
            <span>SSH tunnel</span>
            <code id="common-center-tunnel">{tunnel}</code>
            <button class="platform-action platform-copy-action" type="button"
                    data-copy="#common-center-tunnel" aria-label="Copy SSH tunnel command"
                    aria-live="polite" aria-atomic="true">Copy</button>
        </div>
    </aside>
</section>'''


validate_platform_registry()
