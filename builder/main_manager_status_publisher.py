#!/usr/bin/env python3
"""Publish a tokenless MAIN MANAGER status snapshot to Bridge.

Reads the continuation queue through ``portfolio_continuation_scheduler.py
status`` (no model call, no dispatch), maps the open queue items onto the
department-campus event contract and posts one non-executable snapshot to
Bridge ``/api/status-event``. Bridge stores it as an already finished record,
so no worker ever picks it up.

Run every few minutes from launchd; see
``launchd/com.pirajoke.main-manager-status-publisher.plist.template``.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dashboard_builder.department_campus import CAMPUS_PROJECTS, DEPARTMENT_ZONES  # noqa: E402

SOURCE_AGENT = "main-manager"
RUNTIME_DIR = Path.home() / "Library/Application Support/MainManagerPortfolioContinuation"
DEFAULT_SCHEDULER = RUNTIME_DIR / "portfolio_continuation_scheduler.py"
DEFAULT_STATE = RUNTIME_DIR / "state/scheduler-state.json"
DEFAULT_QUEUE = RUNTIME_DIR / "state/continuation-queue.json"
DEFAULT_LOCK = RUNTIME_DIR / "state/scheduler.lock"
DEFAULT_ROUTES = RUNTIME_DIR / "agent-routes.json"
DEFAULT_TOKEN_FILE = Path.home() / "jarvis/.secrets/bridge_api_token"

# Scheduler human_projection status -> campus status. DONE items are history
# and are not shown as live work.
CAMPUS_STATUS = {
    "NEEDS MARK": "waiting",
    "WORKING": "active",
    "PROBLEM": "failed",
    "WAITING": "queued",
}
STATUS_PRIORITY = {"failed": 0, "waiting": 1, "active": 2, "queued": 3}
NEXT_STEP = {
    "waiting": "Ждёт решения Марка",
    "active": "Агент работает над задачей",
    "failed": "Доставка не подтверждена, нужна проверка",
    "queued": "В очереди MAIN MANAGER",
}
DEPARTMENT_ROLE = {
    "hq": "Main Manager",
    "sales": "Sales Researcher",
    "development": "Builder",
    "design": "Designer",
    "infrastructure": "Infrastructure Engineer",
    "internal": "Knowledge Curator",
    "finance": "Finance Analyst",
}
PROJECT_ALIASES = {"MYDICTIONARY": "MY DICTIONARY", "MYDICTIONNARY": "MY DICTIONARY"}
_PROJECTS = {record["project"]: record for record in CAMPUS_PROJECTS}


class PublisherError(RuntimeError):
    pass


def iso_z(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def campus_project(name: object) -> dict[str, Any] | None:
    if not isinstance(name, str):
        return None
    normalized = " ".join(name.replace("_", " ").upper().split())
    normalized = PROJECT_ALIASES.get(normalized.replace(" ", ""), normalized)
    return _PROJECTS.get(normalized)


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def queue_updated_at(queue_path: Path) -> str | None:
    """Last time the continuation queue changed on disk (idle collects do not rewrite it)."""
    try:
        return iso_z(datetime.fromtimestamp(queue_path.stat().st_mtime, tz=timezone.utc))
    except OSError:
        return None


def build_events(status: dict[str, Any], *, observed_at: str) -> list[dict[str, Any]]:
    pixel_events = status.get("pixel_events")
    human = status.get("human_projection")
    if not isinstance(pixel_events, list) or not isinstance(human, list) or len(pixel_events) != len(human):
        raise PublisherError("scheduler_status_invalid")
    by_project: dict[str, dict[str, Any]] = {}
    for pixel, person in zip(pixel_events, human):
        if not isinstance(pixel, dict) or not isinstance(person, dict):
            continue
        campus_status = CAMPUS_STATUS.get(person.get("status"))
        record = campus_project(pixel.get("project"))
        if campus_status is None or record is None:
            continue
        current = by_project.get(record["project"])
        if current is not None and STATUS_PRIORITY[current["status"]] <= STATUS_PRIORITY[campus_status]:
            continue
        department_id = record["department_id"]
        zone = DEPARTMENT_ZONES[department_id]
        task_id = f"mm-{slug(record['project'])}"
        by_project[record["project"]] = {
            "event_id": f"{task_id}-{campus_status}",
            "task_id": task_id,
            "department_id": department_id,
            "department_label": zone["label"],
            "zone_id": zone["zone_id"],
            "project": record["project"],
            "agent_id": record["agent_id"],
            "role": DEPARTMENT_ROLE[department_id],
            "status": campus_status,
            "updated_at": observed_at,
            "next_step": NEXT_STEP[campus_status],
            "evidence_count": 0,
            "ephemeral": True,
        }
    return sorted(by_project.values(), key=lambda event: (STATUS_PRIORITY[event["status"]], event["project"]))


def build_snapshot(status: dict[str, Any], *, now: datetime, queue_path: Path) -> dict[str, Any]:
    if status.get("ok") is not True:
        raise PublisherError("scheduler_status_failed")
    observed_at = iso_z(now)
    counts = status.get("counts")
    snapshot = {
        "source_agent": SOURCE_AGENT,
        "event": "status",
        "project": "MAIN MANAGER",
        "observed_at": observed_at,
        "queue_updated_at": queue_updated_at(queue_path),
        "pixel_events": build_events(status, observed_at=observed_at),
    }
    if isinstance(counts, dict) and all(type(v) is int and v >= 0 for v in counts.values()):
        snapshot["counts"] = counts
    return snapshot


def run_scheduler_status(args: argparse.Namespace, now: datetime) -> dict[str, Any]:
    command = [
        sys.executable,
        str(args.scheduler),
        "status",
        "--state", str(args.state),
        "--queue", str(args.queue),
        "--lock", str(args.lock),
        "--routes", str(args.routes),
        "--stale-after-seconds", "300",
        "--now", iso_z(now),
    ]
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise PublisherError("scheduler_unavailable") from error
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise PublisherError("scheduler_status_invalid") from error


def post_snapshot(snapshot: dict[str, Any], *, bridge_url: str, token: str, timeout: float = 10) -> dict[str, Any]:
    request = urllib.request.Request(
        f"{bridge_url.rstrip('/')}/api/status-event",
        data=json.dumps(snapshot, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            result = json.load(response)
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as error:
        raise PublisherError("bridge_post_failed") from error
    if not isinstance(result, dict) or result.get("status") != "done" or not result.get("id"):
        raise PublisherError("bridge_response_invalid")
    return result


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--scheduler", type=Path, default=DEFAULT_SCHEDULER)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--queue", type=Path, default=DEFAULT_QUEUE)
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK)
    parser.add_argument("--routes", type=Path, default=DEFAULT_ROUTES)
    parser.add_argument("--bridge-url", default="http://127.0.0.1:8899")
    parser.add_argument("--token-file", type=Path, default=DEFAULT_TOKEN_FILE)
    parser.add_argument("--dry-run", action="store_true", help="print the snapshot instead of posting it")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    now = datetime.now(timezone.utc)
    try:
        snapshot = build_snapshot(run_scheduler_status(args, now), now=now, queue_path=args.queue)
        if args.dry_run:
            print(json.dumps(snapshot, ensure_ascii=False, indent=2))
            return 0
        token = args.token_file.read_text(encoding="utf-8").strip()
        if not token:
            raise PublisherError("bridge_token_unavailable")
        result = post_snapshot(snapshot, bridge_url=args.bridge_url, token=token)
    except OSError:
        print(json.dumps({"ok": False, "reason": "bridge_token_unavailable"}))
        return 1
    except PublisherError as error:
        print(json.dumps({"ok": False, "reason": str(error)}))
        return 1
    print(json.dumps({
        "ok": True,
        "id": result["id"],
        "events": len(snapshot["pixel_events"]),
        "queue_updated_at": snapshot["queue_updated_at"],
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
