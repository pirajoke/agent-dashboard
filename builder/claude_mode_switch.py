#!/usr/bin/env python3
"""Claude Code permission mode on the Mac mini, switched from Command Center (Mark 2026-11-17).

Mark: «переключатель bypass permission и выключить, и тогда у нас вернётся наш расширенный список».

The site never writes ~/.claude/settings.json. It drops a request into ~/.claude-mode/inbox and this
script, run by launchd (QueueDirectories on that inbox, plus a slow interval to keep the state fresh),
checks the request and changes exactly two keys:

* «bypass»   — permissions.defaultMode = bypassPermissions, skipDangerousModePermissionPrompt = true
* «standard» — permissions.defaultMode = auto, skipDangerousModePermissionPrompt removed

The allow and deny lists and autoMode stay untouched in both modes, so «standard» is the extended
allow list that was in force before bypass. Deny rules apply in both modes.

Only the owner can switch: each request carries the Cloudflare Access sign-in of the browser that asked,
and this script checks its signature again with Cloudflare's keys. A file dropped by anything else on the
machine is refused and logged. Requests older than two minutes are refused too. Every change keeps a backup
of settings.json in ~/.claude-mode/backups and one line in ~/.claude-mode/switch.log.
"""
from __future__ import annotations

import datetime as dt
import fcntl
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path

MODES = {
    "bypass": {"defaultMode": "bypassPermissions", "skip": True},
    "standard": {"defaultMode": "auto", "skip": False},
}
REQUEST_ID = re.compile(r"^[a-z0-9-]{8,64}$")
MAX_REQUEST_AGE = 120.0
MAX_REQUEST_BYTES = 8192
RECENT = 8
SCHEMA = "claude_mode_v1"


def mode_dir(home: Path) -> Path:
    return Path(os.environ.get("CLAUDE_MODE_DIR", home / ".claude-mode"))


def settings_path(home: Path) -> Path:
    return Path(os.environ.get("CLAUDE_MODE_SETTINGS", home / ".claude" / "settings.json"))


def _iso(at: float) -> str:
    return dt.datetime.fromtimestamp(at, dt.timezone.utc).isoformat(timespec="seconds")


def observed_mode(settings: dict) -> tuple[str, str | None]:
    default = (settings.get("permissions") or {}).get("defaultMode")
    if default == "bypassPermissions":
        return "bypass", default
    if default in (None, "auto", "default", "acceptEdits"):
        return "standard", default
    return "other", default if isinstance(default, str) else None


def _write_json_atomic(path: Path, data, mode: int) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.chmod(tmp, mode)
        json.loads(Path(tmp).read_text())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def apply_mode(settings_file: Path, backups: Path, mode: str, now: float) -> tuple[bool, str]:
    """Set ``mode`` in settings.json. Returns (changed, previous mode). Never writes a damaged file."""
    raw = settings_file.read_text()
    settings = json.loads(raw)
    if not isinstance(settings, dict):
        raise ValueError("settings.json is not an object")
    before, _ = observed_mode(settings)
    want = MODES[mode]
    permissions = settings.setdefault("permissions", {})
    if not isinstance(permissions, dict):
        raise ValueError("permissions is not an object")
    changed = permissions.get("defaultMode") != want["defaultMode"] or bool(settings.get("skipDangerousModePermissionPrompt")) != want["skip"]
    if not changed:
        return False, before
    backups.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.fromtimestamp(now, dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = backups / f"settings-{stamp}-{before}-to-{mode}.json"
    backup.write_text(raw)
    os.chmod(backup, 0o600)
    permissions["defaultMode"] = want["defaultMode"]
    if want["skip"]:
        settings["skipDangerousModePermissionPrompt"] = True
    else:
        settings.pop("skipDangerousModePermissionPrompt", None)
    _write_json_atomic(settings_file, settings, settings_file.stat().st_mode & 0o777)
    return True, before


def _log(base: Path, entry: dict) -> None:
    with open(base / "switch.log", "a") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _recent(base: Path) -> list[dict]:
    try:
        lines = (base / "switch.log").read_text().splitlines()[-RECENT:]
    except FileNotFoundError:
        return []
    out = []
    for line in reversed(lines):
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def _seen_ids(base: Path) -> set[str]:
    try:
        return {json.loads(line).get("id") for line in (base / "switch.log").read_text().splitlines() if line.strip()}
    except (FileNotFoundError, ValueError):
        return set()


def _read_request(path: Path) -> dict:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_REQUEST_BYTES:
        raise ValueError("not_a_request_file")
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise ValueError("not_an_object")
    return data


def process(home: Path, verify, now: float | None = None) -> dict:
    """Handle every request in the inbox, then write the state the site shows."""
    now = time.time() if now is None else now
    base = mode_dir(home)
    inbox = base / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    os.chmod(base, 0o700)
    settings_file = settings_path(home)
    with open(base / ".lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        previous = {}
        try:
            previous = json.loads((base / "state.json").read_text())
        except (FileNotFoundError, ValueError):
            pass
        try:
            current, _ = observed_mode(json.loads(settings_file.read_text()))
        except (OSError, ValueError):
            current = "unknown"
        if previous.get("mode") in ("bypass", "standard", "other") and current not in (previous.get("mode"), "unknown"):
            _log(base, {"at": _iso(now), "event": "changed_outside", "from": previous.get("mode"), "mode": current})
        seen = _seen_ids(base)
        last_request = previous.get("last_request")
        requests = sorted((p for p in inbox.iterdir() if p.suffix == ".json"), key=lambda p: p.stat().st_mtime)
        for path in requests:
            entry = {"at": _iso(now), "event": "refused"}
            try:
                request = _read_request(path)
                request_id, mode = request.get("id"), request.get("mode")
                entry.update(id=request_id if isinstance(request_id, str) and REQUEST_ID.match(request_id) else None, mode=mode)
                requested_at = request.get("requested_at")
                if not entry["id"] or entry["id"] in seen:
                    raise ValueError("bad_or_repeated_id")
                if mode not in MODES:
                    raise ValueError("unknown_mode")
                if isinstance(requested_at, bool) or not isinstance(requested_at, (int, float)) or not (now - MAX_REQUEST_AGE <= requested_at <= now + 5):
                    raise ValueError("stale_request")
                by = verify(request.get("token"))
                if not by:
                    raise ValueError("not_signed_in_owner")
                changed, before = apply_mode(settings_file, base / "backups", mode, now)
                entry.update(event="switched" if changed else "unchanged", by=by, **{"from": before})
                current = mode
            except (OSError, ValueError) as error:
                entry["reason"] = str(error) if str(error) else type(error).__name__
            finally:
                path.unlink(missing_ok=True)
            _log(base, entry)
            if entry.get("id"):
                seen.add(entry["id"])
                last_request = {key: entry.get(key) for key in ("id", "event", "mode", "reason", "at")}
        try:
            settings = json.loads(settings_file.read_text())
            current, default_mode = observed_mode(settings)
            skip = bool(settings.get("skipDangerousModePermissionPrompt"))
        except (OSError, ValueError):
            current, default_mode, skip = "unknown", None, None
        recent = _recent(base)
        last_change = next((e for e in recent if e.get("event") in ("switched", "changed_outside")), None)
        state = {
            "schema": SCHEMA,
            "mode": current,
            "default_mode": default_mode,
            "skip_prompt": skip,
            "observed_at": _iso(now),
            "changed_at": (last_change or {}).get("at") or previous.get("changed_at"),
            "changed_by": (last_change or {}).get("by") if last_change else previous.get("changed_by"),
            "last_request": last_request,
            "recent": recent,
        }
        _write_json_atomic(base / "state.json", state, 0o600)
        return state


def _access_verifier(home: Path):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from dashboard_builder.cloudflare_access import AccessGate, configured_access_app, discover_access_app

    host = "command.meshly.fr"
    config = home / ".agent-bridge" / "cloudflare_access.json"
    gate = AccessGate(host, discover=lambda h: configured_access_app(config) or discover_access_app(h))
    return lambda token: gate.owner_email(token) if isinstance(token, str) else None


def main() -> int:
    home = Path.home()
    process(home, _access_verifier(home))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
