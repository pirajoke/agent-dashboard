#!/usr/bin/env python3
"""Deploy merged Command Center code on the Mac mini by itself.

Runs every 5 minutes from launchd (com.pirajoke.dashboard-auto-deploy). Each
run fetches origin/main into ~/agent-dashboard and compares it with the commit
that was last deployed. When `builder/` changed and GitHub CI is green for the
new commit, it runs that commit's `builder/deploy_to_scripts.sh` from a
detached worktree, checks that the dashboard answers on :7777 and, if the
deploy or the check fails, redeploys the previous commit.

Merging a PR on GitHub is the approval; nothing here pushes, merges or holds a
token. CI status is read from the public GitHub API without credentials.

State: ~/.agent-bridge/auto-deploy/state.json (written by deploy_to_scripts.sh
too, so manual deploys count). Log: ~/.agent-bridge/auto-deploy/deploys.jsonl.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

HOME = Path.home()
REPO_DIR = Path(os.environ.get("AUTO_DEPLOY_REPO_DIR", HOME / "agent-dashboard"))
STATE_DIR = Path(os.environ.get("AUTO_DEPLOY_STATE_DIR", HOME / ".agent-bridge" / "auto-deploy"))
GITHUB_REPO = "pirajoke/agent-dashboard"
HEALTH_URL = os.environ.get("AUTO_DEPLOY_HEALTH_URL", "http://127.0.0.1:7777/")
DEPLOY_PATHS = ("builder/",)
OK_CONCLUSIONS = {"success", "neutral", "skipped"}
LOG_KEEP = 500


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def git(*args: str, repo: Path = REPO_DIR) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True, timeout=120
    ).stdout.strip()


def load_state(state_dir: Path = STATE_DIR) -> dict:
    try:
        return json.loads((state_dir / "state.json").read_text())
    except (OSError, ValueError):
        return {}


def save_state(state: dict, state_dir: Path = STATE_DIR) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    tmp = state_dir / "state.json.tmp"
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True))
    tmp.replace(state_dir / "state.json")


def append_log(entry: dict, state_dir: Path = STATE_DIR) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    path = state_dir / "deploys.jsonl"
    lines = path.read_text().splitlines() if path.exists() else []
    lines.append(json.dumps(entry, sort_keys=True))
    path.write_text("\n".join(lines[-LOG_KEEP:]) + "\n")


def ci_state(sha: str, fetch=None) -> str:
    """Return green, pending or red for the commit's GitHub check runs."""
    url = f"https://api.github.com/repos/{GITHUB_REPO}/commits/{sha}/check-runs?per_page=100"
    if fetch is None:
        def fetch(target: str) -> dict:
            request = urllib.request.Request(
                target, headers={"Accept": "application/vnd.github+json", "User-Agent": "dashboard-auto-deploy"}
            )
            with urllib.request.urlopen(request, timeout=20) as response:
                return json.load(response)
    runs = fetch(url).get("check_runs") or []
    if not runs:
        return "pending"
    if any(run.get("status") != "completed" for run in runs):
        return "pending"
    if all(run.get("conclusion") in OK_CONCLUSIONS for run in runs):
        return "green"
    return "red"


def needs_deploy(changed_files: list[str]) -> bool:
    return any(name.startswith(DEPLOY_PATHS) for name in changed_files)


def healthy(url: str = HEALTH_URL, attempts: int = 6, delay: float = 5.0) -> bool:
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(url, timeout=10) as response:
                if response.status == 200:
                    return True
        except (urllib.error.URLError, OSError):
            pass
        if attempt + 1 < attempts:
            time.sleep(delay)
    return False


def deploy_commit(sha: str) -> tuple[bool, str]:
    """Run deploy_to_scripts.sh from a detached worktree at `sha`."""
    worktree = Path(tempfile.mkdtemp(prefix="dashboard-auto-deploy."))
    worktree.rmdir()
    try:
        git("worktree", "add", "--detach", str(worktree), sha)
        env = dict(os.environ, DASHBOARD_INSTALL_AUTO_DEPLOY="0", AUTO_DEPLOY_DEPLOYED_SHA=sha)
        result = subprocess.run(
            [str(worktree / "builder" / "deploy_to_scripts.sh")],
            capture_output=True, text=True, timeout=900, env=env,
        )
        tail = (result.stdout + result.stderr).strip().splitlines()[-15:]
        return result.returncode == 0, "\n".join(tail)
    except (subprocess.SubprocessError, OSError) as error:
        return False, str(error)
    finally:
        try:
            git("worktree", "remove", "--force", str(worktree))
        except (subprocess.SubprocessError, OSError):
            shutil.rmtree(worktree, ignore_errors=True)


def run(
    *,
    fetch_head=None,
    changed_between=None,
    get_ci=ci_state,
    do_deploy=deploy_commit,
    is_healthy=healthy,
    state_dir: Path = STATE_DIR,
) -> str:
    """One pass. Returns what happened, for logs and tests."""
    if fetch_head is None:
        def fetch_head() -> str:
            git("fetch", "--quiet", "origin", "main")
            return git("rev-parse", "FETCH_HEAD")
    if changed_between is None:
        def changed_between(old: str, new: str) -> list[str]:
            return git("diff", "--name-only", old, new).splitlines()

    state = load_state(state_dir)
    head = fetch_head()
    deployed = state.get("deployed_sha")
    state["checked_at"] = now_iso()

    if not deployed:
        # First run before any recorded deploy: deploy what main has now.
        changed = ["builder/"]
    elif deployed == head:
        save_state(state, state_dir)
        return "up_to_date"
    else:
        try:
            changed = changed_between(deployed, head)
        except subprocess.SubprocessError:
            changed = ["builder/"]  # unknown history: deploy to be safe

    if not needs_deploy(changed):
        state["deployed_sha"] = head  # only generated files moved
        save_state(state, state_dir)
        return "no_builder_changes"

    if state.get("failed_sha") == head:
        save_state(state, state_dir)
        return "skipped_failed"

    ci = get_ci(head)
    if ci != "green":
        state["waiting_sha"] = head
        state["waiting_reason"] = f"ci_{ci}"
        if ci == "red":
            state["failed_sha"] = head
            append_log({"at": now_iso(), "sha": head, "result": "ci_red"}, state_dir)
        save_state(state, state_dir)
        return f"ci_{ci}"

    ok, output = do_deploy(head)
    if ok and is_healthy():
        state.update(deployed_sha=head, deployed_at=now_iso(), last_result="deployed")
        state.pop("waiting_sha", None)
        state.pop("waiting_reason", None)
        save_state(state, state_dir)
        append_log({"at": now_iso(), "sha": head, "from": deployed, "result": "deployed"}, state_dir)
        return "deployed"

    reason = "deploy_failed" if not ok else "health_failed"
    rollback = "none"
    if deployed:
        back_ok, back_output = do_deploy(deployed)
        rollback = "ok" if back_ok and is_healthy() else "failed"
        output = f"{output}\n--- rollback ---\n{back_output}"
    state.update(failed_sha=head, last_result=f"{reason}_rollback_{rollback}", failed_at=now_iso())
    save_state(state, state_dir)
    append_log(
        {"at": now_iso(), "sha": head, "from": deployed, "result": reason, "rollback": rollback,
         "output": output[-4000:]},
        state_dir,
    )
    return f"{reason}_rollback_{rollback}"


def record_deployed(sha: str, state_dir: Path = STATE_DIR) -> None:
    state = load_state(state_dir)
    state.update(deployed_sha=sha, deployed_at=now_iso())
    save_state(state, state_dir)


def main() -> int:
    if len(sys.argv) == 3 and sys.argv[1] == "--record":
        record_deployed(sys.argv[2])
        return 0
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    lock = STATE_DIR / "lock"
    try:
        lock.mkdir()
    except FileExistsError:
        if time.time() - lock.stat().st_mtime < 1800:
            print(f"{now_iso()} another run is active")
            return 0
        lock.rmdir()
        lock.mkdir()
    try:
        outcome = run()
    except Exception as error:  # keep launchd quiet; record and retry next time
        outcome = f"error: {error}"
    finally:
        lock.rmdir()
    print(f"{now_iso()} {outcome}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
