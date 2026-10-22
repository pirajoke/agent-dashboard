"""Which Mac mini services are really down (Mark 2026-10-14: «многие лежат сервисы»).

The health API reports every registered launchd job as running or stopped. Three kinds of
«stopped» are not a problem, so the list hides them:

- a scheduled job that launchd has loaded and whose last run exited cleanly is just waiting
  for its next run;
- a job switched off with ``launchctl disable`` is off on purpose;
- a job whose plist is gone and that launchd does not know is no longer installed.

A scheduled job that launchd has not loaded (what happened after the reboot of 2026-10-12) or
whose last run failed stays in view, with the reason in its description.
"""

from __future__ import annotations

import plistlib
import re
from pathlib import Path
from typing import Callable

LAUNCH_AGENTS_DIR = Path.home() / "Library" / "LaunchAgents"

NOT_LOADED_NOTE = "не загружена в launchd"
FAILED_NOTE = "последний запуск с ошибкой (код {code})"


def parse_launchctl_list(raw: str) -> dict[str, int | None]:
    """``launchctl list`` → {label: last exit status}, None when it never ran."""
    loaded: dict[str, int | None] = {}
    for line in raw.splitlines():
        parts = line.split("\t") if "\t" in line else line.split()
        if len(parts) < 3 or parts[0] == "PID":
            continue
        status = parts[1].strip()
        try:
            loaded[parts[2].strip()] = int(status)
        except ValueError:
            loaded[parts[2].strip()] = None
    return loaded


def parse_launchctl_running(raw: str) -> set[str]:
    """``launchctl list`` → labels that have a live process (a PID in the first column)."""
    running = set()
    for line in raw.splitlines():
        parts = line.split("\t") if "\t" in line else line.split()
        if len(parts) >= 3 and parts[0].strip().isdigit():
            running.add(parts[2].strip())
    return running


def parse_launchctl_disabled(raw: str) -> set[str] | None:
    """``launchctl print-disabled gui/<uid>`` → labels switched off, None if launchctl did not answer."""
    if "disabled services" not in raw:
        return None
    disabled = set()
    for line in raw.splitlines():
        match = re.search(r'"([^"]+)"\s*=>\s*(disabled|true|enabled|false)', line)
        if match and match.group(2) in {"disabled", "true"}:
            disabled.add(match.group(1))
    return disabled


def plist_schedule(path: Path) -> dict | None:
    """The schedule of a launchd plist: {"interval": seconds or None}, or None if it is not scheduled."""
    try:
        with path.open("rb") as handle:
            data = plistlib.load(handle)
    except (OSError, plistlib.InvalidFileException, ValueError):
        return None
    if not isinstance(data, dict) or data.get("KeepAlive") is True:
        return None
    interval = data.get("StartInterval")
    if isinstance(interval, int) and interval > 0:
        return {"interval": interval}
    if data.get("StartCalendarInterval"):
        return {"interval": None}
    return None


def _plist_path(service: dict) -> Path | None:
    raw = service.get("plist")
    if isinstance(raw, str) and raw.strip():
        return Path(raw.strip()).expanduser()
    label = service.get("label")
    if isinstance(label, str) and label.strip():
        return LAUNCH_AGENTS_DIR / f"{label.strip()}.plist"
    return None


def _with_note(service: dict, note: str) -> str:
    desc = str(service.get("desc") or "").strip()
    return f"{desc} · {note}" if desc else note


def normalize_services(
    services: list,
    *,
    loaded: dict[str, int | None],
    disabled: set[str],
    schedule_for: Callable[[Path], dict | None] = plist_schedule,
    plist_exists: Callable[[Path], bool] = Path.exists,
) -> list:
    """Drop the stopped services that are not down and mark scheduled jobs that need attention."""
    result = []
    for service in services:
        label = service.get("label") if isinstance(service, dict) else None
        if not isinstance(label, str) or not label.strip():
            result.append(service)
            continue
        label = label.strip()
        if label in disabled:
            continue
        if service.get("status") == "running":
            result.append(service)
            continue

        path = _plist_path(service)
        if label not in loaded and (path is None or not plist_exists(path)):
            continue

        schedule = schedule_for(path) if path is not None and plist_exists(path) else None
        if schedule is None and service.get("cat") != "scheduled":
            result.append(service)
            continue

        item = dict(service)
        if schedule and schedule.get("interval") and not item.get("interval"):
            item["interval"] = schedule["interval"]
        exit_code = loaded.get(label, item.get("exit_code"))
        if label not in loaded:
            item["cat"] = "core"
            item["desc"] = _with_note(item, NOT_LOADED_NOTE)
        elif exit_code not in (None, 0):
            item["cat"] = "core"
            item["exit_code"] = exit_code
            item["desc"] = _with_note(item, FAILED_NOTE.format(code=exit_code))
        else:
            item["cat"] = "scheduled"
        result.append(item)
    return result


# Agents that apps put in ~/Library/LaunchAgents for their own updates; not Mark's services.
VENDOR_PREFIXES = ("com.apple.", "com.google.", "com.microsoft.", "com.adobe.", "com.dropbox.", "com.docker.",
                   "com.openai.", "com.anthropic.", "us.zoom.", "com.spotify.", "com.tailscale.", "org.mozilla.",
                   "com.brave.", "com.getdropbox.", "com.valvesoftware.", "com.logi.", "com.logitech.")
UNLISTED_NOTE = "работает; добавлено само, раньше не было в списке"


def _readable_name(label: str) -> str:
    """com.pirajoke.health-lab → Health Lab; homebrew.mxcl.n8n → N8n."""
    for prefix in ("com.pirajoke.", "homebrew.mxcl.", "com.", "org.", "io."):
        if label.startswith(prefix):
            label = label[len(prefix):]
            break
    words = re.split(r"[-_.]+", label)
    return " ".join(word[:1].upper() + word[1:] for word in words if word) or label


def unlisted_running_services(
    services: list,
    *,
    running: set[str],
    disabled: set[str],
    agents_dir: Path | None = None,
    plist_exists: Callable[[Path], bool] = Path.exists,
) -> list:
    """Mark 2026-10-20: about 13 services run on the Mac mini but the page never showed them.

    Any job that runs now from a plist in ~/Library/LaunchAgents, is not in the health API
    registry, is not switched off and is not an app's own updater is added as running.
    """
    agents_dir = agents_dir or LAUNCH_AGENTS_DIR
    known = {str(item.get("label")).strip() for item in services if isinstance(item, dict) and item.get("label")}
    extra = []
    for label in sorted(running):
        if label in known or label in disabled or label.startswith(VENDOR_PREFIXES) or label.startswith("application."):
            continue
        plist = agents_dir / f"{label}.plist"
        if not plist_exists(plist):
            continue
        extra.append({"name": _readable_name(label), "label": label, "status": "running", "cat": "core",
                      "desc": UNLISTED_NOTE, "plist": str(plist), "unlisted": True})
    return extra


def normalize_payload(data, *, loaded: dict[str, int | None], disabled: set[str], running: set[str] | None = None, **kwargs):
    """Apply :func:`normalize_services` to the service lists of a health API answer.

    With ``running`` (labels with a live process), running jobs missing from the registry are added.
    """
    if not isinstance(data, dict):
        return data
    cleaned = dict(data)
    for key in ("services", "services_detailed"):
        if isinstance(cleaned.get(key), list):
            original = cleaned[key]
            cleaned[key] = normalize_services(original, loaded=loaded, disabled=disabled, **kwargs)
            if running:
                cleaned[key] = cleaned[key] + unlisted_running_services(
                    original, running=running, disabled=disabled,
                    plist_exists=kwargs.get("plist_exists", Path.exists))
    return cleaned
