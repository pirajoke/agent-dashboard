"""Bounded owner-only navigation projection from the canonical portfolio registry.

No private registry contents are read for an anonymous caller. This module
returns only navigation metadata, never the underlying project or owner records.
Owner project cards (`navigation.command_center.projects`) are a short status
plus links to the documents that hold the real record; they are not a copy of it.
"""
from __future__ import annotations

from datetime import datetime
import json
import re
from pathlib import Path
import unicodedata
from urllib.parse import unquote, urlsplit

MAX_BYTES = 1024 * 1024
PLATFORM_IDS = frozenset(("financial", "mydictionary", "health", "ai-singularity", "context-news",
                         "accountable", "jarvis", "property-os", "pixel-agents", "closeness-mirror",
                         "sushi-parisien", "n8n"))
KINDS = frozenset(("documents", "notes", "code", "tasks"))
SCOPES = frozenset(("current", "archive", "upstream", "reference"))
HOSTS = frozenset(("github.com", "drive.google.com", "docs.google.com"))
PROJECT_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,39}")
MAX_PROJECTS = 12
MAX_FACTS = 10
MAX_TASKS = 10
MAX_LINKS = 4


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


def _command_center_block(path: Path) -> tuple[str, dict | None]:
    """Read navigation.command_center, or say why it cannot be used."""
    try:
        with Path(path).open("rb") as stream:
            raw = stream.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            return "unavailable", None
        data = json.loads(raw.decode("utf-8"))
    except FileNotFoundError:
        return "not_configured", None
    except (OSError, ValueError, UnicodeError, RecursionError):
        return "unavailable", None
    if not isinstance(data, dict) or data.get("schema_version") != 2:
        return "unavailable", None
    navigation = data.get("navigation", {})
    if not isinstance(navigation, dict):
        return "unavailable", None
    if "command_center" not in navigation:
        return "not_configured", None
    block = navigation["command_center"]
    if not isinstance(block, dict):
        return "unavailable", None
    return "ready", block


def _verified(block: dict) -> str | None:
    verified = block.get("verified_at")
    try:
        if not _text(verified, 64):
            raise ValueError("date")
        datetime.fromisoformat(verified.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    return verified


def platform_resources_projection(path: Path, owner: bool = False) -> dict:
    if not owner:
        return _empty("owner_required")
    state, block = _command_center_block(path)
    if block is None:
        return _empty(state)
    # A registry holding only owner project cards has no platform links yet.
    platforms = block.get("platforms", {})
    if not isinstance(platforms, dict):
        return _empty("unavailable")
    verified = _verified(block)
    result = {"state": "ready", "verified_at": verified, "platforms": {}}
    for platform_id, entry in platforms.items():
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


def _project_card(entry: object) -> dict | None:
    if not isinstance(entry, dict):
        return None
    card_id = entry.get("id")
    if not isinstance(card_id, str) or not PROJECT_ID.fullmatch(card_id):
        return None
    if not _text(entry.get("name"), 80) or not _text(entry.get("status"), 200):
        return None
    card = {"id": card_id, "name": entry["name"], "status": entry["status"]}
    if _text(entry.get("checked"), 10):
        try:
            datetime.strptime(entry["checked"], "%Y-%m-%d")
            card["checked"] = entry["checked"]
        except ValueError:
            pass
    facts = entry.get("facts") if isinstance(entry.get("facts"), list) else []
    card["facts"] = [{"label": item["label"], "text": item["text"]} for item in facts
                     if isinstance(item, dict) and _text(item.get("label"), 40) and _text(item.get("text"), 400)
                     ][:MAX_FACTS]
    tasks = entry.get("tasks") if isinstance(entry.get("tasks"), list) else []
    card["tasks"] = [item for item in tasks if _text(item, 200)][:MAX_TASKS]
    links = entry.get("links") if isinstance(entry.get("links"), list) else []
    card["links"] = [{"label": item["label"], "url": item["url"]} for item in links
                     if isinstance(item, dict) and _text(item.get("label"), 40) and _url(item.get("url"))
                     ][:MAX_LINKS]
    return card


def owner_projects_projection(path: Path, owner: bool = False) -> dict:
    """Owner-only project cards; an anonymous caller never causes a registry read."""
    if not owner:
        return {"state": "owner_required", "verified_at": None, "projects": []}
    state, block = _command_center_block(path)
    if block is None:
        return {"state": state, "verified_at": None, "projects": []}
    entries = block.get("projects", [])
    if not isinstance(entries, list):
        return {"state": "unavailable", "verified_at": None, "projects": []}
    projects, seen = [], set()
    for entry in entries:
        card = _project_card(entry)
        # One card per id: a repeated id never shows a second, competing card.
        if card is None or card["id"] in seen:
            continue
        seen.add(card["id"])
        projects.append(card)
        if len(projects) == MAX_PROJECTS:
            break
    return {"state": "ready", "verified_at": _verified(block), "projects": projects}
