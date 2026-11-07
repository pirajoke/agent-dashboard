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

Mark 2026-11-07 («Итоги недели»): projects drop weekly notes into an inbox (see
``dashboard_builder/weekly_reports.py``); they show up «По направлениям» with «Сделано», «Ждёт тебя» and
«Дальше». Each week is also saved as ``<monday>.json`` for the «Итоги недели» page. ``--now`` builds the
week so far (the page button and Jarvis use it) without marking the week as sent.
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
from dashboard_builder.weekly_reports import collect_notes, direction_lines, group_by_direction, report_week  # noqa: E402

HOME = Path.home()
DAILY_WORK_DIR = HOME / ".agent-bridge" / "daily-work"
OWNER_TODO_FILE = HOME / ".agent-bridge" / "owner-todo.json"
OUT_DIR = HOME / ".agent-bridge" / "weekly-digest"
CONFIG_FILE = HOME / ".agent-bridge" / "telegram_digest.json"
SITE = "https://command.meshly.fr/"
MAX_PROJECTS = 6
MAX_TODO = 5
MONTHS = ["янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"]
TELEGRAM_LIMIT = 4000
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


def digest_data(projection: dict[str, Any], todo: list[dict[str, Any]], today: date,
                blocks: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """The week as data: the page shows it, ``render`` turns it into the Telegram text."""
    first, last = report_week(today), today - timedelta(days=1)
    week = (projection.get("traction") or {}).get("last_7") or {}
    before = (projection.get("traction") or {}).get("previous_7") or {}
    numbers = {"total_minutes": int(week.get("total_minutes") or 0),
               "claude_minutes": int(week.get("claude_minutes") or 0),
               "codex_minutes": int(week.get("codex_minutes") or 0),
               "prs_merged": int(week.get("prs_merged") or 0),
               "previous_minutes": int(before.get("total_minutes") or 0),
               # The hours always cover the last seven full days; mid-week that is more than this week.
               "last_7_days": first != today - timedelta(days=7)}
    moved = []
    for project in projection.get("projects") or []:
        claude = sum((project.get("daily_claude_minutes") or [])[-8:-1])
        codex = sum((project.get("daily_codex_minutes") or [])[-8:-1])
        merged = sum((project.get("daily_prs_merged") or [])[-8:-1])
        if not (claude or codex or merged):
            continue
        summary = project.get("last_summary") or {}
        bullet = (summary.get("bullets") or [None])[0]
        # Only a line written about the reported week, not today's summary.
        if not (bullet and (today - timedelta(days=7)).isoformat() <= str(summary.get("date") or "") <= last.isoformat()):
            bullet = None
        moved.append({"main": bool(project.get("main")), "name": project.get("name") or project.get("id"),
                      "minutes": claude + codex, "claude_minutes": claude, "codex_minutes": codex,
                      "prs_merged": merged, "summary": bullet})
    moved.sort(key=lambda item: (item["main"], item["minutes"]), reverse=True)
    waiting = [item["text"] for item in todo if not item.get("done")]
    return {"week": first.isoformat(), "from": first.isoformat(), "to": last.isoformat(),
            "title": f"Итоги недели · {day_label(first)} – {day_label(last)}",
            "numbers": numbers, "directions": blocks or [], "moved": moved, "waiting": waiting}


def render(data: dict[str, Any]) -> str:
    """The digest text. Only real numbers: a week without data says so instead of showing zeros."""
    lines = [data["title"], ""]
    numbers = data["numbers"]
    total = numbers["total_minutes"]
    if not total and not numbers["prs_merged"]:
        lines.append("За неделю работы агентов в данных нет.")
    else:
        trend = f" (неделей раньше {hours(numbers['previous_minutes'])})" if numbers["previous_minutes"] else ""
        span = " за 7 дней" if numbers.get("last_7_days") else ""
        lines.append(f"Работа агентов{span}: {hours(total)}{trend}")
        lines.append(f"Claude Code {hours(numbers['claude_minutes'])} · Codex {hours(numbers['codex_minutes'])}")
        lines.append(f"Слито PR: {numbers['prs_merged']}")
    if data["directions"]:
        lines += ["", "По направлениям:"] + direction_lines(data["directions"])[1:]
    moved = data["moved"]
    if moved:
        lines += ["", "Что сдвинулось:"]
        for item in moved[:MAX_PROJECTS]:
            split = " / ".join(part for part in (
                f"Claude Code {hours(item['claude_minutes'])}" if item["claude_minutes"] else "",
                f"Codex {hours(item['codex_minutes'])}" if item["codex_minutes"] else "") if part)
            extra = f", PR: {item['prs_merged']}" if item["prs_merged"] else ""
            lines.append(f"• {item['name']} — {hours(item['minutes'])}" + (f" ({split})" if split else "") + extra)
            if item["summary"]:
                lines.append(f"  {item['summary']}")
        if len(moved) > MAX_PROJECTS:
            lines.append(f"• и ещё {len(moved) - MAX_PROJECTS}")
    waiting = data["waiting"]
    if waiting:
        lines += ["", f"Ждёт тебя ({len(waiting)}):"]
        lines += [f"• {text}" for text in waiting[:MAX_TODO]]
        if len(waiting) > MAX_TODO:
            lines.append(f"• и ещё {len(waiting) - MAX_TODO}")
    lines += ["", SITE + "?tab=weekly"]
    return "\n".join(lines)


def compose(projection: dict[str, Any], todo: list[dict[str, Any]], today: date,
            blocks: list[dict[str, Any]] | None = None) -> str:
    return render(digest_data(projection, todo, today, blocks))


def chunks(text: str, limit: int = TELEGRAM_LIMIT) -> list[str]:
    """Telegram takes 4096 characters a message; split on line breaks."""
    parts, current = [], ""
    for line in text.split("\n"):
        line = line[:limit]
        if current and len(current) + 1 + len(line) > limit:
            parts.append(current)
            current = line
        else:
            current = f"{current}\n{line}" if current else line
    return parts + [current] if current else parts


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
        manual: bool = False, send_now: bool = False, inboxes: list[Path] | None = None,
        opener=urllib.request.urlopen) -> dict[str, Any]:
    """Build the week, save it, and send it.

    The Monday job (default) sends the finished week once. ``manual`` is «Собрать сводку сейчас»: it saves
    the week so far and sends only with ``send_now``; it never marks the week as sent, so Monday still
    sends the whole week."""
    now = now or datetime.now(timezone.utc)
    today = now.astimezone().date()
    week_start = report_week(today)
    week = week_start.isoformat()
    status_path = out / "status.json"
    try:
        status = json.loads(status_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        status = {}
    # Today is in the window but not in the totals: 15 days give two complete weeks.
    projection = work_projection(root, now=now, days=15, owner=True)
    todo = load_todo(todo_file)
    blocks = group_by_direction(collect_notes(week_start, inboxes))
    data = digest_data(projection, todo, today, blocks)
    text = render(data)
    stamp = now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    write(out / f"{week}.md", text + "\n")
    write(out / f"{week}.json", json.dumps({**data, "text": text, "built_at": stamp}, ensure_ascii=False, indent=2))
    result: dict[str, Any] = {"week": week, "at": stamp, "file": str(out / f"{week}.md"),
                              "notes": sum(len(block["projects"]) for block in blocks)}
    if dry_run:
        result.update(ok=True, sent=False, reason="dry_run")
        print(text)
        return result
    if manual and not send_now:
        result.update(ok=True, sent=False, reason="built")
    elif status.get("sent_week") == week and not force and not manual:
        result.update(ok=True, sent=False, reason="already_sent")
    else:
        config = load_config(config_file)
        if config is None:
            result.update(ok=False, sent=False, reason="telegram_not_configured")
        else:
            try:
                for part in chunks(text):
                    send(config, part, opener)
                result.update(ok=True, sent=True)
                if not manual:
                    result["sent_week"] = week
            except (OSError, ValueError, RuntimeError, urllib.error.URLError) as error:
                reason = str(error).replace(config["bot_token"], "[token]")
                result.update(ok=False, sent=False, reason=reason[:200])
    if manual:
        status["last_manual"] = {key: value for key, value in result.items() if key != "file"}
    else:
        status.update({key: value for key, value in result.items() if key != "file"})
        if not result.get("sent"):
            status.pop("sent", None)
    write(status_path, json.dumps(status, ensure_ascii=False, indent=2))
    result["text"] = text
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--force", action="store_true", help="send this week again")
    parser.add_argument("--dry-run", action="store_true", help="print the text, send nothing")
    parser.add_argument("--now", action="store_true", help="build the week so far and save it (Jarvis, the page)")
    parser.add_argument("--send", action="store_true", help="with --now: also send it to Telegram")
    parser.add_argument("--text", action="store_true", help="print only the text (for Jarvis)")
    args = parser.parse_args(argv)
    result = run(force=args.force, dry_run=args.dry_run, manual=args.now, send_now=args.send)
    if args.text:
        print(result.get("text", ""))
    elif not args.dry_run:
        print(json.dumps({key: value for key, value in result.items() if key != "text"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
