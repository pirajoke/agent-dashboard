#!/usr/bin/env python3
"""Retell English project updates from the Контекст tab in two or three plain Russian lines.

Mark 2026-10-25: an update written by Codex in English, with State and Changed Files,
was «невозможно читать». Runs on the Mac mini (launchd ``com.pirajoke.context-retell``,
every 10 minutes). It reads the private context catalog, picks project updates that are
mostly not in Russian and have no retelling for their current text, and asks the Claude
Code CLI signed in on this Mac (``claude -p``, no tools, same call as the day summarizer)
for a short Russian title and two or three plain lines. Results go to ``retold.json``
next to the catalog; the owner-only ``/api/context-library`` adds them to the records.
A record whose text changes is retold again. Nothing is sent anywhere else.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from daily_work_summarizer import call_claude, find_cli, iso_z, redact, write_json  # noqa: E402

SCHEMA = 1
HOME = Path.home()
DEFAULT_CATALOG = Path(os.environ.get(
    "COMMAND_CENTER_CONTEXT_CATALOG", str(HOME / ".agent-bridge" / "context-library" / "catalog.json")))
DEFAULT_MODEL = os.environ.get("CONTEXT_RETELL_MODEL", "claude-sonnet-5-5")
BATCH = 8
MAX_BATCHES = 3
NEWEST = 200
INPUT_LIMIT = 2500
TITLE_LIMIT = 90
TEXT_LIMIT = 420
WORKDIR_NAME = "retell-workdir"

SYSTEM_PROMPT = """Ты пересказываешь короткие отчёты агентов (Claude, Codex) для Марка, владельца \
нескольких продуктов. Марк не программист. Для каждой записи напиши по-русски:
- title: короткий заголовок, до 8 слов, о чём запись;
- text: 2–3 простых предложения: что сделали и что это значит для Марка.
Без технических слов, путей к файлам, веток, коммитов, ID и подсчётов проверок. Не выдумывай \
того, чего нет в тексте. Ответ — только JSON-объект вида {"<id>": {"title": "...", "text": "..."}} \
для каждого id из запроса, без пояснений вокруг."""

_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*$")
_STAMP = re.compile(r"^\s*(?:\*\*)?(?:recorded|created|updated|date)(?:\*\*)?\s*:", re.IGNORECASE)
_SUMMARY = re.compile(r"^(?:summary|tl;?dr|result|outcome|итог|итоги|резюме|кратко|что сделано)$", re.IGNORECASE)
_FRONT_MATTER = re.compile(r"^---\n[\s\S]*?\n(?:---|\.\.\.)[ \t]*(?:\n|$)")


def retold_path(catalog: Path) -> Path:
    return catalog.with_name("retold.json")


def summary_text(body: str, title: str) -> str:
    """The part of an update worth retelling: its summary section, else its first block."""
    text = _FRONT_MATTER.sub("", body.replace("\r\n", "\n").lstrip("﻿"))
    sections: list[tuple[str, list[str]]] = [("", [])]
    for line in text.split("\n"):
        heading = _HEADING.match(line)
        if heading:
            sections.append((heading.group(1).strip(), []))
        elif not _STAMP.match(line):
            sections[-1][1].append(line)
    filled = [(h, "\n".join(lines).strip()) for h, lines in sections if "\n".join(lines).strip()]
    chosen = next((t for h, t in filled if _SUMMARY.match(h)), None)
    if chosen is None:
        chosen = next((t for h, t in filled if not h or h == title), filled[0][1] if filled else "")
    return chosen[:INPUT_LIMIT]


def mostly_russian(text: str) -> bool:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return True
    cyrillic = sum(1 for c in letters if "Ѐ" <= c <= "ӿ")
    return cyrillic / len(letters) >= 0.5


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def due_records(catalog: dict[str, Any], retold: dict[str, Any]) -> list[dict[str, Any]]:
    """Updates without a retelling for their current text, newest first."""
    items = retold.get("items", {}) if isinstance(retold, dict) else {}
    updates = [r for r in catalog.get("records", []) if isinstance(r, dict) and r.get("kind") == "update"]
    updates.sort(key=lambda r: str(r.get("modified_at", "")), reverse=True)
    due = []
    for record in updates[:NEWEST]:
        known = items.get(record.get("id"))
        if isinstance(known, dict) and known.get("sha256") == record.get("sha256"):
            continue
        source = summary_text(str(record.get("body", "")), str(record.get("title", "")))
        if not source or mostly_russian(str(record.get("title", "")) + "\n" + source):
            continue
        due.append({"id": record["id"], "sha256": record.get("sha256"), "title": record.get("title", ""),
                    "project": record.get("project", ""), "text": source})
    return due


def user_prompt(batch: list[dict[str, Any]]) -> str:
    return json.dumps([{"id": r["id"], "project": r["project"], "title": r["title"], "text": r["text"]}
                       for r in batch], ensure_ascii=False, indent=1)


def parse_reply(text: str, ids: set[str]) -> dict[str, dict[str, str]]:
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        raise ValueError("retell_reply_not_json")
    data = json.loads(match.group(0))
    if not isinstance(data, dict):
        raise ValueError("retell_reply_not_object")
    out = {}
    for rid, value in data.items():
        if rid not in ids or not isinstance(value, dict):
            continue
        title = " ".join(str(value.get("title", "")).split())[:TITLE_LIMIT]
        body = " ".join(str(value.get("text", "")).split())[:TEXT_LIMIT]
        if title and body:
            out[rid] = {"title": title, "text": body}
    return out


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--claude", default=os.environ.get("CONTEXT_RETELL_CLAUDE"), help="path to the claude CLI")
    parser.add_argument("--batches", type=int, default=MAX_BATCHES, help="Claude calls per run")
    parser.add_argument("--dry-run", action="store_true", help="print the prompts instead of calling Claude")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    out = retold_path(args.catalog)
    catalog = load_json(args.catalog)
    retold = load_json(out)
    if not isinstance(retold, dict) or retold.get("schema") != SCHEMA or not isinstance(retold.get("items"), dict):
        retold = {"schema": SCHEMA, "items": {}}
    status: dict[str, Any] = {"last_run": iso_z(datetime.now(timezone.utc)), "model": args.model, "ok": True,
                              "reason": None, "written": 0, "pending": 0}
    if not isinstance(catalog, dict) or not isinstance(catalog.get("records"), list):
        status.update(ok=False, reason="catalog_unavailable")
        print(json.dumps(status, ensure_ascii=False))
        return 1
    due = due_records(catalog, retold)
    batches = [due[i:i + BATCH] for i in range(0, len(due), BATCH)][: max(1, args.batches)]
    if args.dry_run:
        for batch in batches:
            print(user_prompt(batch) + "\n")
        return 0
    cli = find_cli(args.claude) if batches else None
    if batches and not cli:
        status.update(ok=False, reason="claude_not_found")
    for batch in batches if cli else []:
        try:
            reply = call_claude(cli, args.model, SYSTEM_PROMPT, user_prompt(batch), out.parent / WORKDIR_NAME)
            answers = parse_reply(reply, {r["id"] for r in batch})
        except (RuntimeError, ValueError) as error:
            status.update(ok=False, reason=redact(str(error))[:240])
            break
        now = iso_z(datetime.now(timezone.utc))
        for record in batch:
            if record["id"] in answers:
                retold["items"][record["id"]] = {"sha256": record["sha256"], "at": now, **answers[record["id"]]}
                status["written"] += 1
        retold["generated_at"] = now
        write_json(out, retold)
    status["pending"] = max(0, len(due) - status["written"])
    retold["status"] = status
    write_json(out, retold)
    print(json.dumps(status, ensure_ascii=False))
    return 0 if status["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
