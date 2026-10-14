#!/usr/bin/env python3
"""Load the Mac mini's own services again when launchd did not (Mark 2026-10-14: «сделай сторожа»).

On 2026-10-12 the Mac mini lost power, came back, and after the login many LaunchAgents were
never loaded, so JARVIS, the Context News worker and other services stayed down for two days.

Runs at login and every 5 minutes from launchd (com.pirajoke.launchd-watchdog). Each run:

- remembers every com.pirajoke.* / homebrew.mxcl.* job that launchd has loaded and whose plist
  is in ~/Library/LaunchAgents ("wanted");
- forgets a job once it is switched off with ``launchctl disable`` or its plist is removed;
- loads (``launchctl bootstrap``) every wanted job that launchd does not have, after checking
  again 30 seconds later so a deploy that reloads a job is not raced.

It never loads a job it has not seen running, so services that are off stay off. To stop a
service for good, switch it off with ``launchctl disable gui/$(id -u)/<label>``; a plain
``launchctl bootout`` is undone within 5 minutes.

State: ~/.agent-bridge/launchd-watchdog/state.json. Log: ~/.agent-bridge/launchd-watchdog/events.jsonl.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import plistlib
import subprocess
import time

from dashboard_builder.service_status import parse_launchctl_disabled, parse_launchctl_list

HOME = Path.home()
LAUNCH_AGENTS_DIR = Path(os.environ.get("LAUNCHD_WATCHDOG_AGENTS_DIR", HOME / "Library" / "LaunchAgents"))
STATE_DIR = Path(os.environ.get("LAUNCHD_WATCHDOG_STATE_DIR", HOME / ".agent-bridge" / "launchd-watchdog"))
SELF_LABEL = "com.pirajoke.launchd-watchdog"
PREFIXES = ("com.pirajoke.", "homebrew.mxcl.")
RECHECK_SECONDS = 30
LOG_KEEP = 500


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run(cmd: list[str], timeout: int = 20) -> tuple[int, str]:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return result.returncode, ((result.stdout or "") + (result.stderr or "")).strip()
    except (OSError, subprocess.TimeoutExpired) as error:
        return 1, str(error)


def agent_plists(agents_dir: Path = LAUNCH_AGENTS_DIR) -> dict[str, Path]:
    """{label: plist} for our jobs in ~/Library/LaunchAgents, by each plist's own Label."""
    found: dict[str, Path] = {}
    for path in sorted(agents_dir.glob("*.plist")):
        try:
            with path.open("rb") as handle:
                label = plistlib.load(handle).get("Label")
        except (OSError, plistlib.InvalidFileException, ValueError, AttributeError):
            continue
        if isinstance(label, str) and label.startswith(PREFIXES) and label != SELF_LABEL:
            found[label] = path
    return found


def update_wanted(wanted: set[str], loaded: set[str], disabled: set[str], plists: dict[str, Path]) -> set[str]:
    """Jobs to keep loaded: the ones seen loaded, minus switched-off and removed ones."""
    return {label for label in wanted | (loaded & set(plists)) if label in plists and label not in disabled}


def missing(wanted: set[str], loaded: set[str]) -> list[str]:
    return sorted(wanted - loaded)


def load_state(state_dir: Path = STATE_DIR) -> dict:
    try:
        return json.loads((state_dir / "state.json").read_text())
    except (OSError, ValueError):
        return {}


def save_state(state: dict, state_dir: Path = STATE_DIR) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    tmp = state_dir / "state.json.tmp"
    tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n")
    tmp.replace(state_dir / "state.json")


def log_event(event: dict, state_dir: Path = STATE_DIR) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    path = state_dir / "events.jsonl"
    try:
        lines = path.read_text().splitlines()[-(LOG_KEEP - 1):]
    except OSError:
        lines = []
    lines.append(json.dumps({"at": now_iso(), **event}, ensure_ascii=False))
    path.write_text("\n".join(lines) + "\n")


def launchd_state() -> tuple[set[str] | None, set[str] | None]:
    code, listing = run(["launchctl", "list"])
    loaded = set(parse_launchctl_list(listing)) if code == 0 else set()
    _, disabled_raw = run(["launchctl", "print-disabled", f"gui/{os.getuid()}"])
    return (loaded or None), parse_launchctl_disabled(disabled_raw)


def bootstrap(plist: Path) -> tuple[bool, str]:
    code, output = run(["launchctl", "bootstrap", f"gui/{os.getuid()}", str(plist)])
    return code == 0, output[-300:]


def run_once(
    *,
    state_dir: Path = STATE_DIR,
    agents_dir: Path = LAUNCH_AGENTS_DIR,
    read_launchd=launchd_state,
    load=bootstrap,
    sleep=time.sleep,
) -> dict:
    loaded, disabled = read_launchd()
    if loaded is None or disabled is None:
        # launchctl did not answer: change nothing rather than guess.
        return {"status": "launchctl_unavailable"}
    plists = agent_plists(agents_dir)
    state = load_state(state_dir)
    wanted = update_wanted(set(state.get("wanted", [])), loaded, disabled, plists)
    todo = missing(wanted, loaded)
    results = {}
    if todo:
        sleep(RECHECK_SECONDS)
        loaded_again, _ = read_launchd()
        for label in missing(set(todo), loaded_again or set()):
            ok, output = load(plists[label])
            results[label] = "loaded" if ok else "failed"
            log_event({"label": label, "result": results[label], "output": output}, state_dir)
    state.update(wanted=sorted(wanted), last_run=now_iso(), last_loaded=results)
    save_state(state, state_dir)
    return {"status": "ok", "wanted": len(wanted), "loaded": results}


if __name__ == "__main__":
    print(json.dumps(run_once(), ensure_ascii=False))
