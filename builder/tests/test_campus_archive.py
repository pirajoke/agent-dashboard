"""Mark 2026-10-25: projects he is not working on leave the campus map for an archive."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest

from dashboard_builder.campus_archive import (
    IDLE_DAYS,
    apply_campus_archive,
    change_archive,
    load_archive,
)
from dashboard_builder.department_campus import build_department_campus_html
from campus_archive_write import without_archive_write

ROOT = Path(__file__).resolve().parents[1]
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


class CampusArchiveSurfaceTest(unittest.TestCase):
    def test_markup_and_script_offer_archive_and_restore(self):
        html = build_department_campus_html()
        self.assertIn("data-campus-archive-toggle", html)
        self.assertIn("data-campus-archive-list", html)
        self.assertIn("Убрать в архив", html)
        script = (ROOT / "dashboard-assets" / "script.js").read_text(encoding="utf-8")
        self.assertIn("'/api/manager/campus-archive'", script)
        self.assertIn("renderCampusArchive(payload?.archive)", script)
        self.assertIn("'В архив'", script)
        self.assertIn("'Вернуть'", script)
        self.assertNotIn("campus-archive-write", without_archive_write(script))

    def test_server_applies_archive_and_guards_writes(self):
        server = (ROOT / "dashboard-server-m4.py").read_text(encoding="utf-8")
        self.assertIn("apply_campus_archive(payload, CAMPUS_ARCHIVE_FILE", server)
        self.assertIn("parsed.path == '/api/manager/campus-archive'", server)
        handler = server.split("def _handle_campus_archive_change", 1)[1].split("def ", 1)[0]
        self.assertIn("self._platform_owner_body(", handler)


if __name__ == "__main__":
    unittest.main()
