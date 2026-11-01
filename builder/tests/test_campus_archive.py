"""Mark 2026-10-25: projects he is not working on leave the campus map for an archive."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import importlib.util
import io
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from dashboard_builder.campus_archive import (
    IDLE_DAYS,
    apply_campus_archive,
    change_archive,
    load_archive,
)
from campus_archive_write import without_archive_write

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("dashboard_campus_archive_test", ROOT / "dashboard-server-m4.py")
SERVER = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(SERVER)
NOW = datetime(2026, 10, 25, 22, 0, tzinfo=timezone.utc)
ROUTES = {"main-manager", "my-dictionary", "health-os", "jarvis"}


def agent(route_id: str, project: str, state_at: datetime | None, state: str | None = None) -> dict:
    return {
        "route_id": route_id, "project": project, "department_id": "development", "agent_role": "BUILDER",
        "state": state, "availability": "available" if state else "unavailable",
        "freshness": "fresh" if state else ("stale" if state_at else "unavailable"),
        "state_at": state_at.strftime("%Y-%m-%dT%H:%M:%SZ") if state_at else None,
        "outcome_stage": None,
    }


def payload() -> dict:
    return {
        "state": "empty",
        "events": [],
        "agents": [
            agent("main-manager", "MAIN MANAGER", None),
            agent("my-dictionary", "MY DICTIONARY", NOW - timedelta(minutes=2), "running"),
            agent("health-os", "HEALTH OS", NOW - timedelta(days=IDLE_DAYS + 3)),
            agent("jarvis", "JARVIS", None),
        ],
        "activity_counts": {},
    }


class CampusArchiveTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "campus-archive.json"

    def tearDown(self):
        self.tmp.cleanup()

    def routes_on_map(self, now=NOW, data=None):
        result = apply_campus_archive(data or payload(), self.path, now=now)
        return [row["route_id"] for row in result["agents"]], result

    def test_idle_and_never_seen_projects_go_to_the_archive(self):
        on_map, result = self.routes_on_map()
        self.assertEqual(on_map, ["main-manager", "my-dictionary"])
        self.assertEqual(
            result["archive"],
            [{"route_id": "health-os", "project": "HEALTH OS", "reason": "idle"},
             {"route_id": "jarvis", "project": "JARVIS", "reason": "idle"}],
        )
        self.assertEqual(result["activity_counts"]["enabled"], 2)
        self.assertEqual(result["activity_counts"]["running"], 1)

    def test_last_work_is_remembered_after_it_leaves_the_live_checkpoint(self):
        self.routes_on_map()
        later = payload()
        later["agents"][1] = agent("my-dictionary", "MY DICTIONARY", None)
        on_map, _ = self.routes_on_map(now=NOW + timedelta(days=IDLE_DAYS - 1), data=later)
        self.assertIn("my-dictionary", on_map)
        on_map, _ = self.routes_on_map(now=NOW + timedelta(days=IDLE_DAYS + 1), data=later)
        self.assertNotIn("my-dictionary", on_map)

    def test_manual_archive_restore_and_new_work_bring_it_back(self):
        self.routes_on_map()
        change_archive(self.path, {"route": "my-dictionary", "archived": True}, known_routes=ROUTES, now=NOW)
        on_map, result = self.routes_on_map(now=NOW + timedelta(minutes=1))
        self.assertNotIn("my-dictionary", on_map)
        self.assertIn({"route_id": "my-dictionary", "project": "MY DICTIONARY", "reason": "manual"}, result["archive"])

        change_archive(self.path, {"route": "health-os", "archived": False}, known_routes=ROUTES, now=NOW)
        on_map, _ = self.routes_on_map(now=NOW + timedelta(days=1))
        self.assertIn("health-os", on_map)

        fresh = payload()
        fresh["agents"][1] = agent("my-dictionary", "MY DICTIONARY", NOW + timedelta(hours=1), "running")
        on_map, _ = self.routes_on_map(now=NOW + timedelta(hours=1, minutes=1), data=fresh)
        self.assertIn("my-dictionary", on_map)

    def test_coordinator_stays_and_bad_changes_are_refused(self):
        for bad in (
            {"route": "main-manager", "archived": True},
            {"route": "unknown", "archived": True},
            {"route": "jarvis", "archived": "yes"},
            {"route": "jarvis"},
            ["jarvis"],
        ):
            with self.assertRaises(ValueError):
                change_archive(self.path, bad, known_routes=ROUTES, now=NOW)
        self.assertFalse(self.path.exists())

    def test_unreadable_store_and_payload_without_roster(self):
        self.path.write_text("{not json", encoding="utf-8")
        self.assertEqual(load_archive(self.path)["archived_at"], {})
        plain = {"state": "empty", "events": []}
        self.assertEqual(apply_campus_archive(dict(plain), self.path, now=NOW), plain)

    def test_store_is_private_and_only_written_on_change(self):
        self.routes_on_map()
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        written = self.path.stat().st_mtime_ns
        self.routes_on_map()
        self.assertEqual(self.path.stat().st_mtime_ns, written)
        self.assertIn("my-dictionary", json.loads(self.path.read_text())["last_seen"])


def _block(source: str, start: str, end: str) -> str:
    begin = source.index(start)
    return source[begin:source.index(end, begin)]


class CampusArchiveEndpointTest(unittest.TestCase):
    """The owner-only write and the departments read, run through the real handler."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "campus-archive.json"

    def call(self, method, path, body=None, *, token="fixture-owner", origin=None, host="localhost:9999"):
        handler = SERVER.Handler.__new__(SERVER.Handler)
        handler.path, handler.command = path, method
        data = json.dumps(body if body is not None else {}).encode()
        handler.headers = {"Host": host, "Content-Length": str(len(data)), "Content-Type": "application/json"}
        if token is not None:
            handler.headers["X-Dashboard-Run-Token"] = token
        if origin is not None:
            handler.headers["Origin"] = origin
        handler.rfile = io.BytesIO(data)
        output = {}
        handler._json_response = lambda status, payload: output.update(status=status, payload=payload)
        with (patch.object(SERVER, "CAMPUS_ARCHIVE_FILE", self.path),
              patch.object(SERVER, "_dashboard_run_token", return_value="fixture-owner"),
              patch.object(SERVER, "_bridge_request", return_value={"tasks": []}),
              patch.object(SERVER, "_department_campus_payload", side_effect=lambda *_a, **_k: payload()),
              patch.object(SERVER.Handler, "_cloudflare_access_owner", return_value=False),
              # Pin the archive clock to the fixture's NOW, or the fixture ages past IDLE_DAYS.
              patch.object(SERVER, "apply_campus_archive",
                           side_effect=lambda data, path, now: apply_campus_archive(data, path, now=NOW))):
            getattr(handler, f"do_{method}")()
        return output

    def test_owner_archives_and_restores_and_the_map_follows(self):
        before = self.call("GET", "/api/manager/departments")["payload"]
        self.assertIn("my-dictionary", [row["route_id"] for row in before["agents"]])
        saved = self.call("POST", "/api/manager/campus-archive", {"route": "my-dictionary", "archived": True},
                          origin="http://localhost:9999")
        self.assertEqual(saved["status"], 200)
        after = self.call("GET", "/api/manager/departments", token=None)["payload"]
        self.assertNotIn("my-dictionary", [row["route_id"] for row in after["agents"]])
        self.assertIn("my-dictionary", [row["route_id"] for row in after["archive"]])
        self.assertEqual(self.call("POST", "/api/manager/campus-archive",
                                   {"route": "my-dictionary", "archived": False})["status"], 200)
        back = self.call("GET", "/api/manager/departments")["payload"]
        self.assertIn("my-dictionary", [row["route_id"] for row in back["agents"]])

    def test_anonymous_cross_origin_and_bad_changes_are_refused(self):
        change = {"route": "jarvis", "archived": True}
        for host in ("localhost:9999", "command.meshly.fr"):
            self.assertEqual(self.call("POST", "/api/manager/campus-archive", change, token=None, host=host)["status"], 401)
            self.assertEqual(self.call("POST", "/api/manager/campus-archive", change, token="wrong", host=host)["status"], 401)
        self.assertEqual(self.call("POST", "/api/manager/campus-archive", change, origin="https://evil.example")["status"], 403)
        for bad in ({"route": "main-manager", "archived": True}, {"route": "../x", "archived": True}, {"route": "jarvis"}):
            self.assertEqual(self.call("POST", "/api/manager/campus-archive", bad)["status"], 400)
        self.assertFalse(self.path.exists())


class CampusArchiveBrowserTest(unittest.TestCase):
    """Runs the campus's archive code in node with a minimal DOM: list, «Вернуть», hidden folders."""

    def test_archive_list_restore_and_folder_hiding(self):
        if shutil.which("node") is None:
            self.skipTest("node is not installed")
        script = (ROOT / "dashboard-assets" / "script.js").read_text(encoding="utf-8")
        code = _block(script, "    function campusProjectKey(name) {", "    function openCampusDetails(button, event) {")
        harness = """
function el(tag) {
    return {tag, children: [], dataset: {}, hidden: false, disabled: false, textContent: '', attrs: {}, listeners: {},
        append(...items) { this.children.push(...items); },
        replaceChildren(...items) { this.children = items; },
        setAttribute(key, value) { this.attrs[key] = value; },
        addEventListener(type, fn) { this.listeners[type] = fn; },
        focus() {}, querySelector() { return null; }};
}
const document = {createElement: el};
const archiveToggleEl = el('button'); archiveToggleEl.hidden = true;
const archiveEl = el('section'); archiveEl.hidden = true;
const archiveListEl = el('ul');
const archiveErrorEl = el('p'); archiveErrorEl.hidden = true;
const health = el('button'); health.dataset.campusProject = 'HEALTH OS';
const news = el('button'); news.dataset.campusProject = 'CONTEXT NEWS';
const projectFolderEls = [health, news];
const posts = [];
let refreshed = 0;
let answer = 200;
function notifyCampusContentHeight() {}
function closeCampusDetails() {}
function campusOwnerHeaders() { return {'X-Dashboard-Run-Token': 't'}; }
function refreshDepartmentCampus() { refreshed += 1; }
async function fetch(url, options) { posts.push([url, options.method, JSON.parse(options.body)]); return {ok: answer === 200, status: answer}; }
CODE
(async () => {
    renderCampusArchive([{route_id: 'health-os', project: 'HEALTH OS', reason: 'idle'}]);
    const shown = {toggleHidden: archiveToggleEl.hidden, rows: archiveListEl.children.map((li) => li.children[0].textContent),
        health: health.dataset.campusProjectArchived, news: news.dataset.campusProjectArchived};
    const back = archiveListEl.children[0].children[1];
    await back.listeners.click();
    answer = 401;
    await back.listeners.click();
    const refused = {error: archiveErrorEl.textContent, errorHidden: archiveErrorEl.hidden, disabled: back.disabled};
    renderCampusArchive([]);
    process.stdout.write(JSON.stringify({shown, posts, refreshed, refused, emptyToggleHidden: archiveToggleEl.hidden}));
})();
""".replace("CODE", code)
        result = subprocess.run(["node", "-e", harness], capture_output=True, text=True, check=True, timeout=30)
        data = json.loads(result.stdout)
        self.assertEqual(data["shown"], {"toggleHidden": False, "rows": ["HEALTH OS"], "health": "true", "news": "false"})
        self.assertEqual(data["posts"][0], ["/api/manager/campus-archive", "POST", {"route": "health-os", "archived": False}])
        self.assertEqual(data["refreshed"], 1)
        self.assertFalse(data["refused"]["errorHidden"])
        self.assertIn("владелец", data["refused"]["error"])
        self.assertFalse(data["refused"]["disabled"])
        self.assertTrue(data["emptyToggleHidden"])

    def test_the_only_campus_write_is_the_archive(self):
        script = (ROOT / "dashboard-assets" / "script.js").read_text(encoding="utf-8")
        self.assertNotIn("campus-archive-write", without_archive_write(script))


if __name__ == "__main__":
    unittest.main()
