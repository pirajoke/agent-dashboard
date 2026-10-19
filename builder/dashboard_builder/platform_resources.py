"""Bounded owner-only navigation projection from the canonical portfolio registry.

No private registry contents are read for an anonymous caller. This module
returns only navigation metadata, never the underlying project or owner records.
"""
from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import unicodedata
from urllib.parse import unquote, urlsplit

MAX_BYTES = 1024 * 1024
PLATFORM_IDS = frozenset(("financial", "mydictionary", "health", "ai-singularity", "context-news",
                         "accountable", "jarvis", "property-os", "pixel-agents", "closeness-mirror",
                         "sushi-parisien", "n8n"))
KINDS = frozenset(("documents", "notes", "code", "tasks"))
SCOPES = frozenset(("current", "archive", "upstream", "reference"))
HOSTS = frozenset(("github.com", "drive.google.com"))


def _text(value: object, limit: int) -> bool:
    return (isinstance(value, str) and 0 < len(value) <= limit and bool(value.strip())
            and not any(unicodedata.category(c).startswith("C") for c in value))


def _url(value: object) -> bool:
    if not _text(value, 2048) or value != value.strip():
        return False
    # Reject raw delimiters even if their query/fragment is empty. Decoding is
    # solely a validation pass; the original URL is what the owner sees.
    if any(c.isspace() for c in value) or any(c in value for c in "? #\\"):
        return False
    decoded = value
    for _ in range(3):
        decoded = unquote(decoded)
        if "\\" in decoded or any(unicodedata.category(c).startswith("C") for c in decoded):
            return False
    try:
        parsed = urlsplit(value)
        return (parsed.scheme == "https" and parsed.netloc.lower() in HOSTS
                and parsed.hostname in HOSTS and parsed.username is None
                and parsed.password is None and parsed.port is None)
    except ValueError:
        return False


def _empty(state: str) -> dict:
    return {"state": state, "verified_at": None, "platforms": {}}


def platform_resources_projection(path: Path, owner: bool = False) -> dict:
    if not owner:
        return _empty("owner_required")
    try:
        with Path(path).open("rb") as stream:
            raw = stream.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            return _empty("unavailable")
        data = json.loads(raw.decode("utf-8"))
    except FileNotFoundError:
        return _empty("not_configured")
    except (OSError, ValueError, UnicodeError, RecursionError):
        return _empty("unavailable")
    if not isinstance(data, dict) or data.get("schema_version") != 2:
        return _empty("unavailable")
    navigation = data.get("navigation", {})
    if not isinstance(navigation, dict):
        return _empty("unavailable")
    if "command_center" not in navigation:
        return _empty("not_configured")
    block = navigation["command_center"]
    if not isinstance(block, dict) or not isinstance(block.get("platforms"), dict):
        return _empty("unavailable")
    verified = block.get("verified_at")
    try:
        if not _text(verified, 64):
            raise ValueError("date")
        datetime.fromisoformat(verified.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        verified = None
    result = {"state": "ready", "verified_at": verified, "platforms": {}}
    for platform_id, entry in block["platforms"].items():
        if platform_id not in PLATFORM_IDS or not isinstance(entry, dict) or not isinstance(entry.get("resources"), list):
            continue
        resources = []
        for item in entry["resources"]:
            if not isinstance(item, dict):
                continue
            kind, scope = item.get("kind"), item.get("scope")
            if (not isinstance(kind, str) or kind not in KINDS or not isinstance(scope, str) or scope not in SCOPES
                    or not _text(item.get("label"), 120) or not _url(item.get("url"))):
                continue
            resources.append({key: item[key] for key in ("kind", "label", "url", "scope")})
            if len(resources) == 8:
                break
        projected = {"resources": resources}
        if _text(entry.get("note"), 400):
            projected["note"] = entry["note"]
        result["platforms"][platform_id] = projected
    return result
