#!/usr/bin/env python3
"""Evening summary of the day's work, sent to Mark in Telegram by 22:00 (Mark 2026-10-23).

Runs on the Mac mini (launchd ``com.pirajoke.daily-digest``, every day at 21:30). It first refreshes
the day: collects the latest Claude Code / Codex sessions and GitHub PRs and asks the summarizer to
retell today again, then writes a short Russian message: the date, hours of work, merged PRs, and per
project what the agents did, what Mark did, what is next and dated deadlines, then the «Ждёт тебя» list.
Everything comes from the same files as MAIN MANAGER (``work_projection`` and Claude's day summaries);
nothing is made up, a day without work says so.

The text is always saved to ``~/.agent-bridge/daily-digest/<day>.md``. It is sent with the same
Telegram settings as the Monday digest (``~/.agent-bridge/telegram_digest.json``, the JARVIS bot);
without them the run records ``telegram_not_configured``. A day is sent once; ``--force`` sends it again.
"""
from __future__ import annotations

import argparse
import html
import json
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))

from dashboard_builder.daily_work import _details, load_summaries, work_projection  # noqa: E402
from weekly_digest import (CONFIG_FILE, DAILY_WORK_DIR, MONTHS, OWNER_TODO_FILE, SITE, hours,  # noqa: E402
                           load_config, load_todo, write)

HERE = Path(__file__).resolve().parent
OUT_DIR = Path.home() / ".agent-bridge" / "daily-digest"
MONTHS_FULL = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября",
               "ноября", "декабря"]
WEEKDAYS = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
EMOJI = {"command-center": "🧭", "financial": "💼", "mydictionary": "📚", "health": "🩺", "context-news": "📰",
         "ai-singularity": "🌀", "accountable": "🧾", "jarvis": "🤖"}
MAX_PROJECTS = 8
PR_WEIGHT = 20  # minutes a merged PR counts for when ordering projects
MAX_PRS = 3
MAX_TODO = 5
LIMIT = 3900  # Telegram allows 4096 characters per message
RULE = "━━━━━━━━━━━━"
MACHINE = "mac-mini"  # the label install_daily_work_collector.sh gives this Mac's session files


def esc(value: object) -> str:
    return html.escape(str(value or "").strip(), quote=False)


def date_label(day: date) -> str:
    return f"{day.day} {MONTHS_FULL[day.month - 1]} {day.year}, {WEEKDAYS[day.weekday()]}"


def short_date(value: str) -> str:
    try:
        day = date.fromisoformat(value)
    except ValueError:
        return esc(value)
    return f"{day.day} {MONTHS[day.month - 1]}"


def project_block(project: dict[str, Any], details: dict[str, Any] | None) -> str:
    """One project: name, time and PRs, then Claude's lead and bullets; PR titles when not retold yet."""
    details = details or {}
    merged = project.get("merged") or []
    meta = [hours(project["minutes"])] if project.get("minutes") else []
    if merged:
        meta.append(f"✅ PR: {len(merged)}")
    emoji = EMOJI.get(project.get("id"), "📁")
    lines = [f"{emoji} <b>{esc(project.get('name') or project.get('id'))}</b>" + (f" · {' · '.join(meta)}" if meta else "")]
    if details.get("lead"):
        lines.append(f"<i>{esc(details['lead'])}</i>")
    agents = details.get("agents") or ([] if details else project.get("bullets") or [])
    if agents:
        lines.append("🤖 Сделали агенты:")
        lines += [f"• {esc(line)}" for line in agents]
    if details.get("you"):
        lines.append("🙋 Ты:")
        lines += [f"• {esc(line)}" for line in details["you"]]
    if not agents and not details.get("you"):
        if merged:
            lines += [f"• {esc(pr.get('title'))} (#{pr.get('number')})" for pr in merged[:MAX_PRS]]
            if len(merged) > MAX_PRS:
                lines.append(f"• и ещё {len(merged) - MAX_PRS}")
        else:
            lines.append("• Работа шла, Claude ещё не пересказал её")
    if details.get("next"):
        lines.append("👉 Дальше: " + "; ".join(esc(line) for line in details["next"]))
    for deadline in details.get("deadlines") or []:
        lines.append(f"⏰ {short_date(deadline['date'])}: {esc(deadline['what'])}")
    return "\n".join(lines)


def fold_twins(projects: list[dict[str, Any]], summary: dict[str, Any] | None) -> list[dict[str, Any]]:
    """A folder seen both in ChatGPT and in Claude Code / Codex («ChatGPT · DOCXX» and «DOCXX») is one project:
    a twin Claude did not retell and without PRs adds its time to the other one instead of its own block."""
    def bare(name: object) -> str:
        return str(name or "").removeprefix("ChatGPT · ").strip().lower()

    kept = []
    for project in projects:
        told = bool(project.get("merged") or project.get("bullets") or _details(summary, project.get("id")))
        twin = next((other for other in projects if other is not project and bare(other.get("name")) == bare(project.get("name"))
                     and (other.get("merged") or other.get("bullets") or _details(summary, other.get("id")))), None)
        if not told and twin is not None:
            twin["minutes"] = (twin.get("minutes") or 0) + (project.get("minutes") or 0)
        else:
            kept.append(project)
    return kept


def compose(day_entry: dict[str, Any] | None, summary: dict[str, Any] | None, todo: list[dict[str, Any]],
            today: date) -> list[str]:
    """The message, split into Telegram-sized parts. Only real numbers; an empty day says so."""
    head = [f"📅 <b>Резюме дня · {date_label(today)}</b>", ""]
    blocks: list[tuple[str, bool]] = []  # (text, starts with a rule line)
    entry = day_entry or {}
    projects = fold_twins([dict(p) for p in entry.get("projects") or [] if not p.get("quiet")], summary)
    if not projects:
        head.append("Сегодня работы агентов в данных нет.")
    else:
        total = int(entry.get("total_minutes") or 0)
        claude, codex = int(entry.get("claude_minutes") or 0), int(entry.get("codex_minutes") or 0)
        split = " · ".join(part for part in (f"Claude Code {hours(claude)}" if claude else "",
                                             f"Codex {hours(codex)}" if codex else "") if part)
        if total:
            # Total is wall-clock time; Claude Code and Codex often run at the same time, so their sum is larger.
            head.append(f"⏱ Работа: <b>{hours(total)}</b>" + (f" ({split}" + (", шли параллельно)" if claude + codex > total else ")")
                                                            if split else ""))
        merged = int(entry.get("prs_merged") or 0)
        head.append(f"✅ Слито PR: <b>{merged}</b> · 📂 Проектов: <b>{len(projects)}</b>")
        if isinstance((summary or {}).get("day"), str) and summary["day"].strip():
            head += ["", f"💬 {esc(summary['day'])}"]
        # Biggest day first: time plus merged PRs (cloud sessions leave PRs without local hours).
        projects.sort(key=lambda p: -((p.get("minutes") or 0) + PR_WEIGHT * len(p.get("merged") or [])))
        for project in projects[:MAX_PROJECTS]:
            blocks.append((project_block(project, _details(summary, project.get("id"))), True))
        rest = projects[MAX_PROJECTS:]
        if rest:
            blocks.append(("📁 Ещё: " + ", ".join(esc(p.get("name")) for p in rest), False))
    waiting = [item for item in todo if not item.get("done")]
    if waiting:
        lines = [f"📌 <b>Ждёт тебя ({len(waiting)})</b>"] + [f"• {esc(item['text'])}" for item in waiting[:MAX_TODO]]
        if len(waiting) > MAX_TODO:
            lines.append(f"• и ещё {len(waiting) - MAX_TODO}")
        blocks.append(("\n".join(lines), True))
    blocks.append((f"🔗 {SITE}", False))
    parts, current = [], "\n".join(head)
    for block, ruled in blocks:
        piece = f"\n\n{RULE}\n{block}" if ruled else f"\n\n{block}"
        if len(current) + len(piece) > LIMIT:
            parts.append(current)
            current = block[:LIMIT]
        else:
            current += piece
    parts.append(current)
    return parts


def send(config: dict[str, str], text: str, opener=urllib.request.urlopen) -> None:
    body = json.dumps({"chat_id": config["chat_id"], "text": text, "parse_mode": "HTML",
                       "disable_web_page_preview": True}).encode()
    request = urllib.request.Request(f"https://api.telegram.org/bot{config['bot_token']}/sendMessage", data=body,
                                     headers={"Content-Type": "application/json"}, method="POST")
    with opener(request, timeout=20) as response:
        answer = json.loads(response.read() or b"{}")
    if not answer.get("ok"):
        raise RuntimeError(f"telegram_refused: {str(answer.get('description') or '')[:120]}")


def refresh(day: str, runner: Callable[..., Any] = subprocess.run) -> list[str]:
    """Fresh sessions and PRs, then today's summary again. A failed step is noted, the digest still goes."""
    problems = []
    steps = [("collector", [sys.executable, str(HERE / "daily_work_collector.py"), "--machine", MACHINE, "--github"], 600),
             ("summarizer", [sys.executable, str(HERE / "daily_work_summarizer.py"), "--day", day], 900)]
    for name, command, timeout in steps:
        try:
            done = runner(command, cwd=str(HERE), capture_output=True, text=True, timeout=timeout)
            if done.returncode != 0:
                problems.append(f"{name}_exit_{done.returncode}")
        except (OSError, subprocess.SubprocessError) as error:
            problems.append(f"{name}_{type(error).__name__}")
    return problems


def run(*, now: datetime | None = None, root: Path = DAILY_WORK_DIR, todo_file: Path = OWNER_TODO_FILE,
        out: Path = OUT_DIR, config_file: Path = CONFIG_FILE, force: bool = False, dry_run: bool = False,
        fresh: bool = True, opener=urllib.request.urlopen, runner: Callable[..., Any] = subprocess.run) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    today = now.astimezone().date()
    day = today.isoformat()
    status_path = out / "status.json"
    try:
        status = json.loads(status_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        status = {}
    already = status.get("sent_day") == day and not force
    problems = refresh(day, runner) if fresh and not already and not dry_run else []
    projection = work_projection(root, now=now, days=7, owner=True, edition=True, selected=day)
    day_entry = next((item for item in projection.get("feed") or [] if item.get("date") == day), None)
    summary = load_summaries(root, [day]).get(day)
    parts = compose(day_entry, summary, load_todo(todo_file), today)
    write(out / f"{day}.md", "\n\n".join(parts) + "\n")
    result: dict[str, Any] = {"day": day, "at": now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                              "parts": len(parts), "refresh_problems": problems}
    if dry_run:
        result.update(ok=True, sent=False, reason="dry_run")
        print("\n\n----\n\n".join(parts))
        return result
    if already:
        result.update(ok=True, sent=False, reason="already_sent")
    else:
        config = load_config(config_file)
        if config is None:
            result.update(ok=False, sent=False, reason="telegram_not_configured")
        else:
            try:
                for part in parts:
                    send(config, part, opener)
                result.update(ok=True, sent=True, sent_day=day)
            except (OSError, ValueError, RuntimeError, urllib.error.URLError) as error:
                reason = str(error).replace(config["bot_token"], "[token]")
                result.update(ok=False, sent=False, reason=reason[:200])
    status.update(result)
    if not result.get("sent"):
        status.pop("sent", None)
    write(status_path, json.dumps(status, ensure_ascii=False, indent=2))
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--force", action="store_true", help="send today again")
    parser.add_argument("--dry-run", action="store_true", help="print the text, send nothing")
    parser.add_argument("--no-refresh", action="store_true", help="use the data as it is, skip collector and summarizer")
    args = parser.parse_args(argv)
    result = run(force=args.force, dry_run=args.dry_run, fresh=not args.no_refresh)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
