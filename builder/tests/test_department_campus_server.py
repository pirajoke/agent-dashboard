from __future__ import annotations

from datetime import datetime, timedelta, timezone
import importlib
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch


BUILDER_DIR = Path(__file__).resolve().parents[1]
SERVER_PATH = BUILDER_DIR / "dashboard-server-m4.py"
NOW = datetime(2026, 8, 8, 12, 0, tzinfo=timezone.utc)
TOP_LEVEL_FIELDS = (
    "state",
    "generated_at",
    "visible_task_count",
    "omitted_task_count",
    "events",
    "privacy",
)
PUBLIC_EVENT_FIELDS = (
    "event_id",
    "task_id",
    "department_id",
    "department_label",
    "project",
    "agent_id",
    "role",
    "status",
    "updated_at",
    "next_step",
    "evidence_count",
    "ephemeral",
    "zone_id",
)


class DepartmentCampusServerTests(unittest.TestCase):
    def setUp(self):
        try:
            server_spec = importlib.util.spec_from_file_location(
                "dashboard_server_department_campus", SERVER_PATH
            )
            if server_spec is None or server_spec.loader is None:
                self.fail("RED: dashboard server module cannot be loaded")
            self.server = importlib.util.module_from_spec(server_spec)
            server_spec.loader.exec_module(self.server)
        except Exception as exc:
            self.fail(f"RED: dashboard server import failed ({type(exc).__name__}: {exc})")

        if not hasattr(self.server, "_department_campus_payload"):
            self.fail("RED: dashboard-server-m4.py is missing _department_campus_payload")
        try:
            self.campus = importlib.import_module("dashboard_builder.department_campus")
        except Exception as exc:
            self.fail(
                "RED: server contract requires dashboard_builder.department_campus "
                f"({type(exc).__name__}: {exc})"
            )

    def _event(self, department_id="development", **overrides):
        zone = self.campus.DEPARTMENT_ZONES[department_id]
        payload = {
            "event_id": "evt-server-1",
            "task_id": "task-server-1",
            "department_id": department_id,
            "department_label": zone["label"],
            "project": "Public Project",
            "agent_id": "agent-server-1",
            "role": zone["roles"][0],
            "status": "active",
            "updated_at": "2026-08-08T11:59:00Z",
            "next_step": "Review safe evidence",
            "evidence_count": 1,
            "ephemeral": True,
            "zone_id": zone["zone_id"],
        }
        payload.update(overrides)
        return payload

    def _snapshot(self, events, *, updated_at="2026-08-08T11:59:30Z", **metadata_overrides):
        metadata = {
            "event": "status",
            "source_agent": "MAIN MANAGER",
            "pixel_events": events,
        }
        metadata.update(metadata_overrides)
        return {
            "id": "bridge-task-private",
            "updated_at": updated_at,
            "description": "<private-task-body>",
            "result": "<internal-result>",
            "metadata": metadata,
            "messages": [{"body": "<private-message>"}],
        }

    def test_ac_3_err_5_only_newest_same_metadata_verified_manager_snapshot_is_used(self):
        older = self._snapshot(
            [self._event(event_id="evt-old", project="Older Snapshot")],
            updated_at="2026-08-08T11:50:00Z",
        )
        newer = self._snapshot(
            [self._event(event_id="evt-new", project="Newest Snapshot")],
            updated_at="2026-08-08T11:59:30Z",
            source_agent="main-manager",
        )
        projected = self.server._department_campus_payload({"tasks": [older, newer]}, now=NOW)
        self.assertEqual(projected["state"], "active")
        self.assertEqual([item["project"] for item in projected["events"]], ["Newest Snapshot"])

        ordinary = self._snapshot([self._event()])
        ordinary["metadata"].pop("source_agent")
        simulation = self._snapshot([self._event()], event="simulation")
        split = self._snapshot([self._event()])
        split["metadata"].pop("event")
        split["messages"] = [{"metadata": {"event": "status"}}]
        for bridge_data in (
            {"tasks": [ordinary]},
            {"tasks": [simulation]},
            {"tasks": [split]},
            {"tasks": [{"metadata": {}}, {"metadata": {"source_agent": "MAIN MANAGER"}}]},
        ):
            with self.subTest(bridge_data=bridge_data):
                rejected = self.server._department_campus_payload(bridge_data, now=NOW)
                self.assertEqual(rejected["state"], "empty")
                self.assertEqual(rejected["events"], [])

    def test_ac_3_source_agent_provenance_requires_a_real_string(self):
        for source in ("MAIN MANAGER", "main-manager", "main_manager"):
            with self.subTest(kind="valid_string", source=source):
                snapshot = self._snapshot(
                    [self._event(project="Verified Manager")],
                    source_agent=source,
                )
                projected = self.server._department_campus_payload(
                    {"tasks": [snapshot]},
                    now=NOW,
                )
                self.assertEqual(projected["state"], "active")
                self.assertEqual(
                    [event["project"] for event in projected["events"]],
                    ["Verified Manager"],
                )

        for source in ({"main": "manager"}, ["main", "manager"]):
            with self.subTest(kind="forged_non_string", source=source):
                snapshot = self._snapshot(
                    [self._event(project="FORGED NON STRING SOURCE")],
                    source_agent=source,
                )
                projected = self.server._department_campus_payload(
                    {"tasks": [snapshot]},
                    now=NOW,
                )
                self.assertEqual(projected["state"], "empty")
                self.assertEqual(projected["events"], [])
                self.assertNotIn("FORGED", repr(projected))

    def test_ac_fresh_canonical_bridge_dispatch_projects_one_safe_active_owner(self):
        task = {
            "id": "bridge-task-23",
            "status": "running",
            "agent_role": "BUILDER",
            "project": "JARVIS",
            "created_at": "2026-08-08T11:55:00Z",
            "claimed_at": "2026-08-08T11:59:00Z",
            "completed_at": None,
            "description": "<private-description>",
            "result": "<private-result>",
            "error": "<private-error>",
            "messages": [{"body": "<private-message>"}],
            "metadata": {
                "event": "dispatch",
                "objective": "<private-objective>",
            },
        }

        projected = self.server._department_campus_payload({"tasks": [task]}, now=NOW)

        self.assertEqual(tuple(projected), TOP_LEVEL_FIELDS)
        self.assertEqual(projected["state"], "active")
        self.assertEqual(projected["visible_task_count"], 1)
        self.assertEqual(projected["omitted_task_count"], 0)
        self.assertEqual(projected["privacy"], "public_projection")
        self.assertEqual(len(projected["events"]), 1)
        event = projected["events"][0]
        self.assertEqual(tuple(event), PUBLIC_EVENT_FIELDS)
        self.assertEqual(event["task_id"], "bridge-task-23")
        self.assertEqual(event["department_id"], "infrastructure")
        self.assertEqual(event["department_label"], "Infrastructure")
        self.assertEqual(event["project"], "JARVIS")
        self.assertEqual(event["agent_id"], "INFRASTRUCTURE")
        self.assertEqual(event["role"], "Infrastructure Engineer")
        self.assertEqual(event["status"], "active")
        self.assertEqual(event["updated_at"], "2026-08-08T11:59:00Z")
        self.assertTrue(event["ephemeral"])
        self.assertEqual(event["zone_id"], "campus-zone-infrastructure")
        rendered = repr(projected)
        for private_value in (
            "<private-description>",
            "<private-result>",
            "<private-error>",
            "<private-message>",
            "<private-objective>",
        ):
            self.assertNotIn(private_value, rendered)

    def test_bridge_fallback_maps_lifecycle_timestamps_and_fails_closed(self):
        base = {
            "id": "bridge-lifecycle",
            "agent_role": "TESTER",
            "project": "jarvis",
            "created_at": "2026-08-08T11:57:00Z",
            "claimed_at": "2026-08-08T11:58:00Z",
            "completed_at": "2026-08-08T11:59:00Z",
        }
        cases = (
            ("pending", "queued", "2026-08-08T11:57:00Z"),
            ("claimed", "active", "2026-08-08T11:58:00Z"),
            ("done", "done", "2026-08-08T11:59:00Z"),
            ("failed", "failed", "2026-08-08T11:59:00Z"),
        )
        for status, expected_status, expected_time in cases:
            with self.subTest(status=status):
                task = {**base, "id": f"bridge-{status}", "status": status}
                projected = self.server._department_campus_payload(
                    {"tasks": [task]},
                    now=NOW,
                )
                self.assertEqual(projected["state"], "active")
                self.assertEqual(projected["events"][0]["status"], expected_status)
                self.assertEqual(projected["events"][0]["updated_at"], expected_time)

        rejected = (
            {**base, "status": "cancelled"},
            {**base, "status": "unknown"},
            {**base, "status": "running", "agent_role": "UNREGISTERED"},
            {**base, "status": "running", "project": "PRIVATE PROJECT"},
        )
        for task in rejected:
            with self.subTest(rejected=task):
                projected = self.server._department_campus_payload(
                    {"tasks": [task]},
                    now=NOW,
                )
                self.assertEqual(projected["state"], "empty")
                self.assertEqual(projected["events"], [])

    def test_err_1_non_object_bridge_or_non_list_pixel_events_is_unavailable_without_partial_data(self):
        malformed_sources = (None, [], "bad", 7, True)
        for bridge_data in malformed_sources:
            with self.subTest(bridge_data=bridge_data):
                projected = self.server._department_campus_payload(bridge_data, now=NOW)
                self.assertEqual(projected["state"], "unavailable")
                self.assertEqual(projected["events"], [])
                self.assertEqual(projected["visible_task_count"], 0)

        malformed_events = self._snapshot({"not": "a list"})
        projected = self.server._department_campus_payload({"tasks": [malformed_events]}, now=NOW)
        self.assertEqual(projected["state"], "unavailable")
        self.assertEqual(projected["events"], [])

    def test_ac_11_ec_7_stale_or_malformed_refresh_returns_no_previous_agents(self):
        stale = self._snapshot(
            [self._event(updated_at=(NOW - timedelta(minutes=31)).isoformat())],
            updated_at=(NOW - timedelta(minutes=31)).isoformat(),
        )
        projected = self.server._department_campus_payload({"tasks": [stale]}, now=NOW)
        self.assertEqual(projected["state"], "stale")
        self.assertEqual(projected["events"], [])
        self.assertEqual(projected["visible_task_count"], 0)

        malformed = self._snapshot([self._event(updated_at="not-a-time")])
        projected = self.server._department_campus_payload({"tasks": [malformed]}, now=NOW)
        self.assertNotEqual(projected["state"], "active")
        self.assertEqual(projected["events"], [])

    def test_ac_3_ac_8_err_2_err_4_public_get_is_exact_safe_projection_and_failure_is_generic(self):
        response = {}
        requested = []
        handler = self.server.Handler.__new__(self.server.Handler)
        handler.path = "/api/manager/departments"
        handler.headers = {"Host": "command.meshly.fr"}
        handler._json_response = lambda status, payload: response.update(status=status, payload=payload)

        def bridge_request(method, path, payload=None):
            requested.append((method, path, payload))
            return {"tasks": [self._snapshot([self._event(prompt="<private-prompt>")])]}

        original_payload = self.server._department_campus_payload

        def payload_at_fixed_now(bridge_data, *, now=None):
            return original_payload(bridge_data, now=NOW)

        with (
            patch.object(self.server, "_bridge_request", side_effect=bridge_request),
            patch.object(
                self.server,
                "_department_campus_payload",
                side_effect=payload_at_fixed_now,
            ),
        ):
            handler.do_GET()

        self.assertEqual(response["status"], 200)
        self.assertEqual(requested, [("GET", "/api/tasks?limit=24&include_messages=1", None)])
        self.assertEqual(tuple(response["payload"]), TOP_LEVEL_FIELDS)
        self.assertEqual(response["payload"]["privacy"], "public_projection")
        self.assertEqual(tuple(response["payload"]["events"][0]), PUBLIC_EVENT_FIELDS)
        self.assertNotIn("<private-prompt>", repr(response["payload"]))
        self.assertNotIn("<private-task-body>", repr(response["payload"]))

        failed_response = {}
        handler._json_response = lambda status, payload: failed_response.update(
            status=status, payload=payload
        )
        with patch.object(
            self.server,
            "_bridge_request",
            side_effect=RuntimeError("token=/private/path internal traceback"),
        ):
            handler.do_GET()
        self.assertEqual(failed_response["status"], 200)
        self.assertEqual(failed_response["payload"]["state"], "unavailable")
        self.assertEqual(failed_response["payload"]["events"], [])
        rendered = repr(failed_response["payload"])
        for forbidden in ("token=", "/private/path", "traceback", "RuntimeError"):
            self.assertNotIn(forbidden, rendered)


if __name__ == "__main__":
    unittest.main()
