"""Isolated browser fixtures. Binds loopback, never contacts live services.

Run: PYTHONPATH=builder python3 builder/tests/preview_command_center.py
The printed local URL accepts ?fixture=ready|google-owner|empty|stale|unavailable|anonymous|changed|long-label|unknown|failure.
Navigation uses the real strict owner endpoint and synthetic registry only.
Default navigation has a fresh Mini and stale Pro. No private source is read.
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
from docxx_fixture import fixture as docxx_fixture

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_TOKEN = "isolated-preview-owner"
STARTED = datetime.now(timezone.utc)
MODE = "waiting"


FIXTURE_STATE = None

# Synthetic service list shaped like the Mac mini health API (names only, no owner data).
FIXTURE_SERVICES = [
    {"name": "Lexi Admin", "label": "fixture.lexi-admin", "desc": "Lexi / MyDictionary admin", "status": "running", "runtime": "Docker", "port": 8791, "port_ok": True, "cat": "core"},
    {"name": "Lexi PostgreSQL", "label": "fixture.lexi-db", "desc": "Lexi / MyDictionary database", "status": "running", "runtime": "Docker", "port": 55434, "port_ok": True, "cat": "core"},
    {"name": "Context News Web", "label": "fixture.cn-web", "desc": "Context News web app + admin", "status": "running", "runtime": "Python", "port": 8790, "port_ok": True, "cat": "core"},
    {"name": "Context News Worker", "label": "fixture.cn-worker", "desc": "@contextnews_bot digest delivery", "status": "running", "runtime": "Python", "cat": "core"},
    {"name": "Context News PostgreSQL", "label": "fixture.cn-db", "desc": "Context News database", "status": "running", "runtime": "Postgres", "port": 55432, "port_ok": True, "cat": "core"},
    {"name": "Accountable OS", "label": "fixture.accountable", "desc": "Accountability workspace", "status": "running", "runtime": "Python", "port": 4174, "port_ok": True, "cat": "core"},
    {"name": "Pixel Agents", "label": "fixture.pixel", "desc": "Pixel agents runtime", "status": "running", "runtime": "Node", "port": 3100, "port_ok": True, "cat": "core"},
    {"name": "Closeness Mirror", "label": "fixture.closeness", "desc": "Closeness Mirror app", "status": "running", "runtime": "Node", "cat": "core"},
    {"name": "Krisp Import", "label": "fixture.krisp", "desc": "Legacy Krisp import job · не загружена в launchd", "status": "stopped", "runtime": "Node", "interval": 3600, "cat": "core"},
    {"name": "TGBot Watchdog", "label": "fixture.tgbot-watchdog", "desc": "Restarts Telegram bot if unhealthy · последний запуск с ошибкой (код 1)", "status": "stopped", "runtime": "Python", "interval": 300, "exit_code": 1, "cat": "core"},
    {"name": "Database Backup", "label": "fixture.db-backup", "desc": "Nightly PostgreSQL backup · не загружена в launchd", "status": "stopped", "runtime": "Bash", "interval": 86400, "cat": "core"},
    {"name": "Alert Monitor", "label": "fixture.alert-monitor", "desc": "Periodic alert monitor · не загружена в launchd", "status": "stopped", "runtime": "Python", "interval": 300, "cat": "core"},
    {"name": "M4 Healthcheck", "label": "fixture.m4-health", "desc": "Mac Mini health alert checks · не загружена в launchd", "status": "stopped", "runtime": "Python", "interval": 300, "cat": "core"},
]


def prepare_navigation_fixture():
    if FIXTURE_STATE is None:
        raise RuntimeError("preview fixture needs its isolated temporary state")
    path = SERVER.JARVIS_VAULT_ROOT / "35-Systems" / "PORTFOLIO-REGISTRY.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"schema_version": 2, "navigation": {"command_center": {
        "verified_at": STARTED.isoformat(), "platforms": {
            "financial": {"resources": [
                {"kind": "code", "label": "Synthetic project code", "url": "https://github.com/example/navigation-fixture", "scope": "current"},
                {"kind": "documents", "label": "Synthetic archive", "url": "https://drive.google.com/drive/folders/fixture-archive", "scope": "archive"}],
                "note": "Only synthetic links; no owner documents."},
            "pixel-agents": {"resources": [{"kind": "code", "label": "Synthetic upstream source", "url": "https://github.com/example/upstream-fixture", "scope": "upstream"}]}}}}}
    # Uneven resource counts reproduce the dense private card without owner data.
    payload["navigation"]["command_center"]["platforms"]["jarvis"] = {
        "resources": [
            {"kind": kind, "label": label, "url": f"https://github.com/example/fixture-{i}", "scope": scope}
            for i, (kind, label, scope) in enumerate([
                ("code", "Synthetic project repository", "current"),
                ("notes", "Synthetic project notes", "current"),
                ("tasks", "Synthetic project tasks", "current"),
                ("documents", "Synthetic historical configuration", "archive"),
                ("notes", "Synthetic system map and responsibilities", "current"),
                ("documents", "Synthetic system map PDF", "reference"),
                ("notes", "Synthetic Inbox processing verification", "current"),
                ("documents", "Synthetic document with a deliberately long descriptive title for narrow screens", "reference"),
            ])],
        "note": "Synthetic status: Inbox processing runs on the always-on computer. "
                "The laptop can be off. Keep the processor logged in and online. "
                "This preview contains no owner documents or private project links."
    }
    # One synthetic owner project card for «Личное» in MAIN MANAGER.
    payload["navigation"]["command_center"]["projects"] = [{
        "id": "fixture-personal", "name": "SYNTHETIC PERSONAL PROJECT", "status": "Preparing documents; nothing filed.",
        "checked": STARTED.date().isoformat(),
        "facts": [{"label": "Route", "text": "Synthetic route with a deliberately long description so the row wraps on narrow phone screens."},
                  {"label": "Confirmed", "text": "Synthetic confirmed facts."},
                  {"label": "Filing date", "text": "Not set."}],
        "tasks": ["Synthetic open task one", "Synthetic open task two"],
        "links": [{"label": "Inventory", "url": "https://docs.google.com/document/d/fixture-doc/edit"},
                  {"label": "Checklist", "url": "https://docs.google.com/spreadsheets/d/fixture-sheet/edit"}]}]
    if MODE == "empty":
        payload = {"schema_version": 2}
    elif MODE == "long-label":
        payload["navigation"]["command_center"]["platforms"]["financial"]["resources"][0]["label"] = '<img src=x onerror=alert(1)> Long synthetic label ' + 'W' * 70
        payload["navigation"]["command_center"]["platforms"]["financial"]["note"] = '<script>alert(2)</script> This must be displayed as text.'
    path.write_text("malformed fixture" if MODE == "unavailable" else json.dumps(payload))
    for name, age in (("mac-mini", 600), ("macbook-pro", 28800)):
        day = STARTED.date().isoformat()
        daily = SERVER.DAILY_WORK_DIR / "sessions" / name / f"{day}.json"
        daily.parent.mkdir(parents=True, exist_ok=True)
        data = {"schema": 2, "machine": name, "date": day,
                "collected_at": (STARTED - timedelta(seconds=age)).isoformat(),
                "sources": {"claude": {"ok": True}, "codex": {"ok": MODE != "failure"}}, "sessions": []}
        if MODE == "unknown" and name == "macbook-pro":
            data["collected_at"] = "invalid fixture timestamp"
        daily.write_text(json.dumps(data))
    (SERVER.DAILY_WORK_DIR / "github.json").write_text(json.dumps({
        "ok": MODE != "failure", "collected_at": (STARTED - timedelta(minutes=15)).isoformat(),
        "prs": [], "commits": [], "open_issues": []}))


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
    def _cloudflare_access_owner(self):
        # Only this isolated loopback fixture simulates a Google-authenticated owner.
        # No actual JWT, Google header, account, or authentication network call.
        return MODE == "google-owner"

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
        if parsed.path == "/fixture-deploy":
            # Simulates the Mac mini deploying a newer version while a tab stays open.
            SERVER.AUTO_DEPLOY_STATE_FILE.write_text(json.dumps({"deployed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}))
            self._json_response(200, {"deployed": True})
            return
        if parsed.path == "/api/site-version":
            super().do_GET()
            return
        if parsed.path.startswith('/fixture/'):
            mode = parsed.path.removeprefix('/fixture/')
            if mode in {'sorting', 'waiting', 'ready', 'google-owner', 'changed', 'empty', 'stale', 'unavailable', 'anonymous', 'long-label', 'unknown', 'failure'}:
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
            html = html.replace("const IS_PUBLIC_DASHBOARD = window.location.hostname === 'command.meshly.fr';", "const IS_PUBLIC_DASHBOARD = true;")
            token = "localStorage.removeItem('command-center.jarvis-run-token');" if MODE in {"anonymous", "google-owner"} else f"localStorage.setItem('command-center.jarvis-run-token', {json.dumps(FIXTURE_TOKEN)});"
            html = html.replace("<script>", "<script>" + token, 1)
            self.document(html)
            return
        if parsed.path == "/api/platform-resources":
            prepare_navigation_fixture()
            super().do_GET()  # Exercise the product's strict auth and resource projection.
            return
        if parsed.path == "/api/shared-tasks":
            if not self._decision_owner_authorized():
                self._json_response(401, {"state": "owner_required", "tasks": []})
                return
            self._json_response(200, {"state": "ready", "source": "notion", "board_url": "https://www.notion.so/preview",
                                      "tasks": [{"id": "preview", "title": "Пример новой задачи из PLAUD",
                                                 "status": "doing", "project": "JARVIS", "due_date": "",
                                                 "url": "https://www.notion.so/preview", "revision": STARTED.isoformat()}]})
            return
        if parsed.path in {"/api/docxx", "/api/docxx/folders"} and MODE == "sorting":
            prepare_docxx_sorting()
            super().do_GET()  # The real projection and sorting over a synthetic library.
            return
        if parsed.path == "/api/docxx":
            self._json_response(200, docxx_fixture(MODE))
            return
        if parsed.path == "/api/context-library":
            # Synthetic content only. Never read the operator's vault for previews.
            if not self._decision_owner_authorized():
                self._json_response(200, {"state": "owner_required", "records": []})
                return
            record = {
                "id": "a" * 32, "source": "plaud", "kind": "transcript",
                "title": "Пример: план запуска проекта", "date": STARTED.date().isoformat(),
                "modified_at": STARTED.isoformat(), "project": "Демонстрация интерфейса",
                "obsidian_url": "obsidian://open?vault=Synthetic&file=preview",
            }
            payload = {"state": "ready", "generated_at": STARTED.isoformat(),
                       "sources": [{"source": "plaud", "state": "observed"}], "total": 1}
            if query.get("id"):
                record["body"] = """# Пример: план запуска проекта
## Резюме
### Что решили
- **Начать с пилота:** проверить один сценарий перед большим запуском.
- Оставить оригинальную запись в Obsidian.

### Следующие шаги
- [ ] Подготовить план и обсудить результат.
- [ ] Открыть [задачу-пример](https://github.com/example/context-fixture/issues/23).

> **Рекомендация:** сначала проверить результат с *участниками пилота*.

Это демонстрационные данные; ссылки показывают формат, а не реальную работу.

## Транскрипт
**[00:03] Участник:** Давайте начнём с одного сценария.
**[00:41] Участник:** Затем обсудим результат и выберем следующий шаг.
"""
                payload["record"] = record
            else:
                payload["records"] = [record]
            self._json_response(200, payload)
            return
        if parsed.path == "/api/job-mail":
            # Synthetic replies only (PREVIEW_JOB_MAIL=not_connected shows the connect step).
            if not self._decision_owner_authorized():
                self._json_response(401, {"error": "owner_token_required", "state": "owner_required"})
                return
            self._json_response(200, job_mail_fixture())
            return
        if parsed.path in {"/api/platform-edits", "/api/platform-cards", "/api/owner-todo", "/api/growth"}:
            super().do_GET()  # The product's owner-only read of card edits and owner-made cards.
            return
        if parsed.path == "/api/owner-projects":
            prepare_navigation_fixture()
            super().do_GET()  # The product's strict owner check and card projection.
            return
        if parsed.path == "/api/work/daily":
            prepare_navigation_fixture()
            self._json_response(200, SERVER.work_projection(SERVER.DAILY_WORK_DIR,
                now=datetime.now(timezone.utc), owner=self._decision_owner_authorized()))
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
            payload = {
                "system": {"hostname": "Preview computer", "cpu_percent": 23, "memory_used_gb": 7, "memory_total_gb": 16, "disk_used_gb": 80, "disk_total_gb": 256, "uptime": "2 days"},
                "services": [dict(service, status="stopped") if MODE == "failure" else dict(service) for service in FIXTURE_SERVICES],
            }
            if parsed.path == "/api/all" and self._decision_owner_authorized():
                # A running job the health registry does not list is added by the product rule.
                payload = SERVER.normalize_payload(payload, loaded={"com.example.fixture-extra": 0}, disabled=set(),
                                                   running={"com.example.fixture-extra"}, plist_exists=lambda path: True)
            self._json_response(200, payload)
            return
        if parsed.path.startswith("/api/"):
            self._json_response(200, {"status": "ok", "tasks": [], "services": [], "history": [], "counts": {}})
            return
        self.send_error(404)

    def do_POST(self):
        if urlsplit(self.path).path == "/api/manager/decisions/respond":
            self._handle_manager_decision_response()
        elif urlsplit(self.path).path == "/api/platform-edits":
            self._handle_platform_edits_save()  # Writes only to the isolated fixture state.
        elif urlsplit(self.path).path == "/api/platform-cards":
            self._handle_platform_cards_save()
        elif urlsplit(self.path).path == "/api/growth":
            self._handle_growth_edit()  # Writes only the synthetic note in the fixture state.
        elif urlsplit(self.path).path == "/api/docxx/decide":
            self._handle_docxx_decide()  # Moves only synthetic files in the fixture library.
        elif urlsplit(self.path).path == "/api/owner-todo":
            self._handle_owner_todo_save()  # Writes only to the isolated fixture state.
        else:
            self._json_response(403, {"error": "fixture_read_only"})


def prepare_docxx_sorting():
    """Synthetic «Нужен разбор» documents in a throwaway DOCXXx library (?fixture=sorting)."""
    state = SERVER.HOME / "Library/Application Support/DOCXX-intake"
    if (state / "status.json").exists():
        status = json.loads((state / "status.json").read_text())
        status["checked_at"] = datetime.now(timezone.utc).isoformat()
        (state / "status.json").write_text(json.dumps(status))
        return
    library = SERVER.HOME / "Drive/DOCXXx"
    review = library / "10 — 📥 To review/Documents to review"
    for folder in ("10 — 📥 To review/Documents to review", "20 — France/Médiathèque", "20 — France/Impôts",
                   "20 — France/Logement", "30 — Santé", "40 — Travail/Bulletins de paie", "90 — Archive"):
        (library / folder).mkdir(parents=True, exist_ok=True)
    state.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    attachments = {}
    for index, name in enumerate(("ticketa4_a4_24102026-115416.pdf", "scan_0042.pdf", "IMG_2291.jpeg")):
        (review / name).write_bytes(b"synthetic")
        attachments[name] = {"state": "delivered", "needs_review": True, "name": name, "destination": str(review / name),
                             "delivered_at": (now - timedelta(hours=index + 1)).isoformat()}
    (state / "gmail-journal.json").write_text(json.dumps({"schema_version": 1, "attachments": attachments}))
    for name in ("journal.json", "drive-ingress-journal.json", "config.json"):
        (state / name).write_text("{}")
    (state / "runner.lock").touch()
    (state / "status.json").write_text(json.dumps({
        "checked_at": now.isoformat(), "phase": "needs_review", "model_calls": 0,
        "catalog": {"status": "ready", "documents": 42}, "results": [],
        "drive_ingress": {"status": "idle", "pending": 0, "results": []}, "review_pending": []}))


def job_mail_fixture():
    import os
    from dashboard_builder import job_mail
    if os.environ.get("PREVIEW_JOB_MAIL") == "not_connected":
        return {"state": "not_connected", "email": None, "waiting": [], "recent": [], "stats": job_mail.stats([])}
    now = datetime.now(timezone.utc)
    rows = [("Пример А", "Business Developer", "positive", 3, False), ("Пример Б", "GTM Engineer", "negative", 1, True),
            ("Пример В", "Product Manager", "negative", 9, True), ("Пример Г", "Consultant", "positive", 16, True),
            ("Пример Д", "Sales", "ack", 3, False), ("Пример Е", "Account Executive", "negative", 23, True),
            ("Пример Ж", "Growth", "negative", 12, True), ("Пример З", "Ops", "negative", 30, True),
            ("Пример И", "Sales", "positive", 6, True), ("Пример К", "CSM", "negative", 5, True),
            ("Пример Л", "BizDev", "negative", 38, True), ("Пример М", "PM", "negative", 19, True)]
    replies = [{"id": f"m{index}", "thread_id": f"t{index}", "company": company, "role": role, "verdict": verdict,
                "date": (now - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ"), "answered": answered,
                "link": f"https://mail.google.com/mail/#all/t{index}", "subject": "Пример"}
               for index, (company, role, verdict, days, answered) in enumerate(rows)]
    return {"state": "connected", "email": "preview@example.com", "first_scan_done": True, "stale": False,
            "waiting": [reply for reply in replies if reply["verdict"] == "positive" and not reply["answered"]],
            "recent": replies, "stats": job_mail.stats(replies, today=now)}


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="command-center-preview-") as state:
        FIXTURE_STATE = Path(state)
        SERVER.MANAGER_DECISIONS_FILE = FIXTURE_STATE / "responses.jsonl"
        SERVER.PLATFORM_EDITS_FILE = FIXTURE_STATE / "platform-edits.json"
        SERVER.PLATFORM_CARDS_FILE = FIXTURE_STATE / "platform-cards.json"
        SERVER.OWNER_TODO_FILE = FIXTURE_STATE / "owner-todo.json"
        SERVER.HOME = FIXTURE_STATE / "home"  # Synthetic DOCXX state and library for ?fixture=sorting.
        SERVER.JARVIS_VAULT_ROOT = FIXTURE_STATE / "fixture-vault"
        SERVER.DAILY_WORK_DIR = FIXTURE_STATE / "daily-work"
        SERVER.GROWTH_NOTE_FILE = FIXTURE_STATE / "growth-note.md"
        SERVER.GROWTH_EDITS_JOURNAL = FIXTURE_STATE / "growth-edits.jsonl"
        SERVER.GROWTH_NOTE_FILE.write_text("# Точки роста\n\n## Synthetic research area\n- Зачем: Synthetic reason.\n- [x] Synthetic first step\n- [ ] Synthetic second step\n\n## Synthetic design area\n", encoding="utf-8")
        SERVER.AUTO_DEPLOY_STATE_FILE = FIXTURE_STATE / "auto-deploy-state.json"
        SERVER.AUTO_DEPLOY_STATE_FILE.write_text(json.dumps({"deployed_at": (STARTED - timedelta(minutes=7)).strftime("%Y-%m-%dT%H:%M:%SZ")}))
        prepare_navigation_fixture()
        with http.server.ThreadingHTTPServer(("127.0.0.1", 0), PreviewHandler) as server:
            print(f"http://127.0.0.1:{server.server_port}/", flush=True)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass
