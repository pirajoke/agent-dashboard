#!/usr/bin/env python3
"""Suggest a DOCXXx folder for each «Нужен разбор» document from its content.

Mark 2026-10-26: «смотреть по контексту… есть все папочки. Если по контексту подходят, мы это
забираем. Если не подходят, не забираем». Runs on the Mac mini (launchd
``com.pirajoke.docxx-suggest``, every 10 minutes). For open review documents without a guess it
sends the file name, the start of the text DOCXX already extracted (lines with passwords or
logins removed) and the list of existing library folders to the Claude Code CLI signed in on
this Mac (``claude -p``, no tools, same call as the day summarizer). The answer per document is
one folder from that list, «junk», or nothing. Results go to ``~/.agent-bridge/docxx-suggestions.json``.

Mark 2026-11-02: «не забирай дубли… автоматически определять, куда что пошло. Остальное просто
в архив». After the guesses, each open review document is sorted by itself through the same
reversible decisions the site uses (``docxx_actions.apply``, «Вернуть» undoes it): a copy of a
document already in the library or already seen goes to the trash folder, a document with a
fitting folder goes there, junk goes to the trash folder, and everything else the model looked at
goes to the archive folder. Nothing is deleted and nothing is sent anywhere else.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from daily_work_summarizer import call_claude, find_cli, iso_z, redact, write_json  # noqa: E402
from dashboard_builder.docxx import state_path  # noqa: E402
from dashboard_builder.docxx_actions import (  # noqa: E402
    MAX_KEYS, apply, decisions_path, folders_view, load_decisions, load_suggestions, suggestions_path, _sortable)

SCHEMA = 1
HOME = Path.home()
DEFAULT_MODEL = os.environ.get("DOCXX_SUGGEST_MODEL", "claude-sonnet-5-5")
BATCH = 6
MAX_BATCHES = 3
TEXT_LIMIT = 1500
HASH_LIMIT = 50 * 1024 * 1024
MAX_CANDIDATES = 60
WHY_LIMIT = 160
WORKDIR_NAME = "docxx-suggest-workdir"

SYSTEM_PROMPT = """Ты помогаешь Марку разложить документы по папкам его библиотеки на Google Drive. \
Для каждого документа дано имя файла и начало его текста. Дан точный список существующих папок.
Для каждого id ответь:
- folder: одна папка из списка, если документ по смыслу явно к ней относится; иначе null. \
Не придумывай новых папок и не меняй написание;
- junk: true только если это явный мусор (пустой скан, реклама, служебное уведомление без ценности, \
дубликат-заглушка); иначе false;
- why: одна короткая фраза по-русски, почему (до 12 слов), без паролей, номеров и личных данных.
Если сомневаешься — folder: null, junk: false. Ответ — только JSON-объект вида \
{"<id>": {"folder": "..." или null, "junk": false, "why": "..."}} для каждого id, без пояснений."""

# Ticket and account mails carry logins; never pass those lines to the model.
_SECRET = re.compile(r"mot de passe|password|passwort|пароль|identifiant|login|логин|code|pin\b|iban|token",
                     re.IGNORECASE)


def clean_text(text: str) -> str:
    """Text without credential labels and the value that follows them, on the same line or the next."""
    lines = [" ".join(line.split()) for line in str(text or "").splitlines()]
    kept, skip_next = [], False
    for line in lines:
        if not line:
            continue
        if _SECRET.search(line):
            # «Mot de passe : x» or «Mot de passe» then «x» on its own line: drop both forms.
            skip_next = True
            continue
        if skip_next:
            skip_next = False
            continue
        kept.append(line)
    return "\n".join(kept)[:TEXT_LIMIT]


def content_sha(row: dict[str, Any]) -> str | None:
    """The document's sha256: from its journal row, else from the local file (Drive, iCloud, review)."""
    if row.get("_sha"):
        return row["_sha"][0]
    path = row.get("_path")
    try:
        if not path or os.path.islink(path) or not os.path.isfile(path) or os.path.getsize(path) > HASH_LIMIT:
            return None
        digest = hashlib.sha256()
        with open(path, "rb") as stream:
            for chunk in iter(lambda: stream.read(1 << 20), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


def extraction_texts(directory: Path, shas: list[str]) -> dict[str, str]:
    """The newest extracted text for each sha256, read-only; empty when the database is missing."""
    database = Path(directory) / "operations.sqlite3"
    if not shas or not database.is_file() or database.is_symlink():
        return {}
    texts: dict[str, str] = {}
    try:
        connection = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True, timeout=1)
    except sqlite3.Error:
        return {}
    try:
        for sha in dict.fromkeys(shas):
            row = connection.execute(
                "SELECT substr(e.text,1,?) FROM extractions e WHERE e.sha256=? "
                "ORDER BY e.created_at DESC,e.extractor_id LIMIT 1", (TEXT_LIMIT * 4, sha)).fetchone()
            if row and row[0]:
                texts[sha] = clean_text(row[0])
    except sqlite3.Error:
        return texts
    finally:
        connection.close()
    return texts


def due_rows(directory: Path, decisions: dict, known: dict, folders: set[str]) -> list[dict[str, Any]]:
    """Open review rows with no usable guess, each with its cleaned text under ``_text``."""
    rows, _ = _sortable(directory, decisions)
    candidates = [row for row in rows.values() if row.get("status") == "needs_review"][:MAX_CANDIDATES]
    shas = {row["key"]: content_sha(row) for row in candidates}
    texts = extraction_texts(directory, [sha for sha in shas.values() if sha])
    due = []
    for row in candidates:
        row["_text"] = texts.get(shas[row["key"]], "") if shas[row["key"]] else ""
        guess = known.get(row["key"])
        if isinstance(guess, dict) and guess.get("name") == row.get("name"):
            gone = guess.get("folder") is not None and guess.get("folder") not in folders
            text_arrived = guess.get("had_text") is False and bool(row["_text"])
            if not gone and not text_arrived:
                continue
        due.append(row)
    return due


def user_prompt(batch: list[dict[str, Any]], folders: list[str]) -> str:
    items = [{"id": row["key"], "name": row.get("original_name") or row.get("name"), "text": row.get("_text", "")}
             for row in batch]
    return json.dumps({"folders": folders, "documents": items}, ensure_ascii=False, indent=1)


def parse_reply(text: str, ids: set[str], folders: set[str]) -> dict[str, dict[str, Any]]:
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        raise ValueError("suggest_reply_not_json")
    data = json.loads(match.group(0))
    if not isinstance(data, dict):
        raise ValueError("suggest_reply_not_object")
    out = {}
    for key, value in data.items():
        if key not in ids or not isinstance(value, dict):
            continue
        folder = value.get("folder")
        junk = value.get("junk") is True
        out[key] = {"folder": folder if isinstance(folder, str) and folder in folders and not junk else None,
                    "junk": junk, "why": " ".join(str(value.get("why") or "").split())[:WHY_LIMIT]}
    return out


def sort_plan(rows: dict, guesses: dict, view: dict) -> dict[str, list]:
    """Which open review documents go where: {(action, folder): [keys]}. Pure, so it can be tested."""
    movable = set(view.get("movable") or [])
    filed = {content_sha(row) for row in rows.values() if row.get("status") != "needs_review"} - {None}
    seen: set[str] = set()
    plan: dict = {}
    open_rows = sorted((row for key, row in rows.items() if key in movable and row.get("status") == "needs_review"),
                       key=lambda row: str(row.get("at") or ""))
    for row in open_rows:
        sha = content_sha(row)
        if sha and (sha in filed or sha in seen):
            plan.setdefault(("trash", None), []).append(row["key"])
            continue
        if sha:
            seen.add(sha)
        guess = guesses.get(row["key"])
        if not isinstance(guess, dict) or guess.get("name") != row.get("name"):
            continue  # No guess yet: wait for the model, the next run sorts it.
        if guess.get("junk") is True:
            plan.setdefault(("trash", None), []).append(row["key"])
        elif guess.get("folder") in (view.get("folders") or []):
            plan.setdefault(("move", guess["folder"]), []).append(row["key"])
        elif view.get("archive"):
            plan.setdefault(("archive", None), []).append(row["key"])
    return plan


def auto_sort(state: Path, home: Path) -> dict[str, int]:
    decisions_file = decisions_path(home)
    view = folders_view(state, decisions_file)
    if view.get("state") != "ready":
        return {}
    rows, _ = _sortable(state, load_decisions(decisions_file))
    done: dict[str, int] = {}
    for (action, folder), keys in sort_plan(rows, load_suggestions(suggestions_path(home)), view).items():
        for start in range(0, len(keys), MAX_KEYS):
            body = {"action": action, "keys": keys[start:start + MAX_KEYS], **({"folder": folder} if folder else {})}
            try:
                result = apply(state, decisions_file, body)
            except (OSError, ValueError):
                continue
            done[action] = done.get(action, 0) + sum(1 for item in result["results"] if item.get("ok"))
    return done


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--state", type=Path, default=state_path(HOME))
    parser.add_argument("--home", type=Path, default=HOME)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--claude", default=os.environ.get("DOCXX_SUGGEST_CLAUDE"), help="path to the claude CLI")
    parser.add_argument("--batches", type=int, default=MAX_BATCHES, help="Claude calls per run")
    parser.add_argument("--dry-run", action="store_true", help="print the prompts instead of calling Claude")
    parser.add_argument("--no-sort", action="store_true", help="only write guesses, move nothing")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    out = suggestions_path(args.home)
    try:
        saved = json.loads(out.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        saved = None
    if not isinstance(saved, dict) or saved.get("schema_version") != SCHEMA or not isinstance(saved.get("items"), dict):
        saved = {"schema_version": SCHEMA, "items": {}}
    saved["items"] = load_suggestions(out) if saved["items"] else {}
    status: dict[str, Any] = {"last_run": iso_z(datetime.now(timezone.utc)), "model": args.model, "ok": True,
                              "reason": None, "written": 0, "pending": 0}
    decisions_file = decisions_path(args.home)
    view = folders_view(args.state, decisions_file)
    if view.get("state") != "ready" or not view.get("folders"):
        status.update(ok=False, reason="library_unavailable")
        saved["status"] = status
        write_json(out, saved)
        print(json.dumps(status, ensure_ascii=False))
        return 1
    folders = list(view["folders"])
    due = due_rows(args.state, load_decisions(decisions_file), saved["items"], set(folders))
    batches = [due[i:i + BATCH] for i in range(0, len(due), BATCH)][: max(1, args.batches)]
    if args.dry_run:
        for batch in batches:
            print(user_prompt(batch, folders) + "\n")
        return 0
    cli = find_cli(args.claude) if batches else None
    if batches and not cli:
        status.update(ok=False, reason="claude_not_found")
    for batch in batches if cli else []:
        try:
            reply = call_claude(cli, args.model, SYSTEM_PROMPT, user_prompt(batch, folders),
                                out.parent / WORKDIR_NAME)
            answers = parse_reply(reply, {row["key"] for row in batch}, set(folders))
        except (RuntimeError, ValueError) as error:
            status.update(ok=False, reason=redact(str(error))[:240])
            break
        now = iso_z(datetime.now(timezone.utc))
        for row in batch:
            if row["key"] in answers:
                saved["items"][row["key"]] = {"name": row.get("name"), "at": now, "had_text": bool(row["_text"]),
                                              **answers[row["key"]]}
                status["written"] += 1
        write_json(out, saved)
    status["pending"] = max(0, len(due) - status["written"])
    if not args.no_sort:
        write_json(out, saved)
        status["sorted"] = auto_sort(args.state, args.home)
    saved["status"] = status
    write_json(out, saved)
    try:
        os.chmod(out, 0o600)
    except OSError:
        pass
    print(json.dumps(status, ensure_ascii=False))
    return 0 if status["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
