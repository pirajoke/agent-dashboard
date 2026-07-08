#!/usr/bin/env python3
"""Dashboard HTTP server with API for mode switching and live data."""
from __future__ import annotations

import base64
import http.server
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

PORT = 7777
HOME = Path.home()
ORCH_FILE = HOME / ".agent-bridge" / "orchestrator.json"
USAGE_FILE = HOME / ".agent-bridge" / "usage_snapshots.json"
BUILD_SCRIPT = HOME / "scripts" / "build-agent-dashboard.py"
SCRIPTS_DIR = HOME / "scripts"
LAUNCH_AGENTS_DIR = HOME / "Library" / "LaunchAgents"
GITHUB_TOKEN_FILE = HOME / ".agent-bridge" / "dashboard_github_token"
JARVIS_DASHBOARD_RUN_TOKEN_FILE = HOME / ".agent-bridge" / "dashboard_run_token"
JARVIS_PIPELINE_SCRIPT = SCRIPTS_DIR / "jarvis-agent-pipeline"
JARVIS_PIPELINE_REPORT_DIR = HOME / "Library" / "Logs" / "jarvis-agent-pipeline"
JARVIS_PIPELINE_LOG_FILE = HOME / "Library" / "Logs" / "dashboard-jarvis-pipeline-run.log"
GITHUB_REPO = "pirajoke/agent-dashboard"
BRIDGE_API_URL = os.environ.get("BRIDGE_API_URL", "http://127.0.0.1:8899").rstrip("/")
HEALTH_API_URL = os.environ.get("HEALTH_API_URL", "http://127.0.0.1:8880").rstrip("/")
AIR_HEALTH_API_URL = os.environ.get("AIR_HEALTH_API_URL", "http://100.118.34.14:8880").rstrip("/")
PRO_HEALTH_API_URL = os.environ.get("PRO_HEALTH_API_URL", "http://100.74.94.2:8880").rstrip("/")
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
PUBLIC_BRIDGE_PATHS = {
    "/api/bridge/tasks",
    "/api/bridge/status",
}
PUBLIC_FILE_PATHS = {
    "/",
    "/index.html",
    "/agent-dashboard.html",
    "/legacy-dashboard.html",
    "/dashboard-assets/ai-town-32x32folk.png",
    "/favicon.ico",
    "/live-feed.json",
    "/scripts/live-feed.json",
}
JARVIS_PROJECTS = {
    "jarvis": HOME / "jarvis",
}
SENSITIVE_SERVICE_FIELDS = {"config", "env_file", "env_vars", "log", "plist"}
PUBLIC_TASK_METADATA_FIELDS = {
    "assigned_agent",
    "blocked_reason",
    "calls",
    "duration_s",
    "entrypoint",
    "event",
    "failure_reason",
    "project",
    "route_reason",
    "route_source",
    "status",
    "tools",
    "triggered_by",
}

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


def _dashboard_run_token() -> str:
    token = os.environ.get("DASHBOARD_RUN_TOKEN", "").strip()
    if token:
        return token
    JARVIS_DASHBOARD_RUN_TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not JARVIS_DASHBOARD_RUN_TOKEN_FILE.exists() or not JARVIS_DASHBOARD_RUN_TOKEN_FILE.read_text().strip():
        JARVIS_DASHBOARD_RUN_TOKEN_FILE.write_text(secrets.token_urlsafe(24) + "\n")
        JARVIS_DASHBOARD_RUN_TOKEN_FILE.chmod(0o600)
    return JARVIS_DASHBOARD_RUN_TOKEN_FILE.read_text().strip()


def _parse_pipeline_status(report_text: str) -> str:
    match = re.search(r"(?im)^-\s*Status:\s*([a-z_ -]+)\s*$", report_text)
    if match:
        status = match.group(1).strip().lower().replace(" ", "_")
        if status == "done":
            if re.search(r"(?i)\bNEEDS_APPROVAL\b", report_text):
                return "needs_approval"
            if re.search(r"(?m)^##\s+FAIL\s*$", report_text):
                return "failed"
        return status
    if re.search(r"(?m)^ROLE_FAILED=", report_text):
        return "failed"
    if "\n## Tester\n" in report_text:
        return "tester_running"
    if "\n## Builder\n" in report_text:
        return "builder_running"
    if "\n## Supervisor\n" in report_text:
        return "supervisor_running"
    return "starting"


def _pipeline_report_field(report_text: str, field: str) -> str:
    match = re.search(rf"(?im)^-\s*{re.escape(field)}:\s*(.+?)\s*$", report_text)
    return match.group(1).strip() if match else ""


def _compact_report_text(value: str, limit: int = 720) -> str:
    value = re.sub(r"\n{3,}", "\n\n", (value or "").strip())
    if len(value) <= limit:
        return value
    return value[: limit - 3].rstrip() + "..."


def _pipeline_sections(report_text: str) -> dict:
    sections = {}
    pipeline_titles = {"Supervisor", "Builder", "Tester", "Result"}
    matches = [
        match
        for match in re.finditer(r"(?m)^##\s+(.+?)\s*$", report_text)
        if match.group(1).strip() in pipeline_titles
    ]
    for idx, match in enumerate(matches):
        title = match.group(1).strip()
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(report_text)
        sections[title] = _compact_report_text(report_text[start:end])
    return sections


def _pipeline_steps(status: str, sections: dict) -> list[dict]:
    status = (status or "waiting").lower()
    roles = [
        ("supervisor", "Supervisor", "turns request into acceptance criteria"),
        ("builder", "Builder", "implements scoped work or returns exact handoff"),
        ("tester", "Tester", "checks request vs result and evidence"),
    ]
    steps = []
    for key, title, default_detail in roles:
        if title in sections:
            state = "done"
            detail = _compact_report_text(sections[title], 220)
        else:
            state = "pending"
            detail = default_detail
        steps.append({"role": key, "label": title, "state": state, "detail": detail})

    if status == "starting":
        steps[0]["state"] = "working"
    elif status == "supervisor_running":
        steps[0]["state"] = "working"
    elif status == "builder_running":
        steps[0]["state"] = "done"
        steps[1]["state"] = "working"
    elif status == "tester_running":
        steps[0]["state"] = "done"
        steps[1]["state"] = "done"
        steps[2]["state"] = "working"
    elif status == "done":
        for step in steps:
            step["state"] = "done"
    elif status == "needs_approval":
        for step in steps:
            if "NEEDS_APPROVAL" in sections.get(step["label"], ""):
                step["state"] = "failed"
            elif step["label"] in sections:
                step["state"] = "done"
            else:
                step["state"] = "pending"
    elif status == "failed":
        failed_role = ""
        for title, text in sections.items():
            role_match = re.search(r"(?m)^ROLE_FAILED=([a-z_-]+)", text)
            if role_match:
                failed_role = role_match.group(1).lower()
                break
        if failed_role:
            for step in steps:
                if step["role"] == failed_role:
                    step["state"] = "failed"
                elif step["state"] == "pending":
                    step["state"] = "pending"
            return steps
        failed = False
        for step in steps:
            if step["state"] != "done" and not failed:
                step["state"] = "failed"
                failed = True

    return steps


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
    with urllib.request.urlopen(req, timeout=5) as resp:
        raw = resp.read().decode("utf-8")
    return json.loads(raw) if raw else {}


def _pro_health_request(method: str, path: str, payload: dict | None = None) -> dict:
    data = None
    headers = {"Content-Type": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(f"{PRO_HEALTH_API_URL}{path}", data=data, method=method, headers=headers)
    with urllib.request.urlopen(req, timeout=5) as resp:
        raw = resp.read().decode("utf-8")
    return json.loads(raw) if raw else {}


def _air_proxy_path(path: str) -> str | None:
    if path.startswith("/api/air/"):
        return "/api/" + path[len("/api/air/"):]
    return None


def _pro_proxy_path(path: str) -> str | None:
    if path.startswith("/api/pro/"):
        return "/api/" + path[len("/api/pro/"):]
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


def _clip_public_text(value, limit: int = 280) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        try:
            value = json.dumps(value, ensure_ascii=False)
        except Exception:
            value = str(value)
    value = re.sub(r"\s+", " ", value).strip()
    if "authentication_error" in value.lower():
        return "authentication_error: credentials are invalid, expired, or unavailable."
    return value[:limit]


def _public_task_metadata(metadata) -> dict:
    if not isinstance(metadata, dict):
        return {}
    return {
        key: metadata[key]
        for key in PUBLIC_TASK_METADATA_FIELDS
        if key in metadata
    }


def _public_bridge_message(message: dict) -> dict:
    return {
        "id": message.get("id"),
        "task_id": message.get("task_id"),
        "sender": message.get("sender"),
        "receiver": message.get("receiver"),
        "type": message.get("type"),
        "body": _clip_public_text(message.get("body"), 360),
        "created_at": message.get("created_at"),
        "metadata": _public_task_metadata(message.get("metadata")),
    }


def _public_bridge_task(task: dict) -> dict:
    return {
        "id": task.get("id"),
        "status": task.get("status"),
        "agent_role": task.get("agent_role"),
        "project": task.get("project"),
        "description": _clip_public_text(task.get("description"), 260),
        "result": _clip_public_text(task.get("result"), 260) if task.get("result") else None,
        "error": _clip_public_text(task.get("error"), 260) if task.get("error") else None,
        "created_at": task.get("created_at"),
        "claimed_at": task.get("claimed_at"),
        "completed_at": task.get("completed_at"),
        "updated_at": task.get("updated_at"),
        "metadata": _public_task_metadata(task.get("metadata")),
        "messages": [
            _public_bridge_message(message)
            for message in (task.get("messages") or [])[-6:]
            if isinstance(message, dict)
        ],
    }


def _public_bridge_payload(data: dict) -> dict:
    if not isinstance(data, dict):
        return data
    cleaned = dict(data)
    if isinstance(cleaned.get("tasks"), list):
        cleaned["tasks"] = [
            _public_bridge_task(task) if isinstance(task, dict) else task
            for task in cleaned["tasks"][:12]
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

    def _read_json_body(self, max_bytes: int = 4096) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length > max_bytes:
            raise ValueError(f"request body too large; max {max_bytes} bytes")
        return json.loads(self.rfile.read(length)) if length else {}

    def _dashboard_run_authorized(self) -> bool:
        if not self._is_public_request():
            return True
        expected = _dashboard_run_token()
        provided = self.headers.get("X-Dashboard-Run-Token", "").strip()
        return bool(provided) and secrets.compare_digest(provided, expected)

    def _require_dashboard_run_auth(self) -> bool:
        if self._dashboard_run_authorized():
            return True
        self._json_response(
            401,
            {
                "error": "dashboard_run_token_required",
                "message": "Public task launch is locked by dashboard token.",
            },
        )
        return False

    def _redirect_legacy_dashboard(self) -> None:
        self.send_response(302)
        self.send_header("Location", "/?tab=agents&v=pixel-agents")
        self.end_headers()

    def translate_path(self, path):
        clean_path = urlsplit(path).path
        if clean_path == '/agent-dashboard.html' or clean_path == '/legacy-dashboard.html':
            return str(HOME / 'agent-dashboard.html')
        if clean_path == '/live-feed.json' or clean_path == '/scripts/live-feed.json':
            return str(HOME / 'scripts' / 'live-feed.json')
        if clean_path == '/' or clean_path == '/index.html':
            return str(HOME / 'mac-mini-dashboard' / 'index.html')
        return str(HOME / clean_path.lstrip('/'))

    def do_POST(self):
        parsed = urlsplit(self.path)
        if parsed.path == '/api/jarvis/pipeline/run':
            self._handle_jarvis_pipeline_run()
            return

        if self._is_public_request():
            self._json_response(403, {"error": "public_dashboard_read_only"})
            return

        air_path = _air_proxy_path(parsed.path)
        pro_path = _pro_proxy_path(parsed.path)
        if air_path and re.match(r"^/api/service/.+/(start|stop)$", air_path):
            try:
                self._json_response(200, _air_health_request("POST", air_path))
            except Exception as e:
                self._json_response(502, {"error": str(e)})
            return
        if pro_path and re.match(r"^/api/service/.+/(start|stop)$", pro_path):
            try:
                self._json_response(200, _pro_health_request("POST", pro_path))
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

    def _handle_jarvis_pipeline_run(self):
        if not self._require_dashboard_run_auth():
            return
        try:
            body = self._read_json_body(max_bytes=8192)
        except Exception as exc:
            self._json_response(400, {"error": str(exc)})
            return

        task = str(body.get("task", "")).strip()
        if not task:
            self._json_response(400, {"error": "task is required"})
            return
        if len(task) > 1200:
            self._json_response(400, {"error": "task is too long; max 1200 chars"})
            return

        project_key = str(body.get("project") or "jarvis").strip().lower()
        project_dir = JARVIS_PROJECTS.get(project_key)
        if not project_dir:
            self._json_response(400, {"error": "unknown project", "projects": sorted(JARVIS_PROJECTS)})
            return
        if not project_dir.exists():
            self._json_response(500, {"error": "project directory missing", "path": str(project_dir)})
            return
        if not JARVIS_PIPELINE_SCRIPT.exists():
            self._json_response(500, {"error": "pipeline script missing", "path": str(JARVIS_PIPELINE_SCRIPT)})
            return

        run_id = f"{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(3)}"
        report_path = JARVIS_PIPELINE_REPORT_DIR / f"{run_id}.md"

        if bool(body.get("dry_run")):
            self._json_response(
                200,
                {
                    "status": "dry_run",
                    "run_id": run_id,
                    "project": project_key,
                    "project_dir": str(project_dir),
                    "report_path": str(report_path),
                    "task": task,
                    "steps": _pipeline_steps("starting", {}),
                },
            )
            return

        JARVIS_PIPELINE_REPORT_DIR.mkdir(parents=True, exist_ok=True)
        JARVIS_PIPELINE_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        env.update(
            {
                "JARVIS_PROJECT_DIR": str(project_dir),
                "JARVIS_PROJECT_NAME": project_key,
                "JARVIS_AGENT_RUN_ID": run_id,
                "JARVIS_AGENT_REPORT_DIR": str(JARVIS_PIPELINE_REPORT_DIR),
            }
        )
        try:
            log_file = JARVIS_PIPELINE_LOG_FILE.open("a", encoding="utf-8")
            proc = subprocess.Popen(
                [str(JARVIS_PIPELINE_SCRIPT), task],
                cwd=str(project_dir),
                env=env,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            log_file.close()
        except Exception as exc:
            self._json_response(500, {"error": str(exc)})
            return

        self._json_response(
            202,
            {
                "status": "started",
                "pid": proc.pid,
                "run_id": run_id,
                "project": project_key,
                "project_dir": str(project_dir),
                "report_path": str(report_path),
                "task": task,
                "steps": _pipeline_steps("starting", {}),
            },
        )

    def _handle_jarvis_pipeline_status(self, parsed):
        if not self._require_dashboard_run_auth():
            return

        query = parse_qs(parsed.query)
        run_id = (query.get("run_id") or [""])[0].strip()
        report_path = None
        if run_id:
            if not re.match(r"^[A-Za-z0-9._-]+$", run_id):
                self._json_response(400, {"error": "invalid run_id"})
                return
            report_path = JARVIS_PIPELINE_REPORT_DIR / f"{run_id}.md"
        else:
            reports = sorted(JARVIS_PIPELINE_REPORT_DIR.glob("*.md"), key=lambda item: item.stat().st_mtime)
            if reports:
                report_path = reports[-1]
                run_id = report_path.stem

        if not report_path or not report_path.exists():
            self._json_response(
                200,
                {
                    "exists": False,
                    "run_id": run_id or None,
                    "status": "waiting",
                    "report_path": str(report_path) if report_path else None,
                    "steps": _pipeline_steps("waiting", {}),
                    "report_tail": "",
                },
            )
            return

        try:
            report_text = report_path.read_text(errors="replace")
        except Exception as exc:
            self._json_response(500, {"error": str(exc), "run_id": run_id})
            return

        lines = report_text.splitlines()
        status = _parse_pipeline_status(report_text)
        sections = _pipeline_sections(report_text)
        stat = report_path.stat()
        self._json_response(
            200,
            {
                "exists": True,
                "run_id": run_id,
                "status": status,
                "report_path": str(report_path),
                "project_dir": _pipeline_report_field(report_text, "Project"),
                "project": Path(_pipeline_report_field(report_text, "Project")).name
                if _pipeline_report_field(report_text, "Project")
                else None,
                "task": _pipeline_report_field(report_text, "Task"),
                "route": _pipeline_report_field(report_text, "Route"),
                "model": _pipeline_report_field(report_text, "Model"),
                "sections": sections,
                "steps": _pipeline_steps(status, sections),
                "updated_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "bytes": stat.st_size,
                "report_tail": "\n".join(lines[-80:]),
            },
        )

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin', self._cors_origin())
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, X-Dashboard-Run-Token')
        self.end_headers()

    def do_GET(self):
        parsed = urlsplit(self.path)
        if parsed.path in {"/agent-dashboard.html", "/legacy-dashboard.html"}:
            self._redirect_legacy_dashboard()
            return
        if parsed.path == '/api/jarvis/pipeline/status':
            self._handle_jarvis_pipeline_status(parsed)
            return

        air_path = _air_proxy_path(parsed.path)
        pro_path = _pro_proxy_path(parsed.path)
        if self._is_public_request():
            if (
                parsed.path.startswith("/api/logs/")
                or (air_path and air_path.startswith("/api/logs/"))
                or (pro_path and pro_path.startswith("/api/logs/"))
            ):
                self._json_response(403, {"error": "public_logs_disabled"})
                return
            if (
                parsed.path not in PUBLIC_API_PATHS
                and parsed.path not in PUBLIC_LOCAL_PATHS
                and parsed.path not in PUBLIC_BRIDGE_PATHS
                and air_path not in PUBLIC_API_PATHS
                and pro_path not in PUBLIC_API_PATHS
                and parsed.path not in PUBLIC_FILE_PATHS
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
        if pro_path:
            try:
                suffix = f"?{parsed.query}" if parsed.query else ""
                data = _pro_health_request("GET", f"{pro_path}{suffix}")
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
            if self._is_public_request():
                suffix = "limit=12&include_messages=1"
            try:
                data = _bridge_request("GET", f"/api/tasks?{suffix}")
                if self._is_public_request():
                    data = _public_bridge_payload(data)
                self._json_response(200, data)
            except Exception as e:
                self._json_response(502, {"error": str(e), "tasks": []})
            return
        if parsed.path == '/api/bridge/status':
            try:
                data = _bridge_request("GET", "/api/status")
                if self._is_public_request():
                    data = _public_bridge_payload(data)
                self._json_response(200, data)
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

    def do_HEAD(self):
        parsed = urlsplit(self.path)
        if parsed.path in {"/agent-dashboard.html", "/legacy-dashboard.html"}:
            self._redirect_legacy_dashboard()
            return
        super().do_HEAD()

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
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, X-Dashboard-Run-Token')
        self.end_headers()
        self.wfile.write(body)

    def end_headers(self):
        parsed = urlsplit(self.path)
        if parsed.path in {"/", "/index.html", "/agent-dashboard.html", "/legacy-dashboard.html"}:
            self.send_header("Cache-Control", "no-store, no-cache, max-age=0, must-revalidate")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
        else:
            self.send_header('Cache-Control', 'no-cache')
        self.send_header('Access-Control-Allow-Origin', self._cors_origin())
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, X-Dashboard-Run-Token')
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


class DashboardHTTPServer(http.server.ThreadingHTTPServer):
    daemon_threads = True


if __name__ == '__main__':
    server = DashboardHTTPServer(('127.0.0.1', PORT), Handler)
    print(f"Dashboard server on http://localhost:{PORT}")
    server.serve_forever()
