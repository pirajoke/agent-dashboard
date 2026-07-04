#!/usr/bin/env python3
"""Dashboard HTTP server with API for mode switching and live data."""
from __future__ import annotations

import base64
import http.server
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

PORT = 7777
HOME = Path.home()
ORCH_FILE = HOME / ".agent-bridge" / "orchestrator.json"
USAGE_FILE = HOME / ".agent-bridge" / "usage_snapshots.json"
BUILD_SCRIPT = HOME / "scripts" / "build-agent-dashboard.py"
SCRIPTS_DIR = HOME / "scripts"
LAUNCH_AGENTS_DIR = HOME / "Library" / "LaunchAgents"
GITHUB_TOKEN_FILE = HOME / ".agent-bridge" / "dashboard_github_token"
GITHUB_REPO = "pirajoke/agent-dashboard"
BRIDGE_API_URL = os.environ.get("BRIDGE_API_URL", "http://127.0.0.1:8899").rstrip("/")
HEALTH_API_URL = os.environ.get("HEALTH_API_URL", "http://127.0.0.1:8880").rstrip("/")
AIR_HEALTH_API_URL = os.environ.get("AIR_HEALTH_API_URL", "http://100.118.34.14:8880").rstrip("/")
PUBLIC_HOSTS = {"command.meshly.fr"}
PUBLIC_API_PATHS = {
    "/api/health",
    "/api/system",
    "/api/projects",
    "/api/costs",
    "/api/services/detailed",
    "/api/all",
}
PUBLIC_LOCAL_PATHS = {
    "/api/local-services",
}
SENSITIVE_SERVICE_FIELDS = {"config", "env_file", "env_vars", "log", "plist"}

# Services that the orchestrator toggle controls
MANAGED_SERVICES = [
    "com.pirajoke.light-linear-worker",
    "com.pirajoke.claude-linear-responder",
    "com.pirajoke.claude-autonomous-executor",
    "com.pirajoke.codex-linear-executor",
]

LOCAL_SERVICE_WATCH = [
    {"name": "tag-website", "kind": "launchd", "label": "com.pirajoke.tag-website"},
    {"name": "meshly-api", "kind": "launchd", "label": "com.pirajoke.meshly-api"},
    {"name": "turkish-ai-agent", "kind": "launchd", "label": "com.pirajoke.turkish-ai-agent"},
    {"name": "fastdata-webhook", "kind": "launchd", "label": "com.pirajoke.fastdata-webhook"},
    {"name": "cloudflared-m4", "kind": "launchd", "label": "com.pirajoke.cloudflared-m4"},
    {"name": "dashboard-rebuild", "kind": "launchd", "label": "com.pirajoke.dashboard-rebuild"},
    {"name": "generate-live-feed", "kind": "launchd", "label": "com.pirajoke.generate-live-feed"},
    {"name": "linear-bot", "kind": "launchd", "label": "com.pirajoke.linear-bot"},
    {"name": "max-context-bot", "kind": "launchd", "label": "com.pirajoke.max-context-bot"},
    {"name": "stock-content-bot", "kind": "launchd", "label": "com.pirajoke.stock-content-bot"},
    {"name": "handy-voice-router", "kind": "launchd", "label": "com.pirajoke.handy-voice-router"},
    {"name": "postgresql@16", "kind": "launchd", "label": "homebrew.mxcl.postgresql@16"},
    {"name": "next dev", "kind": "process", "match": "next dev"},
]


def _run_text(cmd: list[str], timeout: int = 5) -> str:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return ((result.stdout or "") + (result.stderr or "")).strip()
    except Exception:
        return ""


def _agent_auth_snapshot() -> dict:
    candidates = [
        "/opt/homebrew/bin/claude",
        "/usr/local/bin/claude",
        shutil.which("claude"),
    ]
    claude_cmd = next((cmd for cmd in candidates if cmd and Path(cmd).exists()), None)
    if not claude_cmd:
        return {
            "provider": "Claude",
            "available": False,
            "logged_in": False,
            "status": "missing",
            "message": "claude CLI not found on Mac Mini",
        }
    try:
        result = subprocess.run(
            [claude_cmd, "auth", "status"],
            capture_output=True,
            text=True,
            timeout=8,
        )
    except Exception as exc:
        return {
            "provider": "Claude",
            "available": True,
            "logged_in": False,
            "status": "error",
            "message": str(exc),
        }

    stdout = (result.stdout or "").strip()
    stderr = (result.stderr or "").strip()
    data = {}
    if stdout.startswith("{"):
        try:
            data = json.loads(stdout)
        except Exception:
            data = {}
    logged_in = data.get("loggedIn")
    status = "ok" if result.returncode == 0 and logged_in is True else "blocked"
    message = "Claude CLI is ready" if status == "ok" else "Run claude auth login on Mac Mini"
    return {
        "provider": "Claude",
        "available": True,
        "logged_in": bool(logged_in),
        "status": status,
        "auth_method": data.get("authMethod"),
        "api_provider": data.get("apiProvider"),
        "exit_code": result.returncode,
        "message": message,
        "stderr": stderr[:240],
    }


def _launchctl_disabled(uid: int) -> dict[str, bool]:
    raw = _run_text(["launchctl", "print-disabled", f"gui/{uid}"])
    flags = {}
    for line in raw.splitlines():
        match = re.search(r'"([^"]+)" => (enabled|disabled)', line)
        if match:
            flags[match.group(1)] = match.group(2) == "disabled"
    return flags


def _local_service_snapshot() -> dict:
    uid = os.getuid()
    disabled_flags = _launchctl_disabled(uid)
    process_table = _run_text(["ps", "-axo", "pid=,command="], timeout=10)

    items = []
    enabled_count = 0
    running_count = 0
    launchd_total = 0

    for spec in LOCAL_SERVICE_WATCH:
        if spec["kind"] == "launchd":
            launchd_total += 1
            label = spec["label"]
            disabled = disabled_flags.get(label, False)
            raw = _run_text(["launchctl", "print", f"gui/{uid}/{label}"])
            loaded = bool(raw) and "could not find service" not in raw.lower() and "not found in domain" not in raw.lower()

            state_match = re.search(r"state = ([^\n]+)", raw)
            active_match = re.search(r"active count = (\d+)", raw)
            state = state_match.group(1).strip() if state_match else ("not loaded" if not loaded else "loaded")
            active_count = int(active_match.group(1)) if active_match else 0
            running = loaded and ("running" in state.lower() or active_count > 0)

            if disabled:
                status = "disabled"
                detail = "launchd disabled"
            elif running:
                status = "running"
                detail = f"launchd {state.lower()}"
            else:
                status = "enabled"
                detail = "launchd loaded" if loaded else "launchd waiting"

            if not disabled:
                enabled_count += 1
        else:
            matches = []
            for line in process_table.splitlines():
                if spec["match"] in line and "grep" not in line and "egrep" not in line:
                    pid = line.strip().split(None, 1)[0]
                    matches.append(pid)
            running = bool(matches)
            status = "running" if running else "stopped"
            detail = f"{len(matches)} proc" if running else "manual process"
            disabled = None

        if running:
            running_count += 1

        items.append(
            {
                "name": spec["name"],
                "kind": spec["kind"],
                "status": status,
                "detail": detail,
                "enabled": None if spec["kind"] == "process" else (not disabled),
                "running": running,
            }
        )

    return {
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "enabled_count": enabled_count,
        "launchd_total": launchd_total,
        "running_count": running_count,
        "total": len(items),
        "items": items,
    }


def _bridge_request(method: str, path: str, payload: dict | None = None) -> dict:
    data = None
    headers = {"Content-Type": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(f"{BRIDGE_API_URL}{path}", data=data, method=method, headers=headers)
    with urllib.request.urlopen(req, timeout=10) as resp:
        raw = resp.read().decode("utf-8")
    return json.loads(raw) if raw else {}


def _health_request(method: str, path: str, payload: dict | None = None) -> dict:
    data = None
    headers = {"Content-Type": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(f"{HEALTH_API_URL}{path}", data=data, method=method, headers=headers)
    with urllib.request.urlopen(req, timeout=10) as resp:
        raw = resp.read().decode("utf-8")
    return json.loads(raw) if raw else {}


def _air_health_request(method: str, path: str, payload: dict | None = None) -> dict:
    data = None
    headers = {"Content-Type": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(f"{AIR_HEALTH_API_URL}{path}", data=data, method=method, headers=headers)
    with urllib.request.urlopen(req, timeout=10) as resp:
        raw = resp.read().decode("utf-8")
    return json.loads(raw) if raw else {}


def _air_proxy_path(path: str) -> str | None:
    if path.startswith("/api/air/"):
        return "/api/" + path[len("/api/air/"):]
    return None


def _public_service(service: dict) -> dict:
    return {k: v for k, v in service.items() if k not in SENSITIVE_SERVICE_FIELDS}


def _public_dashboard_payload(data: dict) -> dict:
    if not isinstance(data, dict):
        return data
    cleaned = dict(data)
    for key in ("services", "services_detailed"):
        if isinstance(cleaned.get(key), list):
            cleaned[key] = [
                _public_service(item) if isinstance(item, dict) else item
                for item in cleaned[key]
            ]
    return cleaned


class Handler(http.server.SimpleHTTPRequestHandler):
    def _host_name(self) -> str:
        return self.headers.get("Host", "").split(":", 1)[0].lower()

    def _is_public_request(self) -> bool:
        return self._host_name() in PUBLIC_HOSTS

    def _cors_origin(self) -> str:
        if self._is_public_request():
            return f"https://{self._host_name()}"
        return "*"

    def translate_path(self, path):
        if path == '/agent-dashboard.html' or path == '/legacy-dashboard.html':
            return str(HOME / 'agent-dashboard.html')
        if path == '/live-feed.json' or path == '/scripts/live-feed.json':
            return str(HOME / 'scripts' / 'live-feed.json')
        if path == '/' or path == '/index.html':
            return str(HOME / 'mac-mini-dashboard' / 'index.html')
        return str(HOME / path.lstrip('/'))

    def do_POST(self):
        if self._is_public_request():
            self._json_response(403, {"error": "public_dashboard_read_only"})
            return

        parsed = urlsplit(self.path)
        air_path = _air_proxy_path(parsed.path)
        if air_path and re.match(r"^/api/service/.+/(start|stop)$", air_path):
            try:
                self._json_response(200, _air_health_request("POST", air_path))
            except Exception as e:
                self._json_response(502, {"error": str(e)})
            return

        if re.match(r"^/api/service/.+/(start|stop)$", self.path):
            try:
                self._json_response(200, _health_request("POST", self.path))
            except Exception as e:
                self._json_response(502, {"error": str(e)})
            return

        if self.path == '/api/mode':
            length = int(self.headers.get('Content-Length', 0))
            body = json.loads(self.rfile.read(length)) if length else {}
            new_mode = body.get("mode", "")
            valid = ("claude-claude", "claude-codex", "codex-codex")
            if new_mode not in valid:
                self._json_response(400, {"error": f"Invalid mode. Use: {valid}"})
                return
            # Update orchestrator.json
            orch = json.loads(ORCH_FILE.read_text()) if ORCH_FILE.exists() else {}
            orch["mode"] = new_mode
            orch["changed_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            orch["changed_reason"] = "dashboard"
            ORCH_FILE.write_text(json.dumps(orch, indent=2) + "\n")
            # Rebuild dashboard
            subprocess.Popen([sys.executable, str(BUILD_SCRIPT)],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self._json_response(200, {"mode": new_mode, "status": "ok"})

        elif self.path == '/api/github/token':
            length = int(self.headers.get('Content-Length', 0))
            body = json.loads(self.rfile.read(length)) if length else {}
            token = str(body.get("token", "")).strip()
            if not token:
                self._json_response(400, {"error": "token is required"})
                return
            GITHUB_TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
            GITHUB_TOKEN_FILE.write_text(token + "\n")
            GITHUB_TOKEN_FILE.chmod(0o600)
            self._json_response(200, {"status": "ok"})

        elif self.path == '/api/github/commit':
            length = int(self.headers.get('Content-Length', 0))
            body = json.loads(self.rfile.read(length)) if length else {}
            repo_path = str(body.get("path", "")).strip()
            message = str(body.get("message", "")).strip()
            data = body.get("data")
            if not repo_path or not message:
                self._json_response(400, {"error": "path and message are required"})
                return
            if data is None:
                self._json_response(400, {"error": "data is required"})
                return
            if not GITHUB_TOKEN_FILE.exists():
                self._json_response(401, {"error": "token_missing"})
                return
            token = GITHUB_TOKEN_FILE.read_text().strip()
            if not token:
                self._json_response(401, {"error": "token_missing"})
                return
            try:
                ok = _github_commit(
                    token=token,
                    repo=GITHUB_REPO,
                    path=repo_path,
                    message=message,
                    data=data,
                )
                if ok:
                    self._json_response(200, {"status": "ok"})
                else:
                    self._json_response(502, {"error": "github_commit_failed"})
            except urllib.error.HTTPError as e:
                if e.code in (401, 403):
                    self._json_response(401, {"error": "token_invalid"})
                else:
                    self._json_response(502, {"error": f"github_http_{e.code}"})
            except Exception as e:
                self._json_response(500, {"error": str(e)})

        elif self.path == '/api/usage':
            length = int(self.headers.get('Content-Length', 0))
            body = json.loads(self.rfile.read(length)) if length else {}
            agent = body.get("agent", "").lower()
            if agent not in ("claude", "codex"):
                self._json_response(400, {"error": "agent must be 'claude' or 'codex'"})
                return
            # Load existing
            data = json.loads(USAGE_FILE.read_text()) if USAGE_FILE.exists() else {}
            now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            entry = data.get(agent, {})
            entry["updated_at"] = now
            if "pct" in body:
                entry["used_pct"] = round(float(body["pct"]), 1)
            if "amount" in body:
                entry["used_amount"] = body["amount"]
            if "limit" in body:
                entry["limit"] = body["limit"]
            if "resets" in body:
                entry["resets"] = body["resets"]
            # History
            history = entry.get("history", [])
            history.append({"ts": now, "pct": entry.get("used_pct", 0),
                            "amount": entry.get("used_amount", "")})
            entry["history"] = history[-30:]
            data[agent] = entry
            USAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
            USAGE_FILE.write_text(json.dumps(data, indent=2) + "\n")
            # Rebuild
            subprocess.Popen([sys.executable, str(BUILD_SCRIPT)],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self._json_response(200, {"status": "ok", "agent": agent,
                                       "pct": entry.get("used_pct", 0)})

        elif self.path == '/api/orchestrator/toggle':
            length = int(self.headers.get('Content-Length', 0))
            body = json.loads(self.rfile.read(length)) if length else {}
            activate = body.get("active", True)
            results = []
            for svc in MANAGED_SERVICES:
                plist = LAUNCH_AGENTS_DIR / f"{svc}.plist"
                if not plist.exists():
                    results.append({"service": svc, "status": "plist_missing"})
                    continue
                try:
                    if activate:
                        subprocess.run(
                            ["launchctl", "load", "-w", str(plist)],
                            capture_output=True, text=True, timeout=10,
                        )
                        results.append({"service": svc, "status": "loaded"})
                    else:
                        subprocess.run(
                            ["launchctl", "unload", "-w", str(plist)],
                            capture_output=True, text=True, timeout=10,
                        )
                        results.append({"service": svc, "status": "unloaded"})
                except Exception as e:
                    results.append({"service": svc, "status": f"error: {e}"})
            # Update orchestrator.json
            orch = json.loads(ORCH_FILE.read_text()) if ORCH_FILE.exists() else {}
            orch["paused"] = not activate
            orch["toggle_ts"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            orch["toggle_source"] = "dashboard-toggle"
            ORCH_FILE.write_text(json.dumps(orch, indent=2) + "\n")
            # Rebuild dashboard
            subprocess.Popen([sys.executable, str(BUILD_SCRIPT)],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self._json_response(200, {"active": activate, "services": results})

        elif self.path == '/api/model':
            length = int(self.headers.get('Content-Length', 0))
            body = json.loads(self.rfile.read(length)) if length else {}
            agent = str(body.get("agent", "")).strip()
            model = str(body.get("model", "")).strip()
            if not agent or not model:
                self._json_response(400, {"error": "agent and model are required"})
                return
            orch = json.loads(ORCH_FILE.read_text()) if ORCH_FILE.exists() else {}
            models = orch.get("agent_models", {})
            models[agent] = model
            orch["agent_models"] = models
            orch["model_changed_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            ORCH_FILE.write_text(json.dumps(orch, indent=2) + "\n")
            subprocess.Popen([sys.executable, str(BUILD_SCRIPT)],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self._json_response(200, {"status": "ok", "agent": agent, "model": model})

        elif self.path == '/api/orchestrator/run':
            orch = json.loads(ORCH_FILE.read_text()) if ORCH_FILE.exists() else {}
            mode = orch.get("mode", "claude-codex")
            launched = None
            try:
                if mode == "claude-claude":
                    launched = SCRIPTS_DIR / "claude-autonomous-executor.py"
                    subprocess.Popen(
                        [sys.executable, str(launched)],
                        cwd=str(SCRIPTS_DIR),
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                else:
                    launched = SCRIPTS_DIR / "light-linear-worker.py"
                    subprocess.Popen(
                        [sys.executable, str(launched)],
                        cwd=str(SCRIPTS_DIR),
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                self._json_response(200, {"status": "ok", "mode": mode, "launched": str(launched)})
            except Exception as e:
                self._json_response(500, {"error": str(e), "mode": mode})

        elif self.path == '/api/rebuild':
            subprocess.Popen([sys.executable, str(BUILD_SCRIPT)],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self._json_response(200, {"status": "rebuilding"})

        elif self.path == '/api/bridge/dispatch':
            length = int(self.headers.get('Content-Length', 0))
            body = json.loads(self.rfile.read(length)) if length else {}
            desc = str(body.get("description", "")).strip()
            if not desc:
                self._json_response(400, {"error": "description is required"})
                return
            payload = {
                "description": desc,
                "agent_role": body.get("agent_role") or "BUILDER",
                "project": body.get("project") or None,
            }
            try:
                self._json_response(200, _bridge_request("POST", "/api/dispatch", payload))
            except Exception as e:
                self._json_response(502, {"error": str(e)})

        elif self.path == '/api/service/restart':
            length = int(self.headers.get('Content-Length', 0))
            body = json.loads(self.rfile.read(length)) if length else {}
            name = str(body.get("name", "")).strip()
            # Find the service spec
            spec = next((s for s in LOCAL_SERVICE_WATCH if s["name"] == name), None)
            if not spec:
                # Also check managed services
                spec = next((s for s in MANAGED_SERVICES if name in s), None)
                if spec:
                    spec = {"name": name, "kind": "launchd", "label": spec}
            if not spec:
                self._json_response(400, {"error": f"Unknown service: {name}"})
                return
            if spec["kind"] == "launchd":
                label = spec["label"]
                uid = os.getuid()
                # kickstart = stop + start
                result = subprocess.run(
                    ["launchctl", "kickstart", "-k", f"gui/{uid}/{label}"],
                    capture_output=True, text=True, timeout=10,
                )
                if result.returncode == 0:
                    self._json_response(200, {"status": "restarted", "service": name})
                else:
                    # Fallback: bootout + bootstrap
                    plist = LAUNCH_AGENTS_DIR / f"{label}.plist"
                    if plist.exists():
                        subprocess.run(["launchctl", "bootout", f"gui/{uid}/{label}"],
                                       capture_output=True, timeout=5)
                        subprocess.run(["launchctl", "bootstrap", f"gui/{uid}", str(plist)],
                                       capture_output=True, timeout=5)
                        self._json_response(200, {"status": "restarted_via_bootstrap", "service": name})
                    else:
                        self._json_response(500, {"error": result.stderr or "kickstart failed"})
            else:
                self._json_response(400, {"error": "Can only restart launchd services"})

        elif self.path == '/api/service/logs':
            length = int(self.headers.get('Content-Length', 0))
            body = json.loads(self.rfile.read(length)) if length else {}
            name = str(body.get("name", "")).strip()
            lines_n = int(body.get("lines", 20))
            # Find log files
            log_dir = HOME / "Library" / "Logs"
            candidates = [
                log_dir / f"{name}.log",
                log_dir / f"{name}.err.log",
                HOME / ".agent-bridge" / "logs" / f"{name}.log",
            ]
            spec = next((s for s in LOCAL_SERVICE_WATCH if s["name"] == name), None)
            if spec and spec["kind"] == "launchd":
                candidates.append(log_dir / f"{spec['label']}.log")
                candidates.append(log_dir / f"{spec['label']}.err.log")

            log_content = ""
            log_file = None
            for candidate in candidates:
                if candidate.exists() and candidate.stat().st_size > 0:
                    log_file = str(candidate)
                    try:
                        all_lines = candidate.read_text(errors="replace").splitlines()
                        log_content = "\n".join(all_lines[-lines_n:])
                    except Exception:
                        pass
                    break
            self._json_response(200, {
                "service": name,
                "file": log_file,
                "lines": log_content,
            })

        else:
            self._json_response(404, {"error": "not found"})

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin', self._cors_origin())
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_GET(self):
        parsed = urlsplit(self.path)
        air_path = _air_proxy_path(parsed.path)
        if self._is_public_request():
            if parsed.path.startswith("/api/logs/") or (air_path and air_path.startswith("/api/logs/")):
                self._json_response(403, {"error": "public_logs_disabled"})
                return
            if (
                parsed.path not in PUBLIC_API_PATHS
                and parsed.path not in PUBLIC_LOCAL_PATHS
                and air_path not in PUBLIC_API_PATHS
                and parsed.path not in ("/", "/index.html", "/favicon.ico")
            ):
                self.send_error(404)
                return

        if air_path:
            try:
                suffix = f"?{parsed.query}" if parsed.query else ""
                data = _air_health_request("GET", f"{air_path}{suffix}")
                if self._is_public_request():
                    data = _public_dashboard_payload(data)
                self._json_response(200, data)
            except Exception as e:
                self._json_response(502, {"error": str(e)})
            return

        if parsed.path == '/api/local-services':
            self._json_response(200, _local_service_snapshot())
            return
        if parsed.path == '/api/health':
            try:
                suffix = f"?{parsed.query}" if parsed.query else ""
                data = _health_request("GET", f"{parsed.path}{suffix}")
                if self._is_public_request():
                    data = _public_dashboard_payload(data)
                else:
                    data["agent_auth"] = _agent_auth_snapshot()
                self._json_response(200, data)
            except Exception as e:
                self._json_response(502, {"error": str(e)})
            return
        if parsed.path in PUBLIC_API_PATHS or (not self._is_public_request() and parsed.path.startswith('/api/logs/')):
            try:
                suffix = f"?{parsed.query}" if parsed.query else ""
                data = _health_request("GET", f"{parsed.path}{suffix}")
                if self._is_public_request():
                    data = _public_dashboard_payload(data)
                self._json_response(200, data)
            except Exception as e:
                self._json_response(502, {"error": str(e)})
            return
        if parsed.path == '/api/bridge/tasks':
            suffix = parsed.query or "limit=12&include_messages=1"
            if "include_messages" not in suffix:
                suffix += "&include_messages=1"
            try:
                self._json_response(200, _bridge_request("GET", f"/api/tasks?{suffix}"))
            except Exception as e:
                self._json_response(502, {"error": str(e), "tasks": []})
            return
        if parsed.path == '/api/bridge/status':
            try:
                self._json_response(200, _bridge_request("GET", "/api/status"))
            except Exception as e:
                self._json_response(502, {"error": str(e), "tasks": {}})
            return
        if self.path == '/api/github/token':
            has_token = GITHUB_TOKEN_FILE.exists() and bool(GITHUB_TOKEN_FILE.read_text().strip())
            self._json_response(200, {"has_token": has_token})
            return
        if self.path == '/api/orchestrator':
            if ORCH_FILE.exists():
                data = json.loads(ORCH_FILE.read_text())
            else:
                data = {"mode": "claude-codex"}
            self._json_response(200, data)
            return
        if self.path == '/api/usage':
            data = json.loads(USAGE_FILE.read_text()) if USAGE_FILE.exists() else {}
            self._json_response(200, data)
            return
        if self.path == '/bookmarklets':
            self._serve_bookmarklets_page()
            return
        super().do_GET()

    def do_DELETE(self):
        if self._is_public_request():
            self._json_response(403, {"error": "public_dashboard_read_only"})
            return

        if self.path == '/api/github/token':
            try:
                if GITHUB_TOKEN_FILE.exists():
                    GITHUB_TOKEN_FILE.unlink()
            except Exception:
                pass
            self._json_response(200, {"status": "ok"})
            return
        self._json_response(404, {"error": "not found"})

    def _serve_bookmarklets_page(self):
        html = """<!DOCTYPE html><html><head><meta charset="utf-8">
<title>Usage Bookmarklets</title>
<style>
body{background:#0d1117;color:#c9d1d9;font-family:system-ui;max-width:700px;margin:2rem auto;padding:1rem}
h1{color:#ff6b35;font-size:1.5rem}
.bm{display:inline-block;padding:0.8rem 1.5rem;margin:0.5rem;border-radius:8px;
font-weight:700;font-size:1rem;text-decoration:none;cursor:grab}
.bm-claude{background:#ff6b35;color:#000}
.bm-codex{background:#3fb950;color:#000}
code{background:rgba(255,255,255,0.1);padding:0.2rem 0.5rem;border-radius:4px;font-size:0.85rem}
.step{margin:1rem 0;padding:0.75rem;border-left:3px solid #ff6b35;background:rgba(255,255,255,0.02)}
.step b{color:#ff6b35}
</style></head><body>
<h1>Usage Tracker Bookmarklets</h1>
<p>Drag these buttons to your bookmarks bar:</p>

<a class="bm bm-claude" href="javascript:void(function(){var d=document.body.innerText,p=d.match(/(\\d+(?:\\.\\d+)?)\\s*%/g),a=d.match(/\\$([\\d,.]+)/g);var pct=prompt('Claude usage %:',p?p[0].replace('%',''):'');if(!pct)return;var amt=prompt('Amount spent (e.g. $67):',a&&a[0]?a[0]:'');var lim=prompt('Plan limit:','200');var res=prompt('Resets on:','');fetch('http://localhost:7777/api/usage',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({agent:'claude',pct:parseFloat(pct),amount:amt||'',limit:lim||'200',resets:res||''})}).then(r=>r.json()).then(j=>alert('Claude updated: '+j.pct+'%')).catch(e=>alert('Error: '+e));}())">📊 Claude Usage</a>

<a class="bm bm-codex" href="javascript:void(function(){var d=document.body.innerText,p=d.match(/(\\d+(?:\\.\\d+)?)\\s*%/g),a=d.match(/\\$([\\d,.]+)/g);var pct=prompt('Codex usage %:',p?p[0].replace('%',''):'');if(!pct)return;var amt=prompt('Amount spent (e.g. $24):',a&&a[0]?a[0]:'');var lim=prompt('Plan limit:','200');var res=prompt('Resets on:','');fetch('http://localhost:7777/api/usage',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({agent:'codex',pct:parseFloat(pct),amount:amt||'',limit:lim||'200',resets:res||''})}).then(r=>r.json()).then(j=>alert('Codex updated: '+j.pct+'%')).catch(e=>alert('Error: '+e));}())">📊 Codex Usage</a>

<h2>How to use</h2>
<div class="step"><b>1.</b> Drag the button above to your bookmarks bar</div>
<div class="step"><b>2.</b> Open <code>claude.ai/settings/usage</code> or <code>chatgpt.com/codex/settings/usage</code></div>
<div class="step"><b>3.</b> Click the bookmarklet — it reads numbers from the page and pre-fills them</div>
<div class="step"><b>4.</b> Confirm → data sent to dashboard, auto-rebuilds</div>

<h2>Or use CLI</h2>
<pre style="background:rgba(255,255,255,0.05);padding:1rem;border-radius:8px">
python3 ~/scripts/orchestrator_tokens.py update claude 67 '$134' '200' 'Apr 15'
python3 ~/scripts/orchestrator_tokens.py update codex 23 '$46' '200' 'Apr 15'
</pre>
</body></html>"""
        body = html.encode()
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', len(body))
        self.end_headers()
        self.wfile.write(body)

    def _json_response(self, code, data):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', len(body))
        self.send_header('Cache-Control', 'no-cache')
        self.send_header('Access-Control-Allow-Origin', self._cors_origin())
        self.end_headers()
        self.wfile.write(body)

    def end_headers(self):
        self.send_header('Cache-Control', 'no-cache')
        self.send_header('Access-Control-Allow-Origin', self._cors_origin())
        super().end_headers()

    def log_message(self, format, *args):
        pass

def _github_api_request(token, method, url, payload=None):
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        raw = resp.read().decode("utf-8")
    return json.loads(raw) if raw else {}


def _github_commit(token, repo, path, message, data):
    base_url = f"https://api.github.com/repos/{repo}/contents/{path}"
    sha = None
    try:
        existing = _github_api_request(token, "GET", base_url)
        sha = existing.get("sha")
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise

    encoded = base64.b64encode(
        json.dumps(data, ensure_ascii=False).encode("utf-8")
    ).decode("ascii")
    body = {
        "message": message,
        "content": encoded,
    }
    if sha:
        body["sha"] = sha
    _github_api_request(token, "PUT", base_url, body)
    return True


if __name__ == '__main__':
    server = http.server.HTTPServer(('127.0.0.1', PORT), Handler)
    print(f"Dashboard server on http://localhost:{PORT}")
    server.serve_forever()
