"""Owner-made cards on the Platforms tab.

Mark 2026-10-21: «сделай также возможность создать карточку, кастомизировать её … чтобы я мог сам
на платформе создавать проекты, вставлять ссылки, описывать, вставлять фотки». The shipped cards stay
in the page; these extra cards live only on the Mac mini and reach the page through an owner-only API,
so nothing about them is in the public HTML. A picture is a small image the page has already shrunk,
kept inside the record as a data URL, so there is no separate file to serve or to leak.
"""
from __future__ import annotations

import base64
import binascii
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import secrets
import threading

from .platform_edits import DESCRIPTION_MAX, GROUPS, NAME_MAX, PRIORITIES, STATUS_MAX, _clean_text, _write_json

MAX_BODY_BYTES = 512 * 1024
MAX_CARDS = 40
MAX_LINKS = 4
URL_MAX = 500
LABEL_MAX = 24
IMAGE_MAX_BYTES = 256 * 1024
LINK_KINDS = ("site", "telegram", "other")

_STORE_LOCK = threading.Lock()
_ID = re.compile(r"^c-[a-f0-9]{8}$")
_URL = re.compile(r"^(?:https?://[^\s/?#]+[^\s]*|tg://[^\s]+)$", re.IGNORECASE)
_IMAGE = re.compile(r"^data:image/(png|jpeg|webp);base64,([A-Za-z0-9+/]+={0,2})$")
_MAGIC = {
    "png": (b"\x89PNG\r\n\x1a\n",),
    "jpeg": (b"\xff\xd8\xff",),
    "webp": (b"RIFF",),
}


def _clean_url(value: object) -> str:
    url = _clean_text(value, URL_MAX)
    if not url or not _URL.match(url):
        raise ValueError("invalid_url")
    return url


def _clean_image(value: object) -> str | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise ValueError("invalid_image")
    match = _IMAGE.match(value)
    if not match:
        raise ValueError("invalid_image")
    try:
        data = base64.b64decode(match.group(2), validate=True)
    except (binascii.Error, ValueError):
        raise ValueError("invalid_image") from None
    if not data or len(data) > IMAGE_MAX_BYTES:
        raise ValueError("image_too_large")
    kind = match.group(1)
    if not data.startswith(_MAGIC[kind]) or (kind == "webp" and data[8:12] != b"WEBP"):
        raise ValueError("invalid_image")
    return value


def validate_card(entry: object, card_id: str) -> dict:
    """Return a clean card, or raise ValueError for anything malformed."""
    allowed = {"id", "name", "status", "description", "priority", "group", "links", "image"}
    if not isinstance(entry, dict) or set(entry) - allowed:
        raise ValueError("invalid_card")
    name = _clean_text(entry.get("name"), NAME_MAX)
    if not name:
        raise ValueError("name_required")
    card = {"id": card_id, "name": name}
    status = _clean_text(entry.get("status"), STATUS_MAX)
    description = _clean_text(entry.get("description"), DESCRIPTION_MAX)
    if status:
        card["status"] = status
    if description:
        card["description"] = description
    priority = entry.get("priority", "normal")
    if priority not in PRIORITIES:
        raise ValueError("invalid_priority")
    card["priority"] = priority
    # No group means a card saved before groups existed; the page shows it under «Личные».
    group = entry.get("group")
    if group is not None:
        if group not in GROUPS:
            raise ValueError("invalid_group")
        card["group"] = group
    links = entry.get("links") or []
    if not isinstance(links, list) or len(links) > MAX_LINKS:
        raise ValueError("invalid_links")
    clean_links = []
    for link in links:
        if not isinstance(link, dict) or set(link) - {"kind", "url", "label"}:
            raise ValueError("invalid_link")
        kind = link.get("kind", "site")
        if kind not in LINK_KINDS:
            raise ValueError("invalid_link_kind")
        clean = {"kind": kind, "url": _clean_url(link.get("url"))}
        label = _clean_text(link.get("label"), LABEL_MAX)
        if label:
            clean["label"] = label
        clean_links.append(clean)
    card["links"] = clean_links
    image = _clean_image(entry.get("image"))
    if image:
        card["image"] = image
    return card


class StoreUnavailable(OSError):
    """The store exists but can't be read; saving on top of it would wipe the cards."""


def load_cards(path: Path) -> dict:
    """Read the store. No file means no cards; a damaged or unreadable file raises StoreUnavailable."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return {"cards": [], "updated_at": None}
    except OSError as error:
        raise StoreUnavailable("store_unreadable") from error
    try:
        data = json.loads(text)
        cards = data.get("cards")
        if not isinstance(cards, list):
            raise ValueError("cards_list_expected")
        clean = []
        for card in cards[:MAX_CARDS]:
            try:
                if isinstance(card, dict) and isinstance(card.get("id"), str) and _ID.match(card["id"]):
                    clean.append(validate_card(card, card["id"]))
            except ValueError:
                continue  # One damaged card must not hide the others.
        return {"cards": clean, "updated_at": data.get("updated_at")}
    except (ValueError, TypeError, AttributeError) as error:
        raise StoreUnavailable("store_unreadable") from error


def change_cards(path: Path, payload: object, *, now: datetime | None = None, new_id=None) -> dict:
    """Save or delete one card on top of what is stored now; returns the whole store.

    ``{"action": "save", "card": {...}}`` creates a card (no ``id``) or replaces the one with that
    ``id``; ``{"action": "delete", "id": "c-…"}`` removes it.
    """
    if not isinstance(payload, dict) or payload.get("action") not in ("save", "delete"):
        raise ValueError("action_expected")
    with _STORE_LOCK:
        cards = load_cards(path)["cards"]
        if payload["action"] == "delete":
            if set(payload) - {"action", "id"}:
                raise ValueError("invalid_request")
            card_id = payload.get("id")
            if not isinstance(card_id, str) or not _ID.match(card_id):
                raise ValueError("invalid_card_id")
            if not any(card["id"] == card_id for card in cards):
                raise LookupError("card_not_found")
            cards = [card for card in cards if card["id"] != card_id]
        else:
            if set(payload) - {"action", "card"}:
                raise ValueError("invalid_request")
            entry = payload.get("card")
            card_id = entry.get("id") if isinstance(entry, dict) else None
            if card_id is None:
                if len(cards) >= MAX_CARDS:
                    raise ValueError("too_many_cards")
                card_id = (new_id or (lambda: f"c-{secrets.token_hex(4)}"))()
                cards.append(validate_card(entry, card_id))
            else:
                if not isinstance(card_id, str) or not _ID.match(card_id):
                    raise ValueError("invalid_card_id")
                index = next((i for i, card in enumerate(cards) if card["id"] == card_id), None)
                if index is None:
                    raise LookupError("card_not_found")
                cards[index] = validate_card(entry, card_id)
        stamp = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
        record = {"cards": cards, "updated_at": stamp}
        _write_json(Path(path), record, prefix=".platform-cards.")
        return {**record, "id": card_id}
