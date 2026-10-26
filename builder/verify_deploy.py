#!/usr/bin/env python3
"""Say whether a merged commit is live on the Mac mini. Read-only.

Run it on the Mac mini after a merge, for example from a Remote Control
session, so the thread can report "on the site" instead of "merged; deploy not
verified":

    cd ~/agent-dashboard && git fetch -q origin main && \
        git show origin/main:builder/verify_deploy.py | python3 - <merge-sha>

It reads what builder/auto_deploy.py recorded (state.json, deploys.jsonl),
checks that the commit is in the deployed history and that the dashboard
answers on :7777. It never deploys, restarts or writes anything.

Exit codes: 0 live, 1 failed or rolled back, 2 still waiting.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import urllib.error
import urllib.request

HOME = Path.home()
REPO_DIR = Path(os.environ.get("AUTO_DEPLOY_REPO_DIR", HOME / "agent-dashboard"))
STATE_DIR = Path(os.environ.get("AUTO_DEPLOY_STATE_DIR", HOME / ".agent-bridge" / "auto-deploy"))
HEALTH_URL = os.environ.get("AUTO_DEPLOY_HEALTH_URL", "http://127.0.0.1:7777/")

MESSAGES = {
    "live": "На сайте: Mac mini поставил эту версию, сайт отвечает.",
    "live_unhealthy": "Версия стоит, но сайт сейчас не отвечает.",
    "rollback_failed": "Сбой: Mac mini не смог ни поставить, ни откатить, что сейчас на сайте, неизвестно.",
    "failed": "Не встало: Mac mini попробовал поставить и откатил назад.",
    "ci_red": "Не встало: проверки на main красные, Mac mini не ставил.",
    "waiting_ci": "Ждёт: Mac mini поставит, как только пройдут проверки.",
    "pending": "Ждёт: Mac mini ставит новые версии раз в 5 минут.",
    "unknown_commit": "Такой версии на Mac mini не видно, проверь номер.",
}


def git(*args: str, repo: Path = REPO_DIR) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=60
    )


def load_state(state_dir: Path = STATE_DIR) -> dict:
    try:
        return json.loads((state_dir / "state.json").read_text())
    except (OSError, ValueError):
        return {}


def load_log(state_dir: Path = STATE_DIR) -> list[dict]:
    try:
        lines = (state_dir / "deploys.jsonl").read_text().splitlines()
    except OSError:
        return []
    entries = []
    for line in lines:
        try:
            entries.append(json.loads(line))
        except ValueError:
            continue
    return entries


def health_code(url: str = HEALTH_URL) -> int:
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code
    except (urllib.error.URLError, OSError):
        return 0


def verdict(sha: str, state: dict, log: list[dict], contains, health: int) -> str:
    """contains(ancestor, descendant) -> bool says whether one commit includes the other."""
    if str(state.get("last_result", "")).endswith("_rollback_failed"):
        return "rollback_failed"  # files on disk may be half-updated; nothing is confirmed
    deployed = state.get("deployed_sha")
    if deployed and contains(sha, deployed):
        return "live" if health == 200 else "live_unhealthy"
    for key, result in (("failed_sha", "failed"), ("waiting_sha", "waiting_ci")):
        other = state.get(key)
        if other and contains(sha, other):
            if result == "failed":
                tried = [e for e in log if e.get("sha") == other]
                if tried and tried[-1].get("result") == "ci_red":
                    return "ci_red"
            return result
    return "pending"


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: verify_deploy.py <merge-sha>", file=sys.stderr)
        return 2
    resolved = git("rev-parse", "--verify", "--quiet", f"{argv[1]}^{{commit}}")
    if resolved.returncode != 0:
        print(json.dumps({"sha": argv[1], "status": "unknown_commit"}))
        print(MESSAGES["unknown_commit"])
        return 2
    sha = resolved.stdout.strip()

    def contains(ancestor: str, descendant: str) -> bool:
        return git("merge-base", "--is-ancestor", ancestor, descendant).returncode == 0

    state = load_state()
    log = load_log()
    health = health_code()
    status = verdict(sha, state, log, contains, health)
    print(json.dumps({
        "sha": sha,
        "status": status,
        "deployed_sha": state.get("deployed_sha"),
        "deployed_at": state.get("deployed_at"),
        "checked_at": state.get("checked_at"),
        "health": health,
        "last_log": log[-3:],
    }, ensure_ascii=False))
    print(MESSAGES[status])
    if status == "live":
        return 0
    return 1 if status in {"failed", "rollback_failed", "ci_red", "live_unhealthy"} else 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
