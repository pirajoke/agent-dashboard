#!/usr/bin/env python3
"""Monday digest of last week's work, sent to Mark in Telegram (Mark 2026-10-22).

Runs on the Mac mini (launchd ``com.pirajoke.weekly-digest``, Mondays at 09:00). It reads the same
data as MAIN MANAGER (``work_projection`` over the Daily Work files: Claude Code and Codex sessions,
merged PRs, Claude's day summaries) and the «Ждёт тебя» list, and writes a short Russian text:
hours this week and the week before, the Claude Code / Codex split, PRs merged, what moved in the
main projects, and what waits on Mark.

The text is always saved to ``~/.agent-bridge/weekly-digest/<week>.md``. It is sent only when
``~/.agent-bridge/telegram_digest.json`` holds ``{"bot_token": "...", "chat_id": "..."}`` (mode 600,
written by Mark); without it the run records ``telegram_not_configured`` and sends nothing.
A week is sent once; ``--force`` sends it again.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from dashboard_builder.daily_work import work_projection  # noqa: E402

HOME = Path.home()
DAILY_WORK_DIR = HOME / ".agent-bridge" / "daily-work"
OWNER_TODO_FILE = HOME / ".agent-bridge" / "owner-todo.json"
OUT_DIR = HOME / ".agent-bridge" / "weekly-digest"
CONFIG_FILE = HOME / ".agent-bridge" / "telegram_digest.json"
SITE = "https://command.meshly.fr/"
MAX_PROJECTS = 6
MAX_TODO = 5
MONTHS = ["янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"]
TOKEN = re.compile(r"^\d{5,}:[A-Za-z0-9_-]{20,}$")


def hours(minutes: int) -> str:
    minutes = max(0, int(minutes or 0))
    if minutes < 60:
        return f"{minutes} мин"
    value = minutes / 60
    text = f"{value:.0f}" if value >= 10 else f"{value:.1f}".rstrip("0").rstrip(".").replace(".", ",")
    return f"{text} ч"


def day_label(day: date) -> str:
    return f"{day.day} {MONTHS[day.month - 1]}"


def compose(projection: dict[str, Any], todo: list[dict[str, Any]], today: date) -> str:
    """The digest text. Only real numbers: a week without data says so instead of showing zeros."""
    first, last = today - timedelta(days=7), today - timedelta(days=1)
    lines = [f"Итоги недели · {day_label(first)} – {day_label(last)}", ""]
    week = (projection.get("traction") or {}).get("last_7") or {}
    before = (projection.get("traction") or {}).get("previous_7") or {}
    total = int(week.get("total_minutes") or 0)
    if not total and not week.get("prs_merged"):
        lines.append("За неделю работы агентов в данных нет.")
    else:
        trend = ""
        if before.get("total_minutes"):
            trend = f" (неделей раньше {hours(before['total_minutes'])})"
        lines.append(f"Работа агентов: {hours(total)}{trend}")
        lines.append(f"Claude Code {hours(week.get('claude_minutes'))} · Codex {hours(week.get('codex_minutes'))}")
        lines.append(f"Слито PR: {int(week.get('prs_merged') or 0)}")
    moved = []
    for project in projection.get("projects") or []:
        claude = sum((project.get("daily_claude_minutes") or [])[-8:-1])
        codex = sum((project.get("daily_codex_minutes") or [])[-8:-1])
        merged = sum((project.get("daily_prs_merged") or [])[-8:-1])
        if not (claude or codex or merged):
            continue
        moved.append((bool(project.get("main")), claude + codex, project, claude, codex, merged))
    moved.sort(key=lambda item: (item[0], item[1]), reverse=True)
    if moved:
        lines += ["", "Что сдвинулось:"]
        for _, minutes, project, claude, codex, merged in moved[:MAX_PROJECTS]:
            split = " / ".join(part for part in (f"Claude Code {hours(claude)}" if claude else "",
                                                 f"Codex {hours(codex)}" if codex else "") if part)
            extra = f", PR: {merged}" if merged else ""
            lines.append(f"• {project.get('name') or project.get('id')} — {hours(minutes)}"
                         + (f" ({split})" if split else "") + extra)
            summary = project.get("last_summary") or {}
            bullet = (summary.get("bullets") or [None])[0]
            if bullet and summary.get("date", "") >= first.isoformat():
                lines.append(f"  {bullet}")
        if len(moved) > MAX_PROJECTS:
            lines.append(f"• и ещё {len(moved) - MAX_PROJECTS}")
    waiting = [item for item in todo if not item.get("done")]
    if waiting:
        lines += ["", f"Ждёт тебя ({len(waiting)}):"]
        lines += [f"• {item['text']}" for item in waiting[:MAX_TODO]]
        if len(waiting) > MAX_TODO:
            lines.append(f"• и ещё {len(waiting) - MAX_TODO}")
    lines += ["", SITE]
    return "\n".join(lines)


def load_todo(path: Path) -> list[dict[str, Any]]:
    """Open «Ждёт тебя» items; nothing when the list is missing or damaged."""
    try:
        items = json.loads(path.read_text(encoding="utf-8")).get("items")
    except (OSError, ValueError, AttributeError):
        return []
    return [item for item in items or [] if isinstance(item, dict) and isinstance(item.get("text"), str)
            and item["text"].strip() and not item.get("done")]


def load_config(path: Path = CONFIG_FILE) -> dict[str, str] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    token, chat = str(data.get("bot_token") or "").strip(), str(data.get("chat_id") or "").strip()
    if not TOKEN.match(token) or not re.fullmatch(r"-?\d{3,20}|@[A-Za-z0-9_]{5,}", chat):
        return None
    return {"bot_token": token, "chat_id": chat}


def send(config: dict[str, str], text: str, opener=urllib.request.urlopen) -> None:
    body = json.dumps({"chat_id": config["chat_id"], "text": text, "disable_web_page_preview": True}).encode()
    request = urllib.request.Request(f"https://api.telegram.org/bot{config['bot_token']}/sendMessage", data=body,
                                     headers={"Content-Type": "application/json"}, method="POST")
    with opener(request, timeout=20) as response:
        answer = json.loads(response.read() or b"{}")
    if not answer.get("ok"):
        raise RuntimeError(f"telegram_refused: {str(answer.get('description') or '')[:120]}")


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(text, encoding="utf-8")
    temp.chmod(0o600)
    temp.replace(path)


def run(*, now: datetime | None = None, root: Path = DAILY_WORK_DIR, todo_file: Path = OWNER_TODO_FILE,
        out: Path = OUT_DIR, config_file: Path = CONFIG_FILE, force: bool = False, dry_run: bool = False,
        opener=urllib.request.urlopen) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    today = now.astimezone().date()
    week = (today - timedelta(days=7)).isoformat()
    status_path = out / "status.json"
    try:
        status = json.loads(status_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        status = {}
    projection = work_projection(root, now=now, days=14, owner=True)
    todo = load_todo(todo_file)
    text = compose(projection, todo, today)
    write(out / f"{week}.md", text + "\n")
    result: dict[str, Any] = {"week": week, "at": now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                              "file": str(out / f"{week}.md")}
    if dry_run:
        result.update(ok=True, sent=False, reason="dry_run")
        print(text)
        return result
    if status.get("sent_week") == week and not force:
        result.update(ok=True, sent=False, reason="already_sent")
    else:
        config = load_config(config_file)
        if config is None:
            result.update(ok=False, sent=False, reason="telegram_not_configured")
        else:
            try:
                send(config, text, opener)
                result.update(ok=True, sent=True, sent_week=week)
            except (OSError, ValueError, RuntimeError, urllib.error.URLError) as error:
                reason = str(error).replace(config["bot_token"], "[token]")
                result.update(ok=False, sent=False, reason=reason[:200])
    status.update({key: value for key, value in result.items() if key != "file"})
    if not result.get("sent"):
        status.pop("sent", None)
    write(status_path, json.dumps(status, ensure_ascii=False, indent=2))
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--force", action="store_true", help="send this week again")
    parser.add_argument("--dry-run", action="store_true", help="print the text, send nothing")
    args = parser.parse_args(argv)
    result = run(force=args.force, dry_run=args.dry_run)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
