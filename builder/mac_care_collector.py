#!/usr/bin/env python3
"""Collect how a MacBook is being looked after and send it to the Mac mini.

Mark 2026-11-02 «визуализируй это в технике когда я нажимаю на мак про»: after the
MacBook Pro overheated, it got a CPU watchdog, a daily hygiene report, a weekly
restart and a list of switched-off agents. This collector reads those facts (and
firewall, pending updates, swap and the heaviest processes right now) every
15 minutes, writes ``~/.agent-bridge/mac-care/<machine>.json`` and, with
``--push-to``, copies it to the Mac mini, where Техника → MacBook Pro shows it to
the owner. It only reads: it never stops a process, deletes a file or changes a
setting. Anything it cannot read is written as ``null`` (unknown), never as «ok».

Mark 2026-11-08 «температуру компьютера в технике … чтобы мог трекать»: it also
reads the temperature sensors (Apple Silicon HID sensors, no sudo; ``macmon`` as a
fallback when installed) and macOS thermal pressure, and keeps a rolling 7-day
history in the same file. The Mac mini runs it too, without ``--push-to``.
"""
from __future__ import annotations

import argparse
import json
import os
import plistlib
import re
import socket
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

SCHEMA = 1
HOME = Path.home()
DEFAULT_OUT = HOME / ".agent-bridge" / "mac-care"
WATCHDOG_LOG = HOME / "Library" / "Logs" / "cpu-watchdog.log"
HYGIENE_REPORT = HOME / "Reports" / "mac-hygiene" / "latest.md"
DISABLED_AGENTS_DIR = HOME / "Library" / "LaunchAgents-disabled"
SOFTWARE_UPDATE_PLIST = Path("/Library/Preferences/com.apple.SoftwareUpdate.plist")
FIREWALL_TOOL = "/usr/libexec/ApplicationFirewall/socketfilterfw"
WATCHDOG_WEEK = timedelta(days=7)
TEXT_LIMIT = 160
THERMAL_HISTORY = timedelta(days=7)
# OSThermalNotification.h: what macOS itself thinks about the heat.
PRESSURE_LEVELS = {0: "nominal", 1: "moderate", 2: "heavy", 3: "trapping", 4: "sleeping"}

_STAMP = re.compile(r"(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}(?::\d{2})?)")
_SECRETS = re.compile(r"(sk-[A-Za-z0-9_-]{8,}|gh[pousr]_[A-Za-z0-9]{8,}|Bearer\s+\S+|token=\S+)", re.I)
_DAYS = "Sunday|Monday|Tuesday|Wednesday|Thursday|Friday|Saturday"


def iso_z(moment: datetime | None) -> str | None:
    if moment is None:
        return None
    return moment.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def run(command: list[str], timeout: int = 15) -> str | None:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout if result.returncode == 0 else None


def clean_text(value: str, limit: int = TEXT_LIMIT) -> str:
    """One short line with the home folder and anything secret-looking removed."""
    value = _SECRETS.sub("[скрыто]", value)
    value = value.replace(str(HOME), "~")
    value = re.sub(r"/Users/[^/\s]+", "~", value)
    value = re.sub(r"\s+", " ", value).strip(" -*#>|")
    return value[:limit]


def parse_stamp(line: str) -> datetime | None:
    match = _STAMP.search(line)
    if not match:
        return None
    clock = match.group(2) if match.group(2).count(":") == 2 else match.group(2) + ":00"
    try:
        # Logs on the Mac are written in its local time.
        return datetime.fromisoformat(f"{match.group(1)}T{clock}").astimezone()
    except ValueError:
        return None


def launchd_jobs(listing: str | None) -> dict[str, int | None]:
    """``launchctl list`` → {label: pid or None}."""
    jobs: dict[str, int | None] = {}
    for line in (listing or "").splitlines()[1:]:
        parts = line.split("\t")
        if len(parts) == 3:
            jobs[parts[2].strip()] = int(parts[0]) if parts[0].strip().isdigit() else None
    return jobs


def job_state(jobs: dict[str, int | None] | None, needle: str) -> str | None:
    """«loaded» when launchd knows a job whose label contains ``needle``; «missing» when not; None if unknown."""
    if jobs is None:
        return None
    return "loaded" if any(needle in label for label in jobs) else "missing"


def watchdog_status(log_text: str | None, jobs: dict[str, int | None] | None, now: datetime) -> dict[str, Any]:
    events_7d = None
    last_at = None
    last_event = ""
    if log_text is not None:
        events_7d = 0
        for line in log_text.splitlines():
            if not line.strip():
                continue
            stamp = parse_stamp(line)
            if stamp is None:
                continue
            if now - stamp <= WATCHDOG_WEEK:
                events_7d += 1
            if last_at is None or stamp >= last_at:
                last_at = stamp
                last_event = clean_text(_STAMP.sub("", line, count=1))
    return {"job": job_state(jobs, "cpu-watchdog"), "events_7d": events_7d,
            "last_event_at": iso_z(last_at), "last_event": last_event}


def hygiene_status(report: Path, jobs: dict[str, int | None] | None) -> dict[str, Any]:
    try:
        text = report.read_text(encoding="utf-8", errors="replace")
        report_at = datetime.fromtimestamp(report.stat().st_mtime, timezone.utc)
    except OSError:
        return {"job": job_state(jobs, "mac-hygiene"), "report_at": None, "headline": "", "attention": None}
    headline = ""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and not stripped.startswith("---"):
            headline = clean_text(stripped)
            break
    attention = sum(1 for line in text.splitlines() if re.search(r"⚠|❌|🔴|\bWARN|\bВнимание", line, re.I))
    return {"job": job_state(jobs, "mac-hygiene"), "report_at": iso_z(report_at), "headline": headline,
            "attention": attention}


def restart_status(sched: str | None, boot_seconds: float | None) -> dict[str, Any]:
    schedule = ""
    scheduled = None
    if sched is not None:
        scheduled = False
        for line in sched.splitlines():
            if re.search(r"\b(restart|shutdown)\b", line, re.I) and re.search(_DAYS + r"|weekdays|weekends|every day", line, re.I):
                scheduled = True
                schedule = clean_text(line)
                break
    boot_at = datetime.fromtimestamp(boot_seconds, timezone.utc) if boot_seconds else None
    return {"scheduled": scheduled, "schedule": schedule, "boot_at": iso_z(boot_at)}


def boot_time(sysctl: str | None) -> float | None:
    match = re.search(r"sec\s*=\s*(\d+)", sysctl or "")
    return float(match.group(1)) if match else None


def firewall_status(text: str | None) -> dict[str, Any]:
    if text is None:
        return {"enabled": None}
    lowered = text.lower()
    if "enabled" in lowered or "state = 1" in lowered or "state = 2" in lowered:
        return {"enabled": True}
    if "disabled" in lowered or "state = 0" in lowered:
        return {"enabled": False}
    return {"enabled": None}


def updates_status(plist_bytes: bytes | None) -> dict[str, Any]:
    if plist_bytes is None:
        return {"pending": None, "checked_at": None}
    try:
        data = plistlib.loads(plist_bytes)
    except Exception:
        return {"pending": None, "checked_at": None}
    pending = []
    for item in data.get("RecommendedUpdates") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("Display Name") or item.get("Identifier") or "").strip()
        version = str(item.get("Display Version") or "").strip()
        if name:
            pending.append(clean_text(f"{name} {version}" if version and version not in name else name, 80))
    checked = data.get("LastSuccessfulDate")
    checked_at = iso_z(checked.replace(tzinfo=timezone.utc)) if isinstance(checked, datetime) else None
    return {"pending": pending, "checked_at": checked_at}


def swap_status(text: str | None) -> dict[str, Any] | None:
    found = dict(re.findall(r"(total|used)\s*=\s*([\d.]+)M", text or ""))
    if "total" not in found or "used" not in found:
        return None
    return {"used_gb": round(float(found["used"]) / 1024, 1), "total_gb": round(float(found["total"]) / 1024, 1)}


def top_processes(text: str | None, limit: int = 3) -> list[dict[str, Any]] | None:
    if text is None:
        return None
    rows: list[dict[str, Any]] = []
    for line in text.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) != 2:
            continue
        try:
            cpu = float(parts[0].replace(",", "."))
        except ValueError:
            continue
        name = os.path.basename(parts[1].strip()) or parts[1].strip()
        rows.append({"name": clean_text(name, 40), "cpu": round(cpu)})
        if len(rows) >= limit:
            break
    return rows


def disabled_agents(folder: Path) -> int | None:
    try:
        return sum(1 for item in folder.iterdir() if item.suffix == ".plist")
    except OSError:
        return None


def read_bytes(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except OSError:
        return None


def read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


# ─── Temperature (Mark 2026-11-08) ───

def read_hid_temperatures() -> dict[str, float] | None:
    """Apple Silicon temperature sensors through IOKit HID, readable without sudo.

    Returns {sensor name: °C}. Called in a child process (``--sensors``) so a
    misbehaving private API can never take the collector down with it.
    """
    if sys.platform != "darwin":
        return None
    import ctypes

    try:
        iokit = ctypes.CDLL("/System/Library/Frameworks/IOKit.framework/IOKit")
        cf = ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
    except OSError:
        return None
    vp = ctypes.c_void_p
    utf8 = 0x08000100
    cf.CFStringCreateWithCString.restype = vp
    cf.CFStringCreateWithCString.argtypes = [vp, ctypes.c_char_p, ctypes.c_uint32]
    cf.CFNumberCreate.restype = vp
    cf.CFNumberCreate.argtypes = [vp, ctypes.c_int, vp]
    cf.CFDictionaryCreate.restype = vp
    cf.CFDictionaryCreate.argtypes = [vp, ctypes.POINTER(vp), ctypes.POINTER(vp), ctypes.c_long, vp, vp]
    cf.CFArrayGetCount.restype = ctypes.c_long
    cf.CFArrayGetCount.argtypes = [vp]
    cf.CFArrayGetValueAtIndex.restype = vp
    cf.CFArrayGetValueAtIndex.argtypes = [vp, ctypes.c_long]
    cf.CFStringGetCString.restype = ctypes.c_bool
    cf.CFStringGetCString.argtypes = [vp, ctypes.c_char_p, ctypes.c_long, ctypes.c_uint32]
    cf.CFGetTypeID.restype = ctypes.c_ulong
    cf.CFGetTypeID.argtypes = [vp]
    cf.CFStringGetTypeID.restype = ctypes.c_ulong
    cf.CFRelease.argtypes = [vp]
    iokit.IOHIDEventSystemClientCreate.restype = vp
    iokit.IOHIDEventSystemClientCreate.argtypes = [vp]
    iokit.IOHIDEventSystemClientSetMatching.restype = ctypes.c_int
    iokit.IOHIDEventSystemClientSetMatching.argtypes = [vp, vp]
    iokit.IOHIDEventSystemClientCopyServices.restype = vp
    iokit.IOHIDEventSystemClientCopyServices.argtypes = [vp]
    iokit.IOHIDServiceClientCopyProperty.restype = vp
    iokit.IOHIDServiceClientCopyProperty.argtypes = [vp, vp]
    iokit.IOHIDServiceClientCopyEvent.restype = vp
    iokit.IOHIDServiceClientCopyEvent.argtypes = [vp, ctypes.c_int64, ctypes.c_int32, ctypes.c_int64]
    iokit.IOHIDEventGetFloatValue.restype = ctypes.c_double
    iokit.IOHIDEventGetFloatValue.argtypes = [vp, ctypes.c_int32]

    def cfstr(text: str) -> int:
        return cf.CFStringCreateWithCString(None, text.encode(), utf8)

    def cfint(value: int) -> int:
        number = ctypes.c_int32(value)
        return cf.CFNumberCreate(None, 3, ctypes.byref(number))  # kCFNumberSInt32Type

    key_callbacks = ctypes.addressof(ctypes.c_char.in_dll(cf, "kCFTypeDictionaryKeyCallBacks"))
    value_callbacks = ctypes.addressof(ctypes.c_char.in_dll(cf, "kCFTypeDictionaryValueCallBacks"))
    keys = (vp * 2)(cfstr("PrimaryUsagePage"), cfstr("PrimaryUsage"))
    values = (vp * 2)(cfint(0xFF00), cfint(5))  # Apple vendor page, temperature sensor
    matching = cf.CFDictionaryCreate(None, keys, values, 2, key_callbacks, value_callbacks)
    client = iokit.IOHIDEventSystemClientCreate(None)
    if not client or not matching:
        return None
    iokit.IOHIDEventSystemClientSetMatching(client, matching)
    services = iokit.IOHIDEventSystemClientCopyServices(client)
    if not services:
        return None
    product_key = cfstr("Product")
    string_type = cf.CFStringGetTypeID()
    readings: dict[str, list[float]] = {}
    for index in range(cf.CFArrayGetCount(services)):
        service = cf.CFArrayGetValueAtIndex(services, index)
        if not service:
            continue
        name = ""
        prop = iokit.IOHIDServiceClientCopyProperty(service, product_key)
        if prop:
            if cf.CFGetTypeID(prop) == string_type:
                buffer = ctypes.create_string_buffer(256)
                if cf.CFStringGetCString(prop, buffer, 256, utf8):
                    name = buffer.value.decode("utf-8", "replace").strip()
            cf.CFRelease(prop)
        event = iokit.IOHIDServiceClientCopyEvent(service, 15, 0, 0)  # kIOHIDEventTypeTemperature
        if not event:
            continue
        value = iokit.IOHIDEventGetFloatValue(event, 15 << 16)
        cf.CFRelease(event)
        if 0 < value < 150:
            readings.setdefault(name or f"sensor {index}", []).append(float(value))
    cf.CFRelease(services)
    return {name: round(max(values), 1) for name, values in readings.items()}


def read_macmon_temperatures() -> dict[str, float] | None:
    """``macmon pipe`` (brew install macmon) also reads temperatures without sudo."""
    text = run(["macmon", "pipe", "-s", "1"], timeout=20)
    if not text:
        return None
    try:
        data = json.loads(text.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return None
    temp = data.get("temp") if isinstance(data, dict) else None
    if not isinstance(temp, dict):
        return None
    sensors = {}
    for key, name in (("cpu_temp_avg", "macmon cpu"), ("gpu_temp_avg", "macmon gpu")):
        value = temp.get(key)
        if isinstance(value, (int, float)) and 0 < value < 150:
            sensors[name] = round(float(value), 1)
    return sensors or None


def sensors_in_child() -> dict[str, float] | None:
    try:
        result = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--sensors"],
                                capture_output=True, text=True, timeout=20, check=False)
        data = json.loads(result.stdout) if result.returncode == 0 and result.stdout.strip() else None
    except (OSError, subprocess.SubprocessError, ValueError):
        data = None
    if isinstance(data, dict) and data:
        return {str(k): float(v) for k, v in data.items() if isinstance(v, (int, float))}
    return read_macmon_temperatures()


def _hottest(sensors: dict[str, float], test) -> float | None:
    values = [value for name, value in sensors.items() if test(name.lower())]
    return round(max(values), 1) if values else None


def thermal_status(sensors: dict[str, float] | None, pressure_text: str | None) -> dict[str, Any]:
    """Sensor names → the few numbers a person cares about.

    CPU = the hottest die sensor («PMU tdie*», «pACC/eACC MTR»); without those,
    the hottest PMU sensor except the fixed calibration value «tcal».
    """
    pressure = None
    match = re.search(r"(\d+)\s*$", (pressure_text or "").strip())
    if match:
        pressure = PRESSURE_LEVELS.get(int(match.group(1)))
    if not sensors:
        return {"cpu_c": None, "max_c": None, "ssd_c": None, "battery_c": None, "sensors": 0, "pressure": pressure}
    cpu = _hottest(sensors, lambda n: "tdie" in n or "acc mtr" in n or n == "macmon cpu")
    if cpu is None:
        cpu = _hottest(sensors, lambda n: n.startswith("pmu") and "tcal" not in n)
    return {
        "cpu_c": cpu,
        "max_c": _hottest(sensors, lambda n: "tcal" not in n),
        "ssd_c": _hottest(sensors, lambda n: "nand" in n),
        "battery_c": _hottest(sensors, lambda n: "battery" in n),
        "sensors": len(sensors),
        "pressure": pressure,
    }


def thermal_history(previous: Any, thermal: dict[str, Any], now: datetime) -> list[dict[str, Any]]:
    """Keep the last 7 days of readings: [{"t": iso, "cpu": °C, "p": pressure}]."""
    points = previous if isinstance(previous, list) else []
    cutoff = now - THERMAL_HISTORY
    kept = []
    for point in points:
        if not isinstance(point, dict):
            continue
        try:
            moment = datetime.fromisoformat(str(point.get("t", "")).replace("Z", "+00:00"))
        except ValueError:
            continue
        if cutoff <= moment < now:
            kept.append(point)
    if thermal.get("cpu_c") is not None or thermal.get("pressure") is not None:
        kept.append({"t": iso_z(now), "cpu": thermal.get("cpu_c"), "p": thermal.get("pressure")})
    return kept


def previous_payload(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def collect(now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    listing = run(["launchctl", "list"])
    jobs = launchd_jobs(listing) if listing is not None else None
    return {
        "watchdog": watchdog_status(read_text(WATCHDOG_LOG), jobs, now),
        "hygiene": hygiene_status(HYGIENE_REPORT, jobs),
        "restart": restart_status(run(["pmset", "-g", "sched"]), boot_time(run(["sysctl", "-n", "kern.boottime"]))),
        "firewall": firewall_status(run([FIREWALL_TOOL, "--getglobalstate"])),
        "updates": updates_status(read_bytes(SOFTWARE_UPDATE_PLIST)),
        "swap": swap_status(run(["sysctl", "vm.swapusage"])),
        "top_processes": top_processes(run(["ps", "-Ao", "pcpu=,comm=", "-r"])),
        "disabled_agents": disabled_agents(DISABLED_AGENTS_DIR),
        "thermal": thermal_status(sensors_in_child(),
                                  run(["notifyutil", "-g", "com.apple.system.thermalpressurelevel"])),
    }


def machine_name(value: str | None) -> str:
    raw = value or socket.gethostname().split(".", 1)[0]
    return re.sub(r"[^a-z0-9-]+", "-", raw.lower()).strip("-") or "mac"


def write_private(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(path)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--machine", default=None)
    parser.add_argument("--push-to", default=None, help="ssh host that receives this machine's care status")
    parser.add_argument("--remote-out", default=".agent-bridge/mac-care")
    parser.add_argument("--sensors", action="store_true", help="print the raw temperature sensors as JSON and exit")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.sensors:
        print(json.dumps(read_hid_temperatures() or {}, ensure_ascii=False))
        return 0
    started = time.monotonic()
    machine = machine_name(args.machine)
    now = datetime.now(timezone.utc)
    target = args.out / f"{machine}.json"
    payload = {"schema": SCHEMA, "machine": machine, "generated_at": iso_z(now), **collect(now)}
    payload["thermal_history"] = thermal_history(previous_payload(target).get("thermal_history"),
                                                 payload.get("thermal") or {}, now)
    write_private(target, json.dumps(payload, ensure_ascii=False, indent=1))
    result: dict[str, Any] = {"ok": True, "machine": machine, "seconds": round(time.monotonic() - started, 1)}
    if args.push_to:
        remote = args.remote_out.rstrip("/")
        try:
            subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", args.push_to,
                            f"mkdir -p {remote} && chmod 700 {remote}"], check=True, timeout=30)
            subprocess.run(["scp", "-q", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", str(target),
                            f"{args.push_to}:{remote}/"], check=True, timeout=60)
            result["pushed"] = True
        except (OSError, subprocess.SubprocessError):
            result.update(pushed=False, ok=False)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
