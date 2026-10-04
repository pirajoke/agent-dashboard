"""Isolated browser fixtures. Binds loopback, never contacts live services.

Run: PYTHONPATH=builder python3 builder/tests/preview_command_center.py
The printed local URL accepts ?fixture=empty|stale|unavailable|anonymous|changed.
The default waiting scenario provides one choice and one active task.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import http.server
import json
import mimetypes
from pathlib import Path
import tempfile
from urllib.parse import parse_qs, urlsplit

from test_owner_decisions import SERVER, event, snapshot

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_TOKEN = "isolated-preview-owner"
STARTED = datetime.now(timezone.utc)
MODE = "waiting"


def fixture_tasks():
    if MODE == "unavailable":
        raise OSError("fixture unavailable")
    updated = STARTED - timedelta(minutes=31) if MODE == "stale" else STARTED
    work = event(task_id="preview-active", event_id="preview-work", status="testing",
                 project="ACCOUNTABLE OS", updated_at=updated.isoformat(),
                 work_summary="Проверяем результат и собираем подтверждения",
                 next_step="Отчёт проверки с результатами")
    waiting = event(updated_at=updated.isoformat(), task_id="preview-choice", event_id="preview-choice-event")
    waiting["decision"]["question"] = "Как подготовить следующий результат?"
    if MODE == "changed":
        waiting["decision"]["options"][0]["cons"] = "Новая оценка ограничений"
    data = snapshot([work] if MODE == "empty" else [waiting, work])
    data["tasks"][0]["updated_at"] = updated.isoformat()
    return data


def fixture_bridge(method, path, payload=None):
    if method != "GET":
        raise AssertionError("fixture must not dispatch work")
    return fixture_tasks()


SERVER._bridge_request = fixture_bridge
SERVER._dashboard_run_token = lambda **kw: FIXTURE_TOKEN


class PreviewHandler(SERVER.Handler):
    def log_message(self, *_args):
        pass

    def end_headers(self):
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; frame-src 'self'")
        super().end_headers()

    def document(self, text, content_type="text/html; charset=utf-8"):
        data = text.encode() if isinstance(text, str) else text
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        global MODE
        parsed = urlsplit(self.path)
        query = parse_qs(parsed.query)
        if parsed.path.startswith('/fixture/'):
            mode = parsed.path.removeprefix('/fixture/')
            if mode in {'waiting', 'changed', 'empty', 'stale', 'unavailable'}:
                MODE = mode
                self._json_response(200, {'fixture': MODE})
            else:
                self.send_error(404)
            return
        if parsed.path == "/":
            MODE = query.get("fixture", ["waiting"])[0]
            html = (ROOT / "mac-mini-dashboard/index.html").read_text()
            # Only the served fixture copy changes origin selection. Product
            # telemetry functions remain byte-for-byte the existing source.
            html = html.replace("const IS_LOCALHOST_PAGE = ['localhost', '127.0.0.1', ''].includes(window.location.hostname);", "const IS_LOCALHOST_PAGE = false;")
            html = html.replace("const LOCAL_API = 'http://localhost:8880';", "const LOCAL_API = window.location.origin;")
            token = "localStorage.removeItem('command-center.jarvis-run-token');" if MODE == "anonymous" else f"localStorage.setItem('command-center.jarvis-run-token', {json.dumps(FIXTURE_TOKEN)});"
            html = html.replace("<script>", "<script>" + token, 1)
            self.document(html)
            return
        if parsed.path in {"/api/manager/decisions", "/api/manager/decisions/responses"}:
            self._handle_manager_decisions(responses=parsed.path.endswith("/responses"))
            return
        if parsed.path == "/api/manager/departments":
            try:
                payload = SERVER._department_campus_payload(fixture_tasks(), owner_view=self._decision_owner_authorized())
            except OSError:
                payload = {"state": "unavailable", "events": []}
            self._json_response(200, payload)
            return
        if parsed.path == "/department-campus.html":
            self.document(SERVER._department_campus_document())
            return
        if parsed.path.startswith("/dashboard-assets/"):
            path = ROOT / parsed.path.lstrip("/")
            if path.is_file() and path.resolve().is_relative_to((ROOT / "dashboard-assets").resolve()):
                self.document(path.read_bytes(), mimetypes.guess_type(path.name)[0] or "application/octet-stream")
            else:
                self.send_error(404)
            return
        if parsed.path in {"/api/all", "/api/air/all", "/api/pro/all"}:
            self._json_response(200, {
                "system": {"hostname": "Preview computer", "cpu_percent": 23, "memory_used_gb": 7, "memory_total_gb": 16, "disk_used_gb": 80, "disk_total_gb": 256, "uptime": "2 days"},
                "services": [{"id": "fixture-service", "name": "Fixture Service", "description": "Isolated preview", "status": "running", "runtime": "Python", "port": 8080, "cat": "core"}],
            })
            return
        if parsed.path.startswith("/api/"):
            self._json_response(200, {"status": "ok", "tasks": [], "services": [], "history": [], "counts": {}})
            return
        self.send_error(404)

    def do_POST(self):
        if urlsplit(self.path).path == "/api/manager/decisions/respond":
            self._handle_manager_decision_response()
        else:
            self._json_response(403, {"error": "fixture_read_only"})


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="command-center-preview-") as state:
        SERVER.MANAGER_DECISIONS_FILE = Path(state) / "responses.jsonl"
        with http.server.ThreadingHTTPServer(("127.0.0.1", 0), PreviewHandler) as server:
            print(f"http://127.0.0.1:{server.server_port}/", flush=True)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass
