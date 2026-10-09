#!/usr/bin/env python3
"""Collect daily Claude Code / Codex work and GitHub outcomes for the Work section.

Tokenless: reads local session logs and the GitHub REST API, never calls a
model. Each run rewrites the per-day files for the last few days, so the
numbers for "today" fill in through the day and "yesterday" settles.

Session files: ``<out>/sessions/<machine>/<YYYY-MM-DD>.json`` (one per local
calendar day of this machine). GitHub snapshot: ``<out>/github.json``. The
Mac mini runs with ``--github``; other Macs run with ``--push-to <host>`` so
their session files land next to the Mac mini's ones.

Prompt text is reduced to a short, redacted topic line. Raw prompts and
assistant output never leave the machine.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import socket
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator

SCHEMA = 1
HOME = Path.home()
DEFAULT_OUT = HOME / ".agent-bridge" / "daily-work"
CLAUDE_DIRS = [HOME / ".claude" / "projects", HOME / ".config" / "claude" / "projects"]
CODEX_DIRS = [HOME / ".codex" / "sessions", HOME / ".codex" / "archived_sessions"]
GITHUB_TOKEN_FILE = HOME / ".agent-bridge" / "dashboard_github_token"
GITHUB_API = "https://api.github.com"
# Two events of one session closer than this count as continuous work.
IDLE_GAP_SECONDS = 30 * 60
# A lone event (one prompt, one reply) still costs about a minute.
EVENT_SECONDS = 60
TOPIC_LIMIT = 110
REMOTE_RE = re.compile(r"github\.com[:/]+([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?$")
SECRET_PATTERNS = [
    re.compile(r"sk-(?:proj-)?[A-Za-z0-9_-]{20,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9_]{20,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{20,}"),
    re.compile(r"AIza[0-9A-Za-z_-]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{30,}\b"),  # Telegram bot token
    re.compile(r"(?i)\b(api[_ -]?key|token|secret|password|passwd|пароль|секрет)\s*[:=]\s*\S{6,}"),
    re.compile(r"[A-Za-z0-9+/_-]{40,}"),
]
TOPIC_SKIP_PREFIXES = (
    "<", "caveat:", "[request interrupted", "this session is being continued",
    "# agents.md", "# claude.md",
)


# ── small helpers ────────────────────────────────────────────────────────────

def parse_ts(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def iso_z(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def local_day(moment: datetime) -> str:
    return moment.astimezone().date().isoformat()


def redact_topic(text: object) -> str | None:
    if not isinstance(text, str):
        return None
    line = " ".join(text.split())
    if not line or line.lower().startswith(TOPIC_SKIP_PREFIXES):
        return None
    for pattern in SECRET_PATTERNS:
        line = pattern.sub("[скрыто]", line)
    if len(line) > TOPIC_LIMIT:
        line = line[: TOPIC_LIMIT - 1].rstrip() + "…"
    return line


def repo_from_remote(url: object) -> str | None:
    if not isinstance(url, str):
        return None
    match = REMOTE_RE.search(url.strip())
    if not match:
        return None
    return f"{match.group(1)}/{match.group(2)}"


_REMOTE_CACHE: dict[str, str | None] = {}


def repo_for_cwd(cwd: str | None) -> str | None:
    if not cwd:
        return None
    if cwd not in _REMOTE_CACHE:
        repo = None
        if Path(cwd).is_dir():
            try:
                result = subprocess.run(
                    ["git", "-C", cwd, "remote", "get-url", "origin"],
                    capture_output=True, text=True, timeout=5, check=False,
                )
                repo = repo_from_remote(result.stdout) if result.returncode == 0 else None
            except (OSError, subprocess.SubprocessError):
                repo = None
        _REMOTE_CACHE[cwd] = repo
    return _REMOTE_CACHE[cwd]


def project_name(cwd: str | None, repo: str | None) -> str:
    if repo:
        return repo.split("/", 1)[1]
    if cwd:
        name = Path(cwd).name
        if name and Path(cwd) != HOME:
            return name
    return "без проекта"


def active_intervals(times: Iterable[datetime]) -> list[tuple[datetime, datetime]]:
    """Merge event times into work intervals; gaps over IDLE_GAP_SECONDS are breaks."""
    ordered = sorted(times)
    intervals: list[list[datetime]] = []
    for moment in ordered:
        end = moment + timedelta(seconds=EVENT_SECONDS)
        if intervals and (moment - intervals[-1][1]).total_seconds() <= IDLE_GAP_SECONDS:
            intervals[-1][1] = max(intervals[-1][1], end)
        else:
            intervals.append([moment, end])
    return [(start, end) for start, end in intervals]


def interval_minutes(intervals: Iterable[tuple[datetime, datetime]]) -> int:
    return round(sum((end - start).total_seconds() for start, end in intervals) / 60)


def iter_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(record, dict):
                    yield record
    except OSError:
        return


def recent_files(roots: list[Path], pattern: str, since: datetime) -> tuple[list[Path], bool]:
    found = False
    files: list[Path] = []
    cutoff = since.timestamp()
    for root in roots:
        if not root.is_dir():
            continue
        found = True
        for path in root.rglob(pattern):
            try:
                if path.stat().st_mtime >= cutoff:
                    files.append(path)
            except OSError:
                continue
    return files, found


# ── session parsing ──────────────────────────────────────────────────────────

class Session:
    def __init__(self, tool: str, session_id: str) -> None:
        self.tool = tool
        self.session_id = session_id
        self.cwd: str | None = None
        self.repo: str | None = None
        self.branch: str | None = None
        self.topic: str | None = None
        self.summary: str | None = None
        self.events: list[datetime] = []
        self.prompts: list[datetime] = []


def _claude_prompt_text(record: dict[str, Any]) -> str | None:
    message = record.get("message")
    if not isinstance(message, dict) or message.get("role") != "user":
        return None
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts = [part.get("text") for part in content if isinstance(part, dict) and part.get("type") == "text"]
        if texts and not any(isinstance(part, dict) and part.get("type") == "tool_result" for part in content):
            return " ".join(t for t in texts if isinstance(t, str))
    return None


def parse_claude_file(path: Path) -> list[Session]:
    sessions: dict[str, Session] = {}
    summary: str | None = None
    for record in iter_jsonl(path):
        if record.get("type") == "summary":
            summary = redact_topic(record.get("summary")) or summary
            continue
        moment = parse_ts(record.get("timestamp"))
        if moment is None or record.get("isSidechain"):
            continue
        session_id = str(record.get("sessionId") or path.stem)
        session = sessions.setdefault(session_id, Session("claude", session_id))
        session.events.append(moment)
        if isinstance(record.get("cwd"), str):
            session.cwd = record["cwd"]
        branch = record.get("gitBranch")
        if isinstance(branch, str) and branch:
            session.branch = branch
        if record.get("type") == "user" and not record.get("isMeta"):
            text = _claude_prompt_text(record)
            if text is not None:
                topic = redact_topic(text)
                if topic:
                    session.prompts.append(moment)
                    session.topic = session.topic or topic
    for session in sessions.values():
        session.summary = summary
        session.repo = repo_for_cwd(session.cwd)
    return list(sessions.values())


def _codex_prompt_text(record: dict[str, Any]) -> str | None:
    payload = record.get("payload") if isinstance(record.get("payload"), dict) else {}
    if record.get("type") == "event_msg" and payload.get("type") == "user_message":
        message = payload.get("message")
        return message if isinstance(message, str) else None
    # Older rollouts wrote bare message records without the payload envelope.
    if record.get("type") == "message" and record.get("role") == "user":
        content = record.get("content")
        if isinstance(content, list):
            return " ".join(
                part.get("text", "") for part in content
                if isinstance(part, dict) and part.get("type") in {"input_text", "text"}
            )
    return None


def parse_codex_file(path: Path) -> list[Session]:
    session = Session("codex", path.stem)
    for record in iter_jsonl(path):
        payload = record.get("payload") if isinstance(record.get("payload"), dict) else {}
        if record.get("type") == "session_meta" or ("id" in record and "instructions" in record):
            meta = payload or record
            session.session_id = str(meta.get("id") or session.session_id)
            if isinstance(meta.get("cwd"), str):
                session.cwd = meta["cwd"]
            git = meta.get("git") if isinstance(meta.get("git"), dict) else {}
            session.repo = repo_from_remote(git.get("repository_url")) or session.repo
            if isinstance(git.get("branch"), str) and git["branch"]:
                session.branch = git["branch"]
        if record.get("type") == "turn_context" and isinstance(payload.get("cwd"), str):
            session.cwd = session.cwd or payload["cwd"]
        moment = parse_ts(record.get("timestamp"))
        if moment is None:
            continue
        session.events.append(moment)
        text = _codex_prompt_text(record)
        if text is not None:
            topic = redact_topic(text)
            if topic:
                session.prompts.append(moment)
                session.topic = session.topic or topic
    if session.repo is None:
        session.repo = repo_for_cwd(session.cwd)
    return [session] if session.events else []


def collect_sessions(since: datetime) -> tuple[list[Session], dict[str, Any]]:
    sources: dict[str, Any] = {}
    sessions: list[Session] = []
    claude_files, claude_found = recent_files(CLAUDE_DIRS, "*.jsonl", since)
    for path in claude_files:
        sessions.extend(parse_claude_file(path))
    sources["claude"] = {"ok": claude_found, "files": len(claude_files)} if claude_found else {
        "ok": False, "reason": "logs_not_found"}
    codex_files, codex_found = recent_files(CODEX_DIRS, "*.jsonl", since)
    for path in codex_files:
        sessions.extend(parse_codex_file(path))
    sources["codex"] = {"ok": codex_found, "files": len(codex_files)} if codex_found else {
        "ok": False, "reason": "logs_not_found"}
    return sessions, sources


def day_records(sessions: list[Session], days: set[str]) -> dict[str, list[dict[str, Any]]]:
    """Split sessions by local calendar day into privacy-reduced records."""
    by_day: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for session in sessions:
        events_by_day: dict[str, list[datetime]] = defaultdict(list)
        for moment in session.events:
            events_by_day[local_day(moment)].append(moment)
        for day, events in events_by_day.items():
            if day not in days:
                continue
            intervals = active_intervals(events)
            prompts = sum(1 for moment in session.prompts if local_day(moment) == day)
            by_day[day].append({
                "tool": session.tool,
                "session_id": session.session_id,
                "project": project_name(session.cwd, session.repo),
                "repo": session.repo,
                "branch": session.branch,
                "start": iso_z(min(events)),
                "end": iso_z(max(events)),
                "active_minutes": interval_minutes(intervals),
                "prompts": prompts,
                "topic": session.summary or session.topic,
                "intervals": [[iso_z(start), iso_z(end)] for start, end in intervals],
            })
    for records in by_day.values():
        records.sort(key=lambda item: item["start"])
    return by_day


# ── GitHub ───────────────────────────────────────────────────────────────────

def github_token() -> str:
    for name in ("GITHUB_TOKEN", "GH_TOKEN", "JARVIS_GITHUB_TOKEN"):
        token = os.environ.get(name, "").strip()
        if token:
            return token
    try:
        token = GITHUB_TOKEN_FILE.read_text(encoding="utf-8").strip()
        if token:
            return token
    except OSError:
        pass
    try:
        result = subprocess.run(
            ["git", "credential", "fill"], input="protocol=https\nhost=github.com\n\n",
            capture_output=True, text=True, timeout=5, check=False,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    for line in result.stdout.splitlines():
        key, _, value = line.partition("=")
        if key == "password":
            return value.strip()
    return ""


def github_get(path: str, token: str, params: dict[str, str] | None = None) -> Any:
    url = f"{GITHUB_API}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "command-center-daily-work"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.load(response)


def github_search(query: str, token: str, *, kind: str = "issues", pages: int = 3) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for page in range(1, pages + 1):
        data = github_get(f"/search/{kind}", token, {"q": query, "per_page": "100", "page": str(page)})
        batch = data.get("items") if isinstance(data, dict) else None
        if not isinstance(batch, list):
            break
        items.extend(batch)
        if len(batch) < 100:
            break
    return items


def _issue_repo(item: dict[str, Any]) -> str | None:
    url = item.get("repository_url")
    if isinstance(url, str) and "/repos/" in url:
        return url.split("/repos/", 1)[1]
    return None


def _pr_item(item: dict[str, Any]) -> dict[str, Any]:
    pull = item.get("pull_request") if isinstance(item.get("pull_request"), dict) else {}
    return {
        "repo": _issue_repo(item),
        "number": item.get("number"),
        "title": item.get("title"),
        "url": item.get("html_url"),
        "state": item.get("state"),
        "draft": bool(item.get("draft")),
        "created_at": item.get("created_at"),
        "updated_at": item.get("updated_at"),
        "closed_at": item.get("closed_at"),
        "merged_at": pull.get("merged_at"),
    }


def collect_github(login: str, since: datetime, repos: set[str]) -> dict[str, Any]:
    token = github_token()
    start = since.date().isoformat()
    snapshot: dict[str, Any] = {"schema": SCHEMA, "login": login, "since": start, "collected_at": iso_z(datetime.now(timezone.utc))}
    try:
        prs: dict[str, dict[str, Any]] = {}
        for query in (
            f"author:{login} is:pr created:>={start}",
            f"author:{login} is:pr closed:>={start}",
            f"author:{login} is:pr is:open",
        ):
            for item in github_search(query, token):
                record = _pr_item(item)
                prs[f"{record['repo']}#{record['number']}"] = record
        issues = [
            {
                "repo": _issue_repo(item), "number": item.get("number"), "title": item.get("title"),
                "url": item.get("html_url"), "updated_at": item.get("updated_at"), "created_at": item.get("created_at"),
            }
            for item in github_search(f"author:{login} is:issue is:open", token, pages=1)
        ]
        commits = []
        for item in github_search(f"author:{login} committer-date:>={start}", token, kind="commits"):
            commit = item.get("commit") if isinstance(item.get("commit"), dict) else {}
            committer = commit.get("committer") if isinstance(commit.get("committer"), dict) else {}
            repository = item.get("repository") if isinstance(item.get("repository"), dict) else {}
            commits.append({"repo": repository.get("full_name"), "date": committer.get("date")})
        # Head branches let the server tell "branch with a PR" from "branch without one".
        heads: dict[str, list[dict[str, Any]]] = {}
        for repo in sorted(repos):
            try:
                pulls = github_get(f"/repos/{repo}/pulls", token, {
                    "state": "all", "sort": "updated", "direction": "desc", "per_page": "100"})
            except (urllib.error.URLError, OSError, ValueError):
                continue
            if isinstance(pulls, list):
                heads[repo] = [
                    {"number": pull.get("number"), "head": (pull.get("head") or {}).get("ref"), "state": pull.get("state")}
                    for pull in pulls if isinstance(pull, dict)
                ]
    except (urllib.error.URLError, OSError, ValueError) as error:
        reason = "github_auth_failed" if isinstance(error, urllib.error.HTTPError) and error.code in {401, 403} else "github_unavailable"
        return {**snapshot, "ok": False, "reason": reason}
    snapshot.update({
        "ok": True,
        "prs": sorted(prs.values(), key=lambda pr: pr.get("created_at") or ""),
        "open_issues": issues,
        "commits": commits,
        "pr_heads": heads,
    })
    return snapshot


# ── output ───────────────────────────────────────────────────────────────────

def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(path)


def machine_name(value: str | None) -> str:
    raw = value or socket.gethostname().split(".", 1)[0]
    return re.sub(r"[^a-z0-9-]+", "-", raw.lower()).strip("-") or "mac"


def known_repos(out_dir: Path, since_day: str) -> set[str]:
    repos: set[str] = set()
    for path in (out_dir / "sessions").glob("*/*.json"):
        if path.stem < since_day:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for record in data.get("sessions", []):
            if isinstance(record, dict) and isinstance(record.get("repo"), str):
                repos.add(record["repo"])
    return repos


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--machine", default=None, help="machine label, default: hostname")
    parser.add_argument("--recent-days", type=int, default=2, help="days always rewritten (today included)")
    parser.add_argument("--backfill-days", type=int, default=45, help="missing days filled once")
    parser.add_argument("--github", action="store_true", help="also collect GitHub outcomes")
    parser.add_argument("--github-login", default="pirajoke")
    parser.add_argument("--push-to", default=None, help="ssh host that receives this machine's files")
    parser.add_argument("--remote-out", default=".agent-bridge/daily-work")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    now = datetime.now(timezone.utc)
    machine = machine_name(args.machine)
    machine_dir = args.out / "sessions" / machine
    today = now.astimezone().date()
    window = [today - timedelta(days=offset) for offset in range(args.backfill_days)]
    recent = {day.isoformat() for day in window[: max(1, args.recent_days)]}
    wanted = {day.isoformat() for day in window if day.isoformat() in recent or not (machine_dir / f"{day.isoformat()}.json").exists()}
    oldest = min(date.fromisoformat(day) for day in wanted)
    since = datetime.combine(oldest, datetime.min.time()).astimezone() - timedelta(days=1)

    sessions, sources = collect_sessions(since)
    by_day = day_records(sessions, wanted)
    for day in sorted(wanted):
        write_json(machine_dir / f"{day}.json", {
            "schema": SCHEMA,
            "date": day,
            "machine": machine,
            "utc_offset_minutes": round((datetime.fromisoformat(day).astimezone().utcoffset() or timedelta()).total_seconds() / 60),
            "collected_at": iso_z(now),
            "sources": sources,
            "sessions": by_day.get(day, []),
        })
    result: dict[str, Any] = {"ok": True, "machine": machine, "days_written": len(wanted),
                              "sessions": sum(len(v) for v in by_day.values()), "sources": sources}

    if args.github:
        since_day = (today - timedelta(days=args.backfill_days)).isoformat()
        snapshot = collect_github(args.github_login, datetime.combine(today - timedelta(days=args.backfill_days), datetime.min.time()),
                                  known_repos(args.out, since_day))
        if snapshot.get("ok") or not (args.out / "github.json").exists():
            write_json(args.out / "github.json", snapshot)
        else:
            # Keep the last good snapshot; record the failure next to it.
            write_json(args.out / "github-error.json", snapshot)
        result["github"] = {"ok": snapshot.get("ok"), "reason": snapshot.get("reason")}

    if args.push_to:
        remote_dir = f"{args.remote_out.rstrip('/')}/sessions/{machine}"
        try:
            subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", args.push_to,
                            f"mkdir -p {remote_dir} && chmod 700 {args.remote_out}"], check=True, timeout=30)
            files = [str(machine_dir / f"{day}.json") for day in sorted(wanted)]
            subprocess.run(["scp", "-q", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", *files,
                            f"{args.push_to}:{remote_dir}/"], check=True, timeout=120)
            result["pushed"] = True
        except (OSError, subprocess.SubprocessError):
            result["pushed"] = False
            result["ok"] = False
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
