#!/usr/bin/env python3
"""Record every infrastructure change on this Mac for the Command Center Infra log.

Tokenless. Each run takes a snapshot of what makes up the machine's runtime
(launchd agents and their plists, Docker containers, Homebrew services,
listening ports, git checkouts, runtime scripts, crontab, tunnel config),
compares it with the previous snapshot and appends one event per difference
to ``<out>/<machine>/events-YYYY-MM.jsonl``. The first run only records a
baseline. Agent commands (Claude/Codex) are collected separately by
``daily_work_collector.py``.

Only names, hashes, ports and commit subjects are stored, never file contents
or environment values.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import socket
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

SCHEMA = 1
HOME = Path.home()
DEFAULT_OUT = HOME / ".agent-bridge" / "infra-changes"
LAUNCH_AGENTS = HOME / "Library" / "LaunchAgents"
RUNTIME_DIRS = [HOME / "scripts"]
RUNTIME_SUFFIXES = {".py", ".sh", ".js", ".plist", ".yml", ".yaml", ".toml"}
TUNNEL_DIRS = [HOME / ".cloudflared"]
REPO_ROOTS = [HOME, HOME / "projects", HOME / "Projects"]
MAX_FILES = 400
OWN_LABEL = "com.pirajoke.infra-change-collector"


def iso_z(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def run(command: list[str], timeout: int = 15) -> str | None:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False,
                                env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout if result.returncode == 0 else None


def sha(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()[:16]
    except OSError:
        return None


# ── snapshot parts; each returns {key: comparable value} or None if unavailable ──

def snap_launchd_files() -> dict[str, Any] | None:
    if not LAUNCH_AGENTS.is_dir():
        return None
    return {path.name: sha(path) for path in sorted(LAUNCH_AGENTS.iterdir()) if path.is_file()}


def snap_launchd_jobs() -> dict[str, Any] | None:
    output = run(["launchctl", "list"])
    if output is None:
        return None
    jobs = {}
    for line in output.splitlines()[1:]:
        parts = line.split("\t")
        if len(parts) != 3 or parts[2].startswith(("com.apple.", "application.", "0x")) or parts[2] == OWN_LABEL:
            continue
        pid, status, label = parts
        jobs[label] = {"running": pid != "-", "pid": None if pid == "-" else pid, "exit": status}
    return jobs


def snap_docker() -> dict[str, Any] | None:
    output = run(["docker", "ps", "-a", "--no-trunc", "--format", "{{json .}}"])
    if output is None:
        return None
    containers = {}
    for line in output.splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        containers[item.get("Names", "?")] = {"image": item.get("Image"), "state": item.get("State"),
                                               "id": (item.get("ID") or "")[:12]}
    return containers


def snap_brew() -> dict[str, Any] | None:
    output = run(["brew", "services", "list", "--json"], timeout=30)
    if output is None:
        return None
    try:
        return {item["name"]: item.get("status") for item in json.loads(output) if isinstance(item, dict)}
    except (json.JSONDecodeError, KeyError, TypeError):
        return None


def snap_ports() -> dict[str, Any] | None:
    output = run(["lsof", "-nP", "-iTCP", "-sTCP:LISTEN"])
    if output is None:
        return None
    ports = {}
    for line in output.splitlines()[1:]:
        parts = line.split()
        if len(parts) < 9:
            continue
        match = re.search(r":(\d+)$", parts[8])
        # Ports in the dynamic range (49152+) are reassigned on every app start.
        if match and int(match.group(1)) < 49152:
            address = parts[8].rsplit(":", 1)[0]
            scope = "local" if address in {"127.0.0.1", "[::1]", "localhost"} else "network"
            ports[match.group(1)] = {"process": parts[0], "scope": scope}
    return ports


def snap_repos() -> dict[str, Any] | None:
    repos = {}
    for root in REPO_ROOTS:
        if not root.is_dir():
            continue
        for git_dir in root.glob("*/.git"):
            checkout = git_dir.parent
            head = run(["git", "-C", str(checkout), "rev-parse", "HEAD"])
            if not head:
                continue
            branch = run(["git", "-C", str(checkout), "rev-parse", "--abbrev-ref", "HEAD"]) or ""
            repos[str(checkout.relative_to(HOME))] = {"head": head.strip()[:12], "branch": branch.strip()}
    return repos


def snap_files(dirs: list[Path], suffixes: set[str] | None) -> dict[str, Any] | None:
    files = {}
    for base in dirs:
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if len(files) >= MAX_FILES:
                break
            if not path.is_file() or "__pycache__" in path.parts or any(part.startswith(".") and part != base.name for part in path.relative_to(base).parts):
                continue
            if suffixes is not None and path.suffix not in suffixes:
                continue
            files[str(path.relative_to(HOME))] = sha(path)
    return files


def snap_crontab() -> dict[str, Any] | None:
    output = run(["crontab", "-l"])
    lines = [line for line in (output or "").splitlines() if line.strip() and not line.startswith("#")]
    return {"entries": len(lines), "hash": hashlib.sha256("\n".join(lines).encode()).hexdigest()[:16]}


PARTS: dict[str, Callable[[], dict[str, Any] | None]] = {
    "launchd_files": snap_launchd_files,
    "launchd_jobs": snap_launchd_jobs,
    "docker": snap_docker,
    "brew": snap_brew,
    "ports": snap_ports,
    "repos": snap_repos,
    "runtime_files": lambda: snap_files(RUNTIME_DIRS, RUNTIME_SUFFIXES),
    "tunnel_files": lambda: snap_files(TUNNEL_DIRS, None),
    "crontab": snap_crontab,
}


def snapshot() -> dict[str, Any]:
    return {name: collect() for name, collect in PARTS.items()}


# ── diff ─────────────────────────────────────────────────────────────────────

def _event(category: str, action: str, subject: str, detail: str | None = None, **extra: Any) -> dict[str, Any]:
    event = {"category": category, "action": action, "subject": subject}
    if detail:
        event["detail"] = detail
    event.update({key: value for key, value in extra.items() if value is not None})
    return event


def _keyed(prev: dict | None, cur: dict | None):
    prev, cur = prev or {}, cur or {}
    for key in sorted(set(prev) | set(cur)):
        yield key, prev.get(key), cur.get(key)


def _repo_subject(checkout: str, old: str, new: str) -> tuple[str | None, int | None]:
    path = HOME / checkout
    subject = run(["git", "-C", str(path), "log", "-1", "--format=%s", new])
    count = run(["git", "-C", str(path), "rev-list", "--count", f"{old}..{new}"])
    try:
        commits = int(count.strip()) if count else None
    except ValueError:
        commits = None
    return (subject.strip()[:140] if subject else None), commits


def diff(prev: dict[str, Any], cur: dict[str, Any]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    # Parts that failed to collect this time or last time are skipped, never
    # reported as everything being removed.
    def both(name: str) -> bool:
        return prev.get(name) is not None and cur.get(name) is not None

    if both("launchd_files"):
        for name, old, new in _keyed(prev["launchd_files"], cur["launchd_files"]):
            if old is None:
                events.append(_event("launchd", "added", name, "plist добавлен"))
            elif new is None:
                events.append(_event("launchd", "removed", name, "plist удалён или переименован"))
            elif old != new:
                events.append(_event("launchd", "changed", name, "plist изменён"))
    if both("launchd_jobs"):
        for label, old, new in _keyed(prev["launchd_jobs"], cur["launchd_jobs"]):
            if old is None:
                events.append(_event("launchd", "loaded", label, "задача загружена в launchd"))
            elif new is None:
                events.append(_event("launchd", "unloaded", label, "задача выгружена из launchd"))
            elif old["pid"] and new["pid"] and old["pid"] != new["pid"]:
                events.append(_event("launchd", "restarted", label, "процесс перезапущен"))
            # Periodic jobs flip between running and idle on their own, so only
            # a change of the last exit code is reported, not every run.
            elif new["exit"] != old["exit"] and new["exit"] != "0" and not new["running"]:
                events.append(_event("launchd", "failed", label, f"последний запуск завершился с кодом {new['exit']}"))
            elif new["exit"] == "0" and old["exit"] != "0" and not new["running"]:
                events.append(_event("launchd", "recovered", label, f"снова завершается без ошибок (был код {old['exit']})"))
    if both("docker"):
        for name, old, new in _keyed(prev["docker"], cur["docker"]):
            if old is None:
                events.append(_event("docker", "added", name, f"контейнер создан из {new['image']}"))
            elif new is None:
                events.append(_event("docker", "removed", name, "контейнер удалён"))
            elif old["image"] != new["image"] or old["id"] != new["id"]:
                events.append(_event("docker", "changed", name, f"контейнер пересоздан: {old['image']} → {new['image']}"))
            elif old["state"] != new["state"]:
                events.append(_event("docker", "started" if new["state"] == "running" else "stopped", name,
                                     f"{old['state']} → {new['state']}"))
    if both("brew"):
        for name, old, new in _keyed(prev["brew"], cur["brew"]):
            if old != new:
                events.append(_event("brew", "changed", name, f"{old or 'нет'} → {new or 'нет'}"))
    if both("ports"):
        for port, old, new in _keyed(prev["ports"], cur["ports"]):
            if old is None:
                events.append(_event("port", "opened", port, f"{new['process']} слушает ({'вся сеть' if new['scope'] == 'network' else 'только localhost'})"))
            elif new is None:
                events.append(_event("port", "closed", port, f"{old['process']} больше не слушает"))
            elif old != new:
                events.append(_event("port", "changed", port, f"{old['process']} → {new['process']}"))
    if both("repos"):
        for checkout, old, new in _keyed(prev["repos"], cur["repos"]):
            if old is None:
                events.append(_event("repo", "added", checkout, f"новый checkout на {new['branch']}"))
            elif new is None:
                events.append(_event("repo", "removed", checkout, "checkout удалён"))
            elif old["head"] != new["head"]:
                subject, commits = _repo_subject(checkout, old["head"], new["head"])
                branch = f"{old['branch']} → {new['branch']}" if old["branch"] != new["branch"] else new["branch"]
                events.append(_event("repo", "updated", checkout, subject or "код обновлён",
                                     branch=branch, from_head=old["head"], to_head=new["head"], commits=commits))
    for part, category in (("runtime_files", "runtime"), ("tunnel_files", "tunnel")):
        if not both(part):
            continue
        added = [k for k, o, n in _keyed(prev[part], cur[part]) if o is None]
        removed = [k for k, o, n in _keyed(prev[part], cur[part]) if n is None]
        changed = [k for k, o, n in _keyed(prev[part], cur[part]) if o and n and o != n]
        if added or removed or changed:
            label = "~/scripts" if category == "runtime" else "~/.cloudflared"
            counts = ", ".join(f"{word} {len(items)}" for word, items in (("изменено", changed), ("добавлено", added), ("удалено", removed)) if items)
            events.append(_event(category, "changed", label, counts, files=(changed + added + removed)[:25]))
    if both("crontab") and prev["crontab"] != cur["crontab"]:
        events.append(_event("cron", "changed", "crontab", f"записей: {prev['crontab']['entries']} → {cur['crontab']['entries']}"))
    return events


# ── main ─────────────────────────────────────────────────────────────────────

def machine_name(value: str | None) -> str:
    raw = value or socket.gethostname().split(".", 1)[0]
    return re.sub(r"[^a-z0-9-]+", "-", raw.lower()).strip("-") or "mac"


def write_private(path: Path, text: str, *, append: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if append:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(text)
    else:
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(path)
    os.chmod(path, 0o600)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--machine", default=None)
    parser.add_argument("--push-to", default=None, help="ssh host that receives this machine's events")
    parser.add_argument("--remote-out", default=".agent-bridge/infra-changes")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    now = datetime.now(timezone.utc)
    machine = machine_name(args.machine)
    machine_dir = args.out / machine
    state_path = machine_dir / "state.json"
    current = snapshot()
    try:
        previous = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        previous = None

    if previous is None:
        events = [_event("baseline", "baseline", machine, "первый снимок: дальше записываются только изменения")]
    else:
        events = diff(previous.get("snapshot") or {}, current)
    stamp = iso_z(now)
    events_path = machine_dir / f"events-{now.strftime('%Y-%m')}.jsonl"
    if events:
        write_private(events_path, "".join(json.dumps({"at": stamp, "machine": machine, **event}, ensure_ascii=False) + "\n" for event in events), append=True)
    unavailable = sorted(name for name, value in current.items() if value is None)
    write_private(state_path, json.dumps({"schema": SCHEMA, "machine": machine, "collected_at": stamp,
                                          "unavailable": unavailable, "snapshot": current}, ensure_ascii=False))
    result: dict[str, Any] = {"ok": True, "machine": machine, "events": len(events), "unavailable": unavailable}

    if args.push_to:
        remote_dir = f"{args.remote_out.rstrip('/')}/{machine}"
        files = [str(state_path)] + ([str(events_path)] if events_path.exists() else [])
        try:
            subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", args.push_to,
                            f"mkdir -p {remote_dir} && chmod 700 {args.remote_out}"], check=True, timeout=30)
            subprocess.run(["scp", "-q", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", *files,
                            f"{args.push_to}:{remote_dir}/"], check=True, timeout=120)
            result["pushed"] = True
        except (OSError, subprocess.SubprocessError):
            result.update(pushed=False, ok=False)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
