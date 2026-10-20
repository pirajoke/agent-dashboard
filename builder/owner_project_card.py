#!/usr/bin/env python3
"""Add or update one owner project card in the private Portfolio Registry.

The card JSON comes on stdin and never lives in this repository:

    python3 builder/owner_project_card.py < card.json

The card goes to `navigation.command_center.projects` and replaces a card with
the same `id`, so running it again updates the card instead of adding a second
one. The registry is copied to `<name>.bak-<UTC time>` first and written
atomically. A card the server would trim (unknown host, overlong text, too many
lines) is refused, so what you send is exactly what MAIN MANAGER shows.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))

from dashboard_builder.platform_resources import MAX_BYTES, _project_card  # noqa: E402

DEFAULT_REGISTRY = Path(os.environ.get("JARVIS_VAULT_PATH", str(Path.home() / "jarvis-context-vault"))).expanduser() \
    / "35-Systems" / "PORTFOLIO-REGISTRY.json"
CARD_FIELDS = ("id", "name", "status", "checked", "facts", "tasks", "links")


def _shown(card: dict) -> dict:
    return {key: card[key] for key in CARD_FIELDS if key in card}


def upsert(registry: Path, card: dict) -> str:
    projected = _project_card(card)
    if projected is None:
        raise ValueError("card needs id (a-z, 0-9, -), name and status")
    wanted = _shown(card)
    for key in ("facts", "tasks", "links"):
        wanted.setdefault(key, [])
    if projected != wanted:
        dropped = [key for key in wanted if projected.get(key) != wanted[key]]
        raise ValueError(f"the server would trim this card ({', '.join(dropped)}); shorten it or fix the links")
    raw = registry.read_bytes()
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, dict) or data.get("schema_version") != 2:
        raise ValueError("registry is not a Portfolio Registry v2")
    navigation = data.setdefault("navigation", {})
    block = navigation.setdefault("command_center", {}) if isinstance(navigation, dict) else None
    if not isinstance(block, dict):
        raise ValueError("registry navigation block is malformed")
    cards = block.setdefault("projects", [])
    if not isinstance(cards, list):
        raise ValueError("navigation.command_center.projects is not a list")
    # The first card with this id is replaced in place; later copies go, so there is never a duplicate.
    result, replaced = [], False
    for item in cards:
        if isinstance(item, dict) and item.get("id") == projected["id"]:
            if not replaced:
                result.append(_shown(card))
                replaced = True
            continue
        result.append(item)
    if not replaced:
        result.append(_shown(card))
    block["projects"] = result
    action = "updated" if replaced else "added"
    body = (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    if len(body) > MAX_BYTES:
        raise ValueError("registry would exceed 1 MiB")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    shutil.copy2(registry, registry.with_name(f"{registry.name}.bak-{stamp}"))
    handle, tmp = tempfile.mkstemp(prefix=".registry-", dir=registry.parent)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(body)
        os.chmod(tmp, registry.stat().st_mode & 0o777)
        os.replace(tmp, registry)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return action


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    args = parser.parse_args(argv)
    if not args.registry.is_file():
        print(f"Нет реестра {args.registry}: карточку не записал.", file=sys.stderr)
        return 2
    try:
        card = json.loads(sys.stdin.read())
        if not isinstance(card, dict):
            raise ValueError("card must be a JSON object")
        action = upsert(args.registry, card)
    except (OSError, ValueError) as exc:
        print(f"Карточку не записал: {exc}", file=sys.stderr)
        return 1
    print(f"Карточка «{card['name']}» {'обновлена' if action == 'updated' else 'добавлена'}: {args.registry}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
