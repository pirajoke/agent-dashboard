#!/usr/bin/env python3
"""List the Claude Code and Codex sessions open right now, for «Сессии» in Агенты (Mark 2026-10-25).

Mark runs many sessions at once (Claude Code, Codex, the ChatGPT app's Codex) and wants to see in one
place which are working, which are done and wait for him, and to jump into each one.

Tokenless, runs every minute on each Mac (launchd ``com.pirajoke.live-sessions``). It reads only the
session logs written to in the last ``--hours`` hours, and for each session keeps: a title, the
project, where it runs, its state, the time of its last step, a short redacted last reply, and how
to open it (a claude.ai link when the session has one, ``codex://threads/<id>`` for Codex, and the
resume command for the terminal). Output: ``~/.agent-bridge/live-sessions/<machine>.json``; other
Macs send theirs to the Mac mini with ``--push-to``. The dashboard server serves them to the owner
only (``/api/live-sessions``).

State, read from the last steps of the log:
- ``working``: the agent is in the middle of a turn;
- ``approve``: a tool call has been waiting for its result for a while, most often a permission
  question in the terminal (a long command looks the same, so the page says «наверное»);
- ``waiting``: the turn is over: the agent answered and waits for Mark;
- ``stopped``: a turn with no step for ``STALLED_AFTER`` (crashed, closed or interrupted).
Whether a finished turn really needs Mark is decided by the dashboard from ``ask``, the end of the
last reply (where an agent puts its question); ``approval`` says what a tool call waits for.
Sessions without a step for ``--hours`` hours are left out: nothing says when a terminal is closed.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from daily_work_collector import (  # noqa: E402
    CLAUDE_DIRS, CODEX_DIRS, DEFAULT_OUT, HOME, SUMMARIZER_DIRNAME, iso_z, machine_name, normalize_cwd,
    parse_ts, project_name, redact_command, redact_topic, repo_for_cwd, write_json)

SCHEMA = 1
DEFAULT_LIVE_OUT = HOME / ".agent-bridge" / "live-sessions"
LOOKBACK_HOURS = 12
# A tool call without its result after this long is most likely a permission question.
APPROVE_AFTER = timedelta(minutes=2)
# A turn with no new step for this long has stopped (crashed, closed or interrupted).
STALLED_AFTER = timedelta(minutes=15)
HEAD_BYTES = 256 * 1024
TAIL_BYTES = 768 * 1024
REPLY_LIMIT = 280
# The end of the last reply, where an agent puts the question it asks.
ASK_CHARS = 400
MAX_SESSIONS = 60
CLAUDE_LINK_RE = re.compile(r"https://claude\.ai/code/session_[A-Za-z0-9_-]{8,80}")
# Messages the harness wraps around a session, not something Mark asked.
WRAPPER_PREFIXES = ("[", "<", "Caveat:", "This session is being continued")
TOOL_ACTIONS = {"Edit": "Разрешить правку файла", "MultiEdit": "Разрешить правку файла",
                "Write": "Разрешить запись файла", "NotebookEdit": "Разрешить правку файла",
                "WebFetch": "Разрешить открыть адрес", "exec": "Разрешить команду"}
SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_.-]{6,80}$")
CLAUDE_APPS = {"cli": "Терминал", "claude-desktop": "Приложение Claude", "claude-vscode": "VS Code",
               "remote": "Claude в облаке"}


def read_lines(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """The first and the last records of a log; a big log is read only at both ends."""
    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            if size <= HEAD_BYTES + TAIL_BYTES:
                return [], _records(handle.read())
            head = handle.read(HEAD_BYTES)
            handle.seek(size - TAIL_BYTES)
            tail = handle.read()
    except OSError:
        return [], []
    # Cut the broken line at each end.
    return _records(head.rsplit(b"\n", 1)[0]), _records(tail.split(b"\n", 1)[-1])


def _records(blob: bytes) -> list[dict[str, Any]]:
    records = []
    for line in blob.decode("utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict):
            records.append(record)
    return records


def _claude_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    return " ".join(part.get("text", "") for part in content
                    if isinstance(part, dict) and part.get("type") == "text" and isinstance(part.get("text"), str))


def _state(last_kind: str | None, last_at: datetime, now: datetime, pending: bool) -> str:
    """last_kind: "reply" (the turn ended), "tool" (a tool call is out) or "step" (anything mid-turn)."""
    if last_kind == "reply":
        return "waiting"
    if pending and last_kind == "tool":
        return "approve" if now - last_at >= APPROVE_AFTER else "working"
    return "stopped" if now - last_at >= STALLED_AFTER else "working"


def ask_tail(text: object) -> str | None:
    """The redacted end of a reply, cut at a sentence start."""
    if not isinstance(text, str):
        return None
    line = " ".join(text.split())
    if len(line) > ASK_CHARS:
        line = line[-ASK_CHARS:]
        cut = re.search(r"[.!?…]\s+", line)
        line = line[cut.end():] if cut else line
    return redact_topic(line, ASK_CHARS + 1)


def tool_ask(name: object, data: object) -> str | None:
    """What a tool call that waits for permission is about to do, in a few words."""
    data = data if isinstance(data, dict) else {}
    command = data.get("command") or data.get("cmd")
    if isinstance(command, list):
        command = " ".join(str(part) for part in command)
    if isinstance(command, str) and command.strip():
        return "Разрешить команду: " + redact_command(command)
    action = TOOL_ACTIONS.get(str(name), f"Разрешить {name}" if isinstance(name, str) and name else None)
    target = data.get("file_path") or data.get("path") or data.get("url")
    if action and isinstance(target, str) and target:
        return f"{action}: " + redact_command(Path(target).name if "://" not in target else target)
    return action


def find_claude_link(path: Path) -> str | None:
    """The claude.ai address of a session with Remote Control or one that runs in the cloud."""
    found = CLAUDE_LINK_RE.search(_read(path).decode("utf-8", errors="replace"))
    return found.group(0) if found else None


def parse_claude(path: Path, now: datetime, links: dict[str, str | None] | None = None) -> dict[str, Any] | None:
    head, tail = read_lines(path)
    records = head + tail
    title = custom = topic = cwd = branch = entry = link = reply = ask = None
    started = last_at = None
    last_kind: str | None = None
    pending: set[str] = set()
    asks: dict[str, str | None] = {}
    session_id = path.stem
    for record in records:
        kind = record.get("type")
        if kind == "custom-title":
            # A name Mark gave with /rename wins over Claude's own title.
            custom = redact_topic(record.get("customTitle")) or custom
            continue
        if kind == "ai-title":
            title = redact_topic(record.get("aiTitle")) or title
            continue
        if kind == "summary":
            title = title or redact_topic(record.get("summary"))
            continue
        if kind == "attachment":
            found = CLAUDE_LINK_RE.search(json.dumps(record.get("attachment"), ensure_ascii=False))
            link = found.group(0) if found else link
        if record.get("isSidechain") or kind not in {"user", "assistant"}:
            continue
        moment = parse_ts(record.get("timestamp"))
        if moment is None:
            continue
        session_id = str(record.get("sessionId") or session_id)
        started = started or moment
        last_at = moment
        cwd = record.get("cwd") if isinstance(record.get("cwd"), str) else cwd
        branch = record.get("gitBranch") or branch
        entry = record.get("entrypoint") or entry
        message = record.get("message") if isinstance(record.get("message"), dict) else {}
        content = message.get("content")
        if kind == "assistant":
            uses = [part.get("id") for part in content or [] if isinstance(part, dict) and part.get("type") == "tool_use"]
            pending.update(str(use) for use in uses if use)
            for part in content or []:
                if isinstance(part, dict) and part.get("type") == "tool_use" and part.get("id"):
                    asks[str(part["id"])] = tool_ask(part.get("name"), part.get("input"))
            raw = _claude_text(content)
            text = redact_topic(raw, REPLY_LIMIT)
            if text:
                reply, ask = text, ask_tail(raw)
            if uses:
                last_kind = "tool"
            elif message.get("stop_reason") in {"end_turn", "stop_sequence", "max_tokens"} or (text and not uses):
                last_kind = "reply"
            else:
                last_kind = "step"
        else:
            results = [part.get("tool_use_id") for part in content if isinstance(part, dict)
                       and part.get("type") == "tool_result"] if isinstance(content, list) else []
            pending.difference_update(str(result) for result in results)
            text = _claude_text(content)
            if not results and record.get("isMeta"):
                continue
            if "[Request interrupted by user" in text:
                last_kind = "reply"
                continue
            if not results and not text.lstrip().startswith(WRAPPER_PREFIXES):
                topic = topic or redact_topic(text)
            last_kind = "step"
    if last_at is None or (entry or "").startswith("sdk"):
        # Headless runs (day summaries, the agent task runner) are not sessions Mark talks to.
        return None
    if link is None and links is not None:
        # The link sits in the middle of a long log: a found link is kept, and a log without one is
        # searched again only once it has grown (Remote Control can be switched on mid-session).
        known = links.get(session_id)
        if isinstance(known, str):
            link = known
        else:
            size = _size(path)
            if not isinstance(known, dict) or known.get("size") != size:
                link = find_claude_link(path)
                links[session_id] = link or {"size": size}
    app = "Claude в облаке" if (entry or "").startswith("remote") else CLAUDE_APPS.get(entry or "", "Терминал")
    state = _state(last_kind, last_at, now, bool(pending))
    approval = next((asks[use] for use in pending if asks.get(use)), None) if state == "approve" else None
    return _session("claude", session_id, custom or title or topic, cwd, branch, app,
                    started, last_at, state, reply, link, ask, approval)


def parse_codex(path: Path, now: datetime, names: dict[str, str]) -> dict[str, Any] | None:
    head, tail = read_lines(path)
    session_id = "-".join(path.stem.split("-")[-5:])  # rollout-<time>-<uuid>
    topic = cwd = branch = reply = ask = None
    app = "Терминал"
    started = last_at = None
    last_kind: str | None = None
    pending: set[str] = set()
    approval = False
    approval_ask: str | None = None
    for record in head + tail:
        payload = record.get("payload") if isinstance(record.get("payload"), dict) else {}
        kind = record.get("type")
        if kind == "session_meta":
            source = payload.get("source")
            if isinstance(source, dict) and "subagent" in source or payload.get("agent_path"):
                return None  # a helper inside another session
            originator = str(payload.get("originator") or "").lower()
            if originator == "codex_exec" or source == "exec":
                return None  # headless runs
            if "chatgpt" in originator:
                app = "ChatGPT"
            elif "desktop" in originator or "app" in originator:
                app = "Приложение Codex"
            elif "vscode" in originator:
                app = "VS Code"
            session_id = str(payload.get("id") or session_id)
            cwd = normalize_cwd(payload.get("cwd")) or cwd
            git = payload.get("git") if isinstance(payload.get("git"), dict) else {}
            branch = git.get("branch") or branch
            continue
        moment = parse_ts(record.get("timestamp"))
        if moment is None:
            continue
        if kind == "turn_context" and isinstance(payload.get("cwd"), str):
            cwd = cwd or normalize_cwd(payload["cwd"])
        item = payload.get("type")
        if kind == "event_msg":
            if item in {"task_complete", "turn_aborted"}:
                last_kind, approval = "reply", False
                pending.clear()
                text = redact_topic(payload.get("last_agent_message"), REPLY_LIMIT)
                if text:
                    reply, ask = text, ask_tail(payload.get("last_agent_message"))
            elif item in {"exec_approval_request", "apply_patch_approval_request", "request_user_input"}:
                approval = True
                if item == "apply_patch_approval_request":
                    approval_ask = "Разрешить правку файлов"
                elif item == "exec_approval_request":
                    approval_ask = tool_ask("exec", payload) or redact_topic(payload.get("reason"), REPLY_LIMIT)
                else:
                    approval_ask = redact_topic(payload.get("question") or payload.get("prompt"), REPLY_LIMIT)
            elif item == "user_message":
                topic = topic or redact_topic(payload.get("message"))
                last_kind, approval = "step", False
            elif item == "agent_message" and redact_topic(payload.get("message"), REPLY_LIMIT):
                reply, ask = redact_topic(payload.get("message"), REPLY_LIMIT), ask_tail(payload.get("message"))
            elif item == "task_started":
                last_kind = "step"
        elif kind == "response_item":
            if item in {"function_call", "custom_tool_call", "local_shell_call"}:
                pending.add(str(payload.get("call_id") or payload.get("id") or len(pending)))
                last_kind = "tool"
            elif item in {"function_call_output", "custom_tool_call_output"}:
                pending.discard(str(payload.get("call_id")))
                last_kind, approval = "step", False
            elif item == "message" and payload.get("role") == "user":
                text = " ".join(part.get("text", "") for part in payload.get("content") or []
                                if isinstance(part, dict) and isinstance(part.get("text"), str))
                topic = topic or redact_topic(text)
            elif item == "message" and payload.get("role") == "assistant":
                text = " ".join(part.get("text", "") for part in payload.get("content") or []
                                if isinstance(part, dict) and isinstance(part.get("text"), str))
                if redact_topic(text, REPLY_LIMIT):
                    reply, ask = redact_topic(text, REPLY_LIMIT), ask_tail(text)
                # Rollouts with response items only mark the answer that ends the turn as final.
                if payload.get("channel") == "final" or payload.get("phase") in {"final", "final_answer"}:
                    last_kind = "reply"
                    pending.clear()
            elif last_kind != "tool":
                last_kind = "step"
        started = started or moment
        last_at = moment
    if last_at is None:
        return None
    # Codex logs every permission question as its own event, so a call that is just out long is a long
    # command (scheduled runs such as Job Radar), not a question for Mark.
    state = "approve" if approval and last_kind != "reply" else _state(last_kind, last_at, now, False)
    return _session("codex", session_id, names.get(session_id) or topic, cwd, branch, app, started, last_at,
                    state, reply, None, ask, approval_ask if state == "approve" else None)


def _session(tool: str, session_id: str, title: str | None, cwd: str | None, branch: object, app: str,
             started: datetime | None, last_at: datetime, state: str, reply: str | None,
             link: str | None, ask: str | None = None, approval: str | None = None) -> dict[str, Any] | None:
    if not SAFE_ID_RE.match(session_id):
        return None
    repo = repo_for_cwd(cwd)
    if tool == "claude":
        resume = f"claude --resume {session_id}"
    else:
        resume = f"codex resume {session_id}"
        link = f"codex://threads/{session_id}"
    if cwd and cwd != str(HOME):
        resume = f"cd {_quote(cwd)} && {resume}"
    return {
        "id": session_id,
        "tool": tool,
        "app": app,
        "title": title or f"Сессия в {project_name(cwd, repo)}",
        "project": project_name(cwd, repo),
        "branch": branch if isinstance(branch, str) and branch and branch not in {"main", "master", "HEAD"} else None,
        "state": state,
        "started_at": iso_z(started or last_at),
        "last_at": iso_z(last_at),
        "reply": reply,
        "ask": ask,
        "approval": approval,
        "link": link,
        "resume": resume,
    }


def _quote(path: str) -> str:
    return path if re.fullmatch(r"[A-Za-z0-9_./~-]+", path) else "'" + path.replace("'", "'\\''") + "'"


def codex_thread_names(home: Path = HOME) -> dict[str, str]:
    """Titles the Codex app gives its chats, when it keeps them (session_index.jsonl)."""
    names: dict[str, str] = {}
    for record in _records(_read(home / ".codex" / "session_index.jsonl")):
        name = redact_topic(record.get("thread_name") or record.get("title"))
        if isinstance(record.get("id"), str) and name:
            names[record["id"]] = name
    return names


def _size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return -1


def _read(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError:
        return b""


def recent_logs(roots: list[Path], pattern: str, since: datetime) -> list[Path]:
    found = []
    for root in roots:
        if not root.is_dir():
            continue
        for path in root.rglob(pattern):
            try:
                if path.stat().st_mtime >= since.timestamp():
                    found.append(path)
            except OSError:
                continue
    return found


def collect(now: datetime, hours: int, skip_dir: Path, links: dict[str, str | None] | None = None) -> list[dict[str, Any]]:
    since = now - timedelta(hours=hours)
    sessions: list[dict[str, Any]] = []
    for path in recent_logs(CLAUDE_DIRS, "*.jsonl", since):
        if "subagents" in path.parts:
            continue
        session = parse_claude(path, now, links)
        if session:
            sessions.append(session)
    names = codex_thread_names()
    for path in recent_logs(CODEX_DIRS[:1], "rollout-*.jsonl", since):
        session = parse_codex(path, now, names)
        if session:
            sessions.append(session)
    skip = str(skip_dir)
    sessions = [s for s in sessions if parse_ts(s["last_at"]) >= since and skip not in s["resume"]]
    # One log can hold a resumed session twice; keep its latest view.
    latest: dict[tuple[str, str], dict[str, Any]] = {}
    for session in sessions:
        key = (session["tool"], session["id"])
        if key not in latest or latest[key]["last_at"] < session["last_at"]:
            latest[key] = session
    return sorted(latest.values(), key=lambda s: s["last_at"], reverse=True)[:MAX_SESSIONS]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_LIVE_OUT)
    parser.add_argument("--machine", default=None, help="machine label, default: hostname")
    parser.add_argument("--hours", type=int, default=LOOKBACK_HOURS)
    parser.add_argument("--push-to", default=None, help="ssh host that receives this machine's file")
    parser.add_argument("--remote-out", default=".agent-bridge/live-sessions")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    now = datetime.now(timezone.utc)
    machine = machine_name(args.machine)
    # Links found earlier, so a long log is searched once. Kept for the sessions still listed.
    links_file = args.out / f".{machine}-links.json"
    try:
        links = json.loads(links_file.read_text(encoding="utf-8"))
        links = links if isinstance(links, dict) else {}
    except (OSError, ValueError):
        links = {}
    sessions = collect(now, args.hours, DEFAULT_OUT.expanduser() / SUMMARIZER_DIRNAME, links)
    listed = {s["id"] for s in sessions}
    write_json(links_file, {key: value for key, value in links.items() if key in listed})
    target = args.out / f"{machine}.json"
    write_json(target, {"schema": SCHEMA, "machine": machine, "collected_at": iso_z(now), "sessions": sessions})
    result: dict[str, Any] = {"ok": True, "machine": machine, "sessions": len(sessions)}
    if args.push_to:
        try:
            subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", args.push_to,
                            f"mkdir -p {args.remote_out} && chmod 700 {args.remote_out}"], check=True, timeout=30)
            subprocess.run(["scp", "-q", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", str(target),
                            f"{args.push_to}:{args.remote_out.rstrip('/')}/"], check=True, timeout=60)
            result["pushed"] = True
        except (OSError, subprocess.SubprocessError):
            result.update(pushed=False, ok=False)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
