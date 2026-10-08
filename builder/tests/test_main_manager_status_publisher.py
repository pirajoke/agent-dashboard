from __future__ import annotations

from datetime import datetime, timedelta, timezone
import importlib.util
import io
import json
import os
from pathlib import Path
import plistlib
import tempfile
import unittest
from unittest.mock import patch


BUILDER_DIR = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 9, 0, 10, tzinfo=timezone.utc)


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


PUBLISHER = _load("main_manager_status_publisher", BUILDER_DIR / "main_manager_status_publisher.py")
SERVER = _load("dashboard_server_status_publisher", BUILDER_DIR / "dashboard-server-m4.py")
from dashboard_builder.department_campus import department_campus_projection  # noqa: E402


def _pixel(project, state="waiting"):
    return {
        "project": project,
        "agentId": "route",
        "agentRole": "BUILDER",
        "departmentId": "development",
        "zoneId": "zone-development",
        "state": state,
        "updatedAt": "2026-08-18T11:47:31+00:00",
    }


def _status(*rows, ok=True):
    return {
        "ok": ok,
        "outcome": "status",
        "counts": {"queued": 2, "owner_gate": 1, "active": 0, "claimed": 0, "agent_stalled": 0},
        "items": [],
        "pixel_events": [_pixel(project) for project, _ in rows],
        "human_projection": [
            {"project": project, "agent": "route", "status": status, "needs_mark": status == "NEEDS MARK"}
            for project, status in rows
        ],
    }


class BuildEventsTests(unittest.TestCase):
    observed = "2026-10-09T00:10:00Z"

    def test_open_items_map_to_campus_contract(self):
        events = PUBLISHER.build_events(
            _status(("JARVIS", "NEEDS MARK"), ("MY DICTIONARY", "WAITING"), ("HEALTH OS", "WORKING")),
            observed_at=self.observed,
        )
        by_project = {event["project"]: event for event in events}
        self.assertEqual(by_project["JARVIS"]["status"], "waiting")
        self.assertEqual(by_project["JARVIS"]["department_id"], "infrastructure")
        self.assertEqual(by_project["JARVIS"]["agent_id"], "INFRASTRUCTURE")
        self.assertEqual(by_project["MY DICTIONARY"]["status"], "queued")
        self.assertEqual(by_project["HEALTH OS"]["status"], "active")
        for event in events:
            self.assertEqual(event["updated_at"], self.observed)
            self.assertIs(event["ephemeral"], True)

    def test_done_items_are_history_not_live_work(self):
        events = PUBLISHER.build_events(_status(("JARVIS", "DONE")), observed_at=self.observed)
        self.assertEqual(events, [])

    def test_most_urgent_item_wins_per_project(self):
        events = PUBLISHER.build_events(
            _status(("JARVIS", "DONE"), ("JARVIS", "WAITING"), ("JARVIS", "NEEDS MARK")),
            observed_at=self.observed,
        )
        self.assertEqual([(e["project"], e["status"]) for e in events], [("JARVIS", "waiting")])

    def test_project_names_are_normalised_and_unknown_projects_skipped(self):
        events = PUBLISHER.build_events(
            _status(("ACCOUNTABLE_OS", "WAITING"), ("MYDICTIONNARY", "WAITING"), ("SECRET LAB", "WAITING")),
            observed_at=self.observed,
        )
        self.assertEqual(sorted(e["project"] for e in events), ["ACCOUNTABLE OS", "MY DICTIONARY"])

    def test_mismatched_scheduler_output_fails_closed(self):
        broken = _status(("JARVIS", "NEEDS MARK"))
        broken["human_projection"] = []
        with self.assertRaises(PUBLISHER.PublisherError):
            PUBLISHER.build_events(broken, observed_at=self.observed)

    def test_published_events_pass_campus_validation(self):
        events = PUBLISHER.build_events(
            _status(("JARVIS", "NEEDS MARK"), ("HEALTH OS", "WORKING")),
            observed_at=self.observed,
        )
        projection = department_campus_projection(events, now=NOW + timedelta(minutes=1))
        self.assertEqual(projection["state"], "active")
        self.assertEqual({e["project"] for e in projection["events"]}, {"JARVIS", "HEALTH OS"})


class SnapshotTests(unittest.TestCase):
    def test_snapshot_carries_queue_change_time_from_queue_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            queue = Path(tmp) / "continuation-queue.json"
            queue.write_text("{}")
            changed = datetime(2026, 10, 8, 23, 50, tzinfo=timezone.utc).timestamp()
            os.utime(queue, (changed, changed))
            snapshot = PUBLISHER.build_snapshot(_status(("JARVIS", "NEEDS MARK")), now=NOW, queue_path=queue)
        self.assertEqual(snapshot["queue_updated_at"], "2026-10-08T23:50:00Z")
        self.assertEqual(snapshot["observed_at"], "2026-10-09T00:10:00Z")
        self.assertEqual(snapshot["source_agent"], "main-manager")
        self.assertEqual(snapshot["event"], "status")
        self.assertEqual(snapshot["counts"]["owner_gate"], 1)

    def test_missing_queue_file_gives_null_change_time(self):
        snapshot = PUBLISHER.build_snapshot(_status(), now=NOW, queue_path=Path("/nonexistent/queue.json"))
        self.assertIsNone(snapshot["queue_updated_at"])
        self.assertEqual(snapshot["pixel_events"], [])

    def test_failed_scheduler_status_is_not_published(self):
        with self.assertRaises(PUBLISHER.PublisherError):
            PUBLISHER.build_snapshot(_status(ok=False), now=NOW, queue_path=Path("/nonexistent"))


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class PostTests(unittest.TestCase):
    def test_posts_to_non_executable_status_event_endpoint(self):
        captured = {}

        def fake_urlopen(request, timeout):
            captured["url"] = request.full_url
            captured["auth"] = request.get_header("Authorization")
            captured["body"] = json.loads(request.data)
            return _Response(json.dumps({"id": "abc123", "status": "done"}).encode())

        snapshot = {"source_agent": "main-manager", "event": "status", "pixel_events": []}
        with patch.object(PUBLISHER.urllib.request, "urlopen", fake_urlopen):
            result = PUBLISHER.post_snapshot(snapshot, bridge_url="http://127.0.0.1:8899/", token="t0k")
        self.assertEqual(result["id"], "abc123")
        self.assertEqual(captured["url"], "http://127.0.0.1:8899/api/status-event")
        self.assertEqual(captured["auth"], "Bearer t0k")
        self.assertEqual(captured["body"], snapshot)

    def test_rejects_response_that_is_not_a_finished_record(self):
        def fake_urlopen(request, timeout):
            return _Response(json.dumps({"id": "abc123", "status": "pending"}).encode())

        with patch.object(PUBLISHER.urllib.request, "urlopen", fake_urlopen):
            with self.assertRaises(PUBLISHER.PublisherError):
                PUBLISHER.post_snapshot({}, bridge_url="http://127.0.0.1:8899", token="t")


class CampusServerIntegrationTests(unittest.TestCase):
    def _bridge(self, snapshot, *, completed_at):
        return {
            "tasks": [
                {
                    "id": "status-row",
                    "status": "done",
                    "created_at": completed_at,
                    "completed_at": completed_at,
                    "metadata": {
                        **{k: v for k, v in snapshot.items() if k not in {"source_agent", "project"}},
                        "source_agent": "main-manager",
                        "entrypoint": "bridge.status_event",
                        "executable": False,
                    },
                }
            ]
        }

    def _snapshot(self, *rows):
        with tempfile.TemporaryDirectory() as tmp:
            queue = Path(tmp) / "q.json"
            queue.write_text("{}")
            changed = datetime(2026, 10, 8, 23, 50, tzinfo=timezone.utc).timestamp()
            os.utime(queue, (changed, changed))
            return PUBLISHER.build_snapshot(_status(*rows), now=NOW, queue_path=queue)

    def test_fresh_snapshot_makes_campus_live_with_queue_time(self):
        data = self._bridge(self._snapshot(("JARVIS", "NEEDS MARK")), completed_at="2026-10-09T00:10:01Z")
        payload = SERVER._department_campus_payload(data, now=NOW + timedelta(minutes=2))
        self.assertEqual(payload["state"], "active")
        self.assertEqual(payload["events"][0]["project"], "JARVIS")
        self.assertEqual(payload["events"][0]["status"], "waiting")
        self.assertEqual(payload["queue_updated_at"], "2026-10-08T23:50:00Z")

    def test_snapshot_without_open_work_is_empty_not_stale(self):
        data = self._bridge(self._snapshot(("JARVIS", "DONE")), completed_at="2026-10-09T00:10:01Z")
        payload = SERVER._department_campus_payload(data, now=NOW + timedelta(minutes=2))
        self.assertEqual(payload["state"], "empty")
        self.assertEqual(payload["queue_updated_at"], "2026-10-08T23:50:00Z")

    def test_publisher_outage_still_reports_stale(self):
        data = self._bridge(self._snapshot(("JARVIS", "NEEDS MARK")), completed_at="2026-10-09T00:10:01Z")
        payload = SERVER._department_campus_payload(data, now=NOW + timedelta(minutes=31))
        self.assertEqual(payload["state"], "stale")
        self.assertEqual(payload["events"], [])
        self.assertEqual(payload["queue_updated_at"], "2026-10-08T23:50:00Z")

    def test_future_queue_time_is_dropped(self):
        snapshot = self._snapshot(("JARVIS", "NEEDS MARK"))
        snapshot["queue_updated_at"] = "2030-01-01T00:00:00Z"
        data = self._bridge(snapshot, completed_at="2026-10-09T00:10:01Z")
        payload = SERVER._department_campus_payload(data, now=NOW + timedelta(minutes=2))
        self.assertNotIn("queue_updated_at", payload)


class LaunchdAndDeployTests(unittest.TestCase):
    def test_launchd_template_runs_publisher_every_five_minutes(self):
        template = (BUILDER_DIR / "launchd/com.pirajoke.main-manager-status-publisher.plist.template").read_text()
        rendered = template.replace("__SCRIPTS_DIR__", "/Users/x/scripts").replace("__HOME__", "/Users/x")
        plist = plistlib.loads(rendered.encode())
        self.assertEqual(plist["Label"], "com.pirajoke.main-manager-status-publisher")
        self.assertEqual(plist["StartInterval"], 300)
        self.assertEqual(plist["ProgramArguments"][-1], "/Users/x/scripts/main_manager_status_publisher.py")

    def test_deploy_installs_publisher_and_launch_agent(self):
        deploy = (BUILDER_DIR / "deploy_to_scripts.sh").read_text()
        self.assertIn("main_manager_status_publisher.py", deploy)
        self.assertIn("com.pirajoke.main-manager-status-publisher", deploy)
        self.assertIn('launchctl bootstrap "gui/$(id -u)" "$PUBLISHER_PLIST"', deploy)


if __name__ == "__main__":
    unittest.main()
