#!/usr/bin/env python3
"""Small stdlib health API for the MacBook Pro Command Center card."""
from __future__ import annotations

import http.server
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import threading
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit


HOST = os.environ.get("HEALTH_HOST", "0.0.0.0")
PORT = int(os.environ.get("HEALTH_PORT", "8880"))
UID = os.getuid()

WATCHED_SERVICES = [
    {
        "name": "Pro Health API",
        "label": "com.pirajoke.macbook-pro-health",
        "desc": "MacBook Pro telemetry for Command Center",
        "cat": "core",
        "runtime": "Python",
        "port": 8880,
    },
    {
        "name": "Agent Supervisor",
        "label": "com.mark.agent-supervisor",
        "desc": "Local agent supervision loop",
        "cat": "core",
        "runtime": "Shell",
    },
    {
        "name": "OmniHarness",
        "label": "com.mark.omniharness",
        "desc": "Local automation harness",
        "cat": "core",
        "runtime": "Shell",
    },
    {
        "name": "Murmur Daemon",
        "label": "com.mark.murmur-daemon",
        "desc": "Local voice / audio helper",
        "cat": "ondemand",
        "runtime": "Shell",
    },
    {
        "name": "Visible App Snapshot",
        "label": "com.mark.visible-app-snapshot",
        "desc": "Active app context snapshot",
        "cat": "scheduled",
        "runtime": "Shell",
    },
]


def run_cmd(args: list[str], timeout: float = 2.0) -> str:
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except Exception:
        return ""
    return (result.stdout or result.stderr or "").strip()


def parse_float(value: str, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def bytes_to_gb(value: float) -> float:
    return round(value / (1024 ** 3), 1)


def total_memory_bytes() -> int:
    out = run_cmd(["sysctl", "-n", "hw.memsize"])
    try:
        return int(out.splitlines()[0])
    except Exception:
        return 0


def top_last_sample() -> str:
    """Run top once with two samples and return only the last one.

    The first sample of `top -l N` is not a current reading (CPU usage there
    is not measured over a fresh interval), so we take the second sample,
    collected over a 1 s interval.
    """
    out = run_cmd(["top", "-l", "2", "-s", "1", "-n", "0"], timeout=5.0)
    starts = [m.start() for m in re.finditer(r"^Processes:", out, re.M)]
    if len(starts) >= 2:
        return out[starts[-1]:]
    return out


def gpu_snapshot() -> dict:
    """GPU stats from IOAccelerator PerformanceStatistics (no sudo needed)."""
    out = run_cmd(["ioreg", "-r", "-d", "1", "-c", "IOAccelerator"], timeout=2.0)
    result: dict = {}
    util = re.search(r'"Device Utilization %"\s*=\s*(\d+)', out)
    if util:
        result["gpu_percent"] = int(util.group(1))
    in_use = re.search(r'"In use system memory"\s*=\s*(\d+)', out)
    if in_use:
        result["gpu_memory_gb"] = bytes_to_gb(int(in_use.group(1)))
    alloc = re.search(r'"Alloc system memory"\s*=\s*(\d+)', out)
    if alloc:
        result["gpu_alloc_gb"] = bytes_to_gb(int(alloc.group(1)))
    return result


def memory_pressure_snapshot(total: int, top: str) -> dict:
    out = run_cmd(["memory_pressure"], timeout=3.0)
    free_pct_match = re.search(r"System-wide memory free percentage:\s+(\d+)%", out)
    free_pct = int(free_pct_match.group(1)) if free_pct_match else None

    swap = run_cmd(["sysctl", "vm.swapusage"])
    swap_used_gb = 0.0
    swap_match = re.search(r"used = ([\d.]+)M", swap)
    if swap_match:
        swap_used_gb = round(parse_float(swap_match.group(1)) / 1024, 1)

    physical_used_gb = 0.0
    phys_match = re.search(r"PhysMem:\s+([\d.]+)([GM]) used", top)
    if phys_match:
        value = parse_float(phys_match.group(1))
        physical_used_gb = round(value if phys_match.group(2) == "G" else value / 1024, 1)

    if free_pct is None:
        return {
            "pressure_free_percent": None,
            "pressure_used_gb": physical_used_gb,
            "available_gb": max(bytes_to_gb(total) - physical_used_gb, 0),
            "physical_used_gb": physical_used_gb,
            "swap_used_gb": swap_used_gb,
        }

    free_pct = max(0, min(100, free_pct))
    total_gb = bytes_to_gb(total)
    available_gb = round(total_gb * free_pct / 100, 1)
    pressure_used_gb = round(max(total_gb - available_gb, 0), 1)
    return {
        "pressure_free_percent": free_pct,
        "pressure_used_gb": pressure_used_gb,
        "available_gb": available_gb,
        "physical_used_gb": physical_used_gb,
        "swap_used_gb": swap_used_gb,
    }


def memory_snapshot(top: str) -> tuple[float, float, dict]:
    total = total_memory_bytes()
    if total <= 0:
        return 0.0, 0.0, {}

    out = run_cmd(["vm_stat"])
    page_size = 16384
    page_match = re.search(r"page size of (\d+) bytes", out)
    if page_match:
        page_size = int(page_match.group(1))

    pages: dict[str, int] = {}
    for line in out.splitlines():
        match = re.match(r"Pages ([\w ]+):\s+(\d+)\.", line.strip())
        if match:
            pages[match.group(1).strip().lower()] = int(match.group(2))

    free_pages = pages.get("free", 0) + pages.get("speculative", 0)
    free = free_pages * page_size
    used = max(total - free, 0)
    pressure = memory_pressure_snapshot(total, top)
    if "wired down" in pages:
        pressure["wired_gb"] = bytes_to_gb(pages["wired down"] * page_size)
    if "occupied by compressor" in pages:
        pressure["compressed_gb"] = bytes_to_gb(pages["occupied by compressor"] * page_size)
    # Use pressure-based memory for the dashboard gauge. The physical "used"
    # number on macOS includes cache/compression and looks scary even when
    # memory pressure is healthy.
    used_gb = pressure.get("pressure_used_gb") or bytes_to_gb(used)
    return used_gb, bytes_to_gb(total), pressure


def cpu_percent(top: str) -> float:
    idle_match = re.search(r"CPU usage:.*?([\d.]+)% idle", top)
    if idle_match:
        return round(max(0.0, 100.0 - parse_float(idle_match.group(1))), 1)

    try:
        ncpu = int(run_cmd(["sysctl", "-n", "hw.ncpu"]) or "1")
        return round(min(100.0, os.getloadavg()[0] / max(ncpu, 1) * 100), 1)
    except Exception:
        return 0.0


def uptime_string() -> str:
    out = run_cmd(["sysctl", "-n", "kern.boottime"])
    match = re.search(r"sec = (\d+)", out)
    if not match:
        return "unknown"
    seconds = max(0, int(time.time()) - int(match.group(1)))
    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes = remainder // 60
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def launchd_status(label: str) -> tuple[str, int | None]:
    out = run_cmd(["launchctl", "print", f"gui/{UID}/{label}"])
    if not out:
        return "stopped", None
    state_match = re.search(r"\bstate = (\w+)", out)
    pid_match = re.search(r"\bpid = (\d+)", out)
    state = state_match.group(1) if state_match else ""
    pid = int(pid_match.group(1)) if pid_match else None
    return ("running" if state == "running" else "stopped"), pid


def port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.2)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def services_snapshot() -> list[dict]:
    services = []
    for spec in WATCHED_SERVICES:
        status, pid = launchd_status(spec["label"])
        item = {
            "name": spec["name"],
            "label": spec["label"],
            "desc": spec["desc"],
            "cat": spec["cat"],
            "runtime": spec["runtime"],
            "status": status,
            "pid": pid,
            "project": "MacBook Pro",
        }
        if "port" in spec:
            item["port"] = spec["port"]
            item["port_ok"] = port_open(int(spec["port"]))
        services.append(item)
    return services


def system_snapshot() -> dict:
    disk = shutil.disk_usage(str(Path.home()))
    top = top_last_sample()
    mem_used, mem_total, mem_pressure = memory_snapshot(top)
    data = {
        "hostname": socket.gethostname(),
        "machine": "MacBook Pro",
        "cpu_percent": cpu_percent(top),
        "memory_used_gb": mem_used,
        "memory_total_gb": mem_total,
        "memory_available_gb": mem_pressure.get("available_gb"),
        "memory_physical_used_gb": mem_pressure.get("physical_used_gb"),
        "memory_pressure_free_percent": mem_pressure.get("pressure_free_percent"),
        "swap_used_gb": mem_pressure.get("swap_used_gb"),
        "disk_used_gb": bytes_to_gb(disk.used),
        "disk_total_gb": bytes_to_gb(disk.total),
        "uptime": uptime_string(),
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    if "wired_gb" in mem_pressure:
        data["memory_wired_gb"] = mem_pressure["wired_gb"]
    if "compressed_gb" in mem_pressure:
        data["memory_compressed_gb"] = mem_pressure["compressed_gb"]
    data.update(gpu_snapshot())
    return data


# --- Qwen (Ollama) on/off switch for Command Center -------------------------
# Mark 2026-11-18: «сделай переключатель для qwen в команд центре».
# On = `ollama serve` running with the model loaded in memory and kept there;
# off = model unloaded and the Ollama server stopped, so its ~18 GB is free.
OLLAMA_BIN = os.environ.get("OLLAMA_BIN", "/opt/homebrew/bin/ollama")
OLLAMA_URL = "http://127.0.0.1:11434"
QWEN_MODEL = os.environ.get("QWEN_MODEL", "qwen3.8:27b")
OLLAMA_LOG = Path.home() / ".ollama" / "serve.log"
# Only this Mac and the Mac mini (which serves Command Center and checks the
# owner) may switch Qwen; everyone else on the network can only read.
# The repository is public, so the Mac mini address is not written here: it
# comes from MACBOOK_CONTROL_ALLOW (comma-separated) or from one address per
# line in ~/.agent-bridge/macbook-control-allow, a local file on this Mac.
LOOPBACK_ADDRESSES = ("127.0.0.1", "::1")
CONTROL_ALLOW_FILE = Path.home() / ".agent-bridge" / "macbook-control-allow"


def load_control_allow(environ=None, allow_file: Path | None = None) -> set[str]:
    environ = os.environ if environ is None else environ
    allow_file = CONTROL_ALLOW_FILE if allow_file is None else allow_file
    allowed = set(LOOPBACK_ADDRESSES)
    for name in ("MACBOOK_CONTROL_ALLOW", "HEALTH_CONTROL_ALLOW"):
        allowed.update(part.strip() for part in environ.get(name, "").split(","))
    try:
        for line in allow_file.read_text(encoding="utf-8").splitlines():
            allowed.add(line.split("#", 1)[0].strip())
    except OSError:
        pass
    allowed.discard("")
    return allowed


CONTROL_ALLOW = load_control_allow()
_qwen_lock = threading.Lock()
_qwen_pending = {"state": None, "since": 0.0, "error": None}


def _ollama_json(method: str, path: str, payload: dict | None = None, timeout: float = 2.0):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        f"{OLLAMA_URL}{path}", data=data, method=method,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8")
    return json.loads(raw) if raw else {}


def _ollama_pids() -> list[int]:
    out = run_cmd(["/usr/sbin/lsof", "-t", "-nP", "-iTCP:11434", "-sTCP:LISTEN"])
    return [int(p) for p in out.split() if p.isdigit()]


def qwen_status() -> dict:
    running = port_open(11434)
    loaded = False
    vram_gb = None
    if running:
        try:
            for m in _ollama_json("GET", "/api/ps").get("models", []):
                if m.get("name") == QWEN_MODEL or m.get("model") == QWEN_MODEL:
                    loaded = True
                    if isinstance(m.get("size_vram"), (int, float)):
                        vram_gb = bytes_to_gb(m["size_vram"])
        except Exception:
            pass
    pending = _qwen_pending["state"]
    # A start or stop that has been going on for too long is reported as failed.
    if pending and time.time() - _qwen_pending["since"] > 240:
        _qwen_pending.update(state=None, error="timeout")
        pending = None
    if pending == "starting" and loaded:
        _qwen_pending.update(state=None, error=None)
        pending = None
    if pending == "stopping" and not running:
        _qwen_pending.update(state=None, error=None)
        pending = None
    state = pending or ("on" if loaded else "off")
    result = {"state": state, "model": QWEN_MODEL, "server_running": running, "loaded": loaded}
    if vram_gb is not None:
        result["memory_gb"] = vram_gb
    if _qwen_pending.get("error"):
        result["error"] = _qwen_pending["error"]
    return result


def _qwen_turn_on() -> None:
    try:
        if not port_open(11434):
            OLLAMA_LOG.parent.mkdir(parents=True, exist_ok=True)
            env = dict(os.environ)
            env["PATH"] = "/opt/homebrew/bin:" + env.get("PATH", "/usr/bin:/bin")
            env["HOME"] = str(Path.home())
            # Keep the model in memory until it is switched off here.
            env["OLLAMA_KEEP_ALIVE"] = "-1"
            log = open(OLLAMA_LOG, "ab")
            subprocess.Popen(
                [OLLAMA_BIN, "serve"], stdout=log, stderr=log, stdin=subprocess.DEVNULL,
                env=env, cwd=str(Path.home()), start_new_session=True,
            )
            for _ in range(60):
                if port_open(11434):
                    break
                time.sleep(0.5)
        # An empty generate request loads the model; keep_alive -1 pins it.
        _ollama_json("POST", "/api/generate", {"model": QWEN_MODEL, "keep_alive": -1}, timeout=200)
    except Exception as error:
        _qwen_pending.update(state=None, error=f"start_failed: {type(error).__name__}")


def _qwen_turn_off() -> None:
    try:
        if port_open(11434):
            try:
                _ollama_json("POST", "/api/generate", {"model": QWEN_MODEL, "keep_alive": 0}, timeout=20)
            except Exception:
                pass
            for pid in _ollama_pids():
                try:
                    os.kill(pid, signal.SIGTERM)
                except OSError:
                    pass
            for _ in range(30):
                if not port_open(11434):
                    break
                time.sleep(0.5)
            for pid in _ollama_pids():
                try:
                    os.kill(pid, signal.SIGKILL)
                except OSError:
                    pass
    except Exception as error:
        _qwen_pending.update(state=None, error=f"stop_failed: {type(error).__name__}")


def qwen_switch(action: str) -> dict:
    with _qwen_lock:
        if _qwen_pending["state"]:
            return qwen_status()
        target = _qwen_turn_on if action == "on" else _qwen_turn_off
        _qwen_pending.update(state="starting" if action == "on" else "stopping", since=time.time(), error=None)
        threading.Thread(target=target, daemon=True).start()
    return qwen_status()


# --- Ollama block and brew-service start/stop (coordinator contract 2026-11-18) ---
BREW_BIN = "/opt/homebrew/bin/brew"
_ollama_disk_cache = {"at": 0.0, "gb": None}


def _ollama_installed() -> bool:
    return os.path.exists(OLLAMA_BIN) or shutil.which("ollama") is not None


def _ollama_disk_gb():
    if time.time() - _ollama_disk_cache["at"] < 600:
        return _ollama_disk_cache["gb"]
    total = 0
    root = Path.home() / ".ollama" / "models"
    try:
        for dirpath, _dirs, files in os.walk(root):
            for name in files:
                try:
                    total += os.lstat(os.path.join(dirpath, name)).st_size
                except OSError:
                    pass
        gb = round(total / 1e9, 1)
    except Exception:
        gb = None
    _ollama_disk_cache.update(at=time.time(), gb=gb)
    return gb


def ollama_block() -> dict:
    installed = False
    try:
        installed = _ollama_installed()
        block = {"installed": installed, "running": False, "disk_gb": _ollama_disk_gb(), "loaded": []}
        try:
            models = _ollama_json("GET", "/api/ps", timeout=1.0).get("models", [])
        except Exception:
            return block
        block["running"] = True
        block["loaded"] = [
            {"name": m.get("name"), "size_gb": round((m.get("size") or 0) / 1e9, 1)}
            for m in models if isinstance(m, dict)
        ]
        return block
    except Exception:
        return {"installed": installed, "running": False, "loaded": []}


def ollama_brew_service(action: str) -> dict:
    env = dict(os.environ)
    env["PATH"] = "/opt/homebrew/bin:/opt/homebrew/sbin:" + env.get("PATH", "/usr/bin:/bin")
    env["HOME"] = str(Path.home())
    try:
        result = subprocess.run(
            [BREW_BIN, "services", action, "ollama"],
            capture_output=True, text=True, timeout=30, env=env,
        )
        output = (result.stdout or "") + (result.stderr or "")
        return {"ok": result.returncode == 0, "action": action, "output": output[-300:]}
    except Exception as error:
        return {"ok": False, "action": action, "output": f"{type(error).__name__}: {error}"[-300:]}


def payload_all() -> dict:
    services = services_snapshot()
    return {
        "status": "ok",
        "ollama": ollama_block(),
        "qwen": qwen_status(),
        "system": system_snapshot(),
        "services": services,
        "services_detailed": services,
        "projects": [],
    }


class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "MacBookProHealth/1.0"

    def _json(self, code: int, data: dict | list) -> None:
        raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(raw)

    def do_OPTIONS(self) -> None:
        self._json(200, {"status": "ok"})

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if path in {"/", "/api/health"}:
            self._json(200, {"status": "ok", "system": system_snapshot()})
            return
        if path == "/api/system":
            self._json(200, system_snapshot())
            return
        if path == "/api/services/detailed":
            self._json(200, {"services": services_snapshot()})
            return
        if path == "/api/all":
            self._json(200, payload_all())
            return
        if path == "/api/qwen":
            self._json(200, qwen_status())
            return
        self._json(404, {"error": "not_found", "path": path})

    def do_POST(self) -> None:
        path = urlsplit(self.path).path
        if path.startswith("/api/ollama/"):
            brew = re.fullmatch(r"/api/ollama/(start|stop)", path)
            if not brew:
                self._json(404, {"error": "not_found", "path": path})
                return
            if self.client_address[0] not in CONTROL_ALLOW:
                self._json(403, {"error": "control_not_allowed"})
                return
            self._json(200, ollama_brew_service(brew.group(1)))
            return
        match = re.fullmatch(r"/api/qwen/(on|off)", path)
        if not match:
            self._json(404, {"error": "not_found", "path": path})
            return
        if self.client_address[0] not in CONTROL_ALLOW:
            self._json(403, {"error": "control_not_allowed"})
            return
        self._json(200, qwen_switch(match.group(1)))

    def log_message(self, fmt: str, *args) -> None:
        print(f"{self.log_date_time_string()} {self.address_string()} {fmt % args}", flush=True)


def main() -> None:
    httpd = http.server.ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"MacBook Pro health API listening on {HOST}:{PORT}", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
