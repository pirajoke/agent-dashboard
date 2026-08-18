from __future__ import annotations

from datetime import datetime, timedelta, timezone
import importlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


BUILDER_DIR = Path(__file__).resolve().parents[1]
PIXEL_EVENT_PATH = BUILDER_DIR / "jarvis-pixel-agent-event"
PIPELINE_PATH = BUILDER_DIR / "jarvis-agent-pipeline"
SERVER_PATH = BUILDER_DIR / "dashboard-server-m4.py"
NOW = datetime(2026, 8, 18, 6, 0, tzinfo=timezone.utc)


class DepartmentCampusLiveTruthTests(unittest.TestCase):
    """RED contract for `.tdd/spec-real-agent-heartbeat-truth-v1.md`."""

    @classmethod
    def setUpClass(cls):
        cls.campus = importlib.import_module("dashboard_builder.department_campus")

    def _event(self, *, status: str = "active", **overrides) -> dict:
        zone = self.campus.DEPARTMENT_ZONES["design"]
        event = {
            "event_id": "run-pixelverse-36",
            "task_id": "run-pixelverse-36",
            "department_id": "design",
            "department_label": zone["label"],
            "project": "PIXELVERSE DASHBOARD",
            "agent_id": "DESIGNER",
            "role": "Designer",
            "status": status,
            "updated_at": "2026-08-18T05:59:50Z",
            "next_step": "Проверить безопасный результат",
            "evidence_count": 1,
            "ephemeral": True,
            "zone_id": zone["zone_id"],
        }
        event.update(overrides)
        return event

    def _heartbeat(self, **overrides) -> dict:
        heartbeat = {
            "project": "PIXELVERSE DASHBOARD",
            "agent_id": "DESIGNER",
            "run_id": "run-pixelverse-36",
            "session_id": "session-pixelverse-36",
            "state": "working",
            "heartbeat_at": "2026-08-18T05:59:45Z",
        }
        heartbeat.update(overrides)
        return heartbeat

    def _project(self, events: object, heartbeats: object) -> dict:
        try:
            return self.campus.department_campus_projection(
                events,
                heartbeats=heartbeats,
                now=NOW,
            )
        except TypeError as exc:
            self.fail(
                "RED: department_campus_projection must accept the verified "
                f"heartbeats source ({exc})"
            )

    def test_ac_1_ec_1_only_exactly_fresh_working_heartbeat_creates_live_presence(self):
        boundary = self._heartbeat(
            heartbeat_at=(NOW - timedelta(seconds=45)).isoformat()
        )
        live = self._project([self._event()], [boundary])

        self.assertEqual(live["state"], "active")
        self.assertEqual(live["visible_task_count"], 1)
        self.assertEqual(len(live["events"]), 1)
        self.assertEqual(live["events"][0]["project"], "PIXELVERSE DASHBOARD")
        self.assertEqual(live["events"][0]["agent_id"], "DESIGNER")

        rejected = (
            self._heartbeat(
                heartbeat_at=(NOW - timedelta(seconds=45, microseconds=1)).isoformat()
            ),
            self._heartbeat(heartbeat_at=(NOW + timedelta(microseconds=1)).isoformat()),
            self._heartbeat(state="idle"),
            self._heartbeat(state="waiting"),
        )
        for heartbeat in rejected:
            with self.subTest(heartbeat=heartbeat):
                projection = self._project([self._event()], [heartbeat])
                self.assertNotEqual(projection["state"], "active")
                self.assertEqual(projection["visible_task_count"], 0)
                self.assertEqual(projection["events"], [])

    def test_ac_1_fresh_heartbeat_without_lifecycle_row_synthesizes_safe_live_event(self):
        projection = self._project([], [self._heartbeat()])

        self.assertEqual(projection["state"], "active")
        self.assertEqual(projection["visible_task_count"], 1)
        self.assertEqual(len(projection["events"]), 1)
        event = projection["events"][0]
        self.assertEqual(event["event_id"], "run-pixelverse-36")
        self.assertEqual(event["task_id"], "run-pixelverse-36")
        self.assertEqual(event["project"], "PIXELVERSE DASHBOARD")
        self.assertEqual(event["agent_id"], "DESIGNER")
        self.assertEqual(event["status"], "active")
        self.assertNotIn("session-pixelverse-36", repr(projection))

    def test_ac_2_ec_2_bridge_lifecycle_without_heartbeat_is_history_not_presence(self):
        for status in ("queued", "active", "done", "failed"):
            with self.subTest(status=status):
                projection = self._project([self._event(status=status)], [])
                self.assertNotEqual(projection["state"], "active")
                self.assertEqual(projection["visible_task_count"], 0)
                self.assertEqual(projection["events"], [])

        for terminal_status in ("done", "failed"):
            with self.subTest(terminal_status=terminal_status):
                projection = self._project(
                    [self._event(status=terminal_status)],
                    [self._heartbeat()],
                )
                self.assertNotEqual(projection["state"], "active")
                self.assertEqual(projection["events"], [])

    def test_ac_3_unknown_mismatched_unsafe_or_incomplete_heartbeat_fails_closed(self):
        invalid = (
            self._heartbeat(project="UNKNOWN PROJECT"),
            self._heartbeat(agent_id="BUILDER"),
            self._heartbeat(run_id="../../private/run"),
            self._heartbeat(session_id="token.secret-12345678901234567890"),
            {key: value for key, value in self._heartbeat().items() if key != "session_id"},
            self._heartbeat(heartbeat_at="not-a-time"),
        )
        for heartbeat in invalid:
            with self.subTest(heartbeat=heartbeat):
                projection = self._project([self._event()], [heartbeat])
                self.assertNotEqual(projection["state"], "active")
                self.assertEqual(projection["events"], [])

    def test_ac_3_private_heartbeat_fields_never_enter_public_projection(self):
        heartbeat = self._heartbeat(
            prompt="<private-prompt>",
            task="<private-task>",
            project_dir="/Users/mark/private/project",
            tool_output="<private-tool-output>",
            credential="ghp_abcdefghijklmnopqrstuvwxyz123456",
            raw={"file": "/private/tmp/raw.json"},
        )

        projection = self._project([self._event()], [heartbeat])

        self.assertEqual(projection["state"], "active")
        rendered = repr(projection)
        for forbidden in (
            "<private-prompt>",
            "<private-task>",
            "/Users/mark/private/project",
            "<private-tool-output>",
            "ghp_abcdefghijklmnopqrstuvwxyz123456",
            "/private/tmp/raw.json",
            "session-pixelverse-36",
        ):
            self.assertNotIn(forbidden, rendered)

    def test_err_1_unreadable_or_malformed_heartbeat_storage_has_no_live_events(self):
        malformed_sources = (None, "{bad json", {}, {"heartbeats": "not-a-list"})
        for heartbeats in malformed_sources:
            with self.subTest(heartbeats=heartbeats):
                projection = self._project([self._event()], heartbeats)
                self.assertNotEqual(projection["state"], "active")
                self.assertEqual(projection["events"], [])

    def test_ac_1_err_1_server_reads_heartbeat_file_and_fails_closed_when_unreadable(self):
        spec = importlib.util.spec_from_file_location(
            "dashboard_server_live_truth_red", SERVER_PATH
        )
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        server = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(server)
        bridge_task = {
            "id": "run-pixelverse-36",
            "status": "running",
            "agent_role": "DESIGNER",
            "project": "PIXELVERSE DASHBOARD",
            "created_at": "2026-08-18T05:59:00Z",
            "claimed_at": "2026-08-18T05:59:50Z",
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            unreadable = Path(temp_dir) / "missing-heartbeats.json"
            try:
                projected = server._department_campus_payload(
                    {"tasks": [bridge_task]},
                    heartbeat_path=unreadable,
                    now=NOW,
                )
            except TypeError as exc:
                self.fail(
                    "RED: server payload must read an injected heartbeat_path "
                    f"and fail closed ({exc})"
                )

            self.assertNotEqual(projected["state"], "active")
            self.assertEqual(projected["events"], [])

            valid_path = Path(temp_dir) / "heartbeats.json"
            valid_path.write_text(
                json.dumps(
                    {
                        "updatedAt": "2026-08-18T05:59:45Z",
                        "agents": {
                            "designer": {
                                "project": "PIXELVERSE DASHBOARD",
                                "agentId": "DESIGNER",
                                "runId": "run-pixelverse-36",
                                "sessionId": "session-pixelverse-36",
                                "state": "working",
                                "heartbeatAt": "2026-08-18T05:59:45Z",
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            live = server._department_campus_payload(
                {"tasks": [bridge_task]},
                heartbeat_path=valid_path,
                now=NOW,
            )

            self.assertEqual(live["state"], "active")
            self.assertEqual(live["visible_task_count"], 1)
            self.assertEqual(live["events"][0]["agent_id"], "DESIGNER")

    def test_err_2_duplicate_or_conflicting_agent_identity_fails_that_agent_closed(self):
        duplicate = self._heartbeat(
            run_id="run-pixelverse-duplicate",
            session_id="session-pixelverse-duplicate",
        )
        second_event = self._event(
            event_id="run-pixelverse-duplicate",
            task_id="run-pixelverse-duplicate",
        )

        projection = self._project(
            [self._event(), second_event],
            [self._heartbeat(), duplicate],
        )

        self.assertNotEqual(projection["state"], "active")
        self.assertEqual(projection["visible_task_count"], 0)
        self.assertEqual(projection["events"], [])

    def test_ac_4_all_persistent_residents_are_static_until_verified_live_replacement(self):
        self.assertEqual(len(self.campus.CAMPUS_RESIDENTS), 7)
        self.assertTrue(
            all(resident["wandering"] is False for resident in self.campus.CAMPUS_RESIDENTS)
        )
        html = self.campus.build_department_campus_html()
        self.assertNotIn("is-wandering", html)
        self.assertEqual(html.count("ожидает задач"), 7)

    def test_ac_5_heartbeat_command_refreshes_copy_without_pixel_tool_event(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir)
            details_path = home / ".pixel-agents" / "jarvis-agent-details.json"
            details_path.parent.mkdir(parents=True)
            before = {
                "updatedAt": "2026-08-18T05:50:00.000Z",
                "agents": {
                    "designer": {
                        "role": "designer",
                        "state": "working",
                        "current": "Safe public status",
                        "task": "Safe task copy",
                        "project": "PIXELVERSE DASHBOARD",
                        "agentId": "DESIGNER",
                        "runId": "run-pixelverse-36",
                        "sessionId": "session-pixelverse-36",
                        "heartbeatAt": "2026-08-18T05:50:00.000Z",
                        "history": [{"at": "2026-08-18T05:50:00.000Z", "type": "start"}],
                    }
                },
            }
            details_path.write_text(json.dumps(before), encoding="utf-8")
            environment = os.environ.copy()
            environment.update(
                {
                    "HOME": str(home),
                    "JARVIS_PIXEL_PROJECT_NAME": "PIXELVERSE DASHBOARD",
                    "JARVIS_PIXEL_AGENT_ID": "DESIGNER",
                    "JARVIS_PIXEL_RUN_ID": "run-pixelverse-36",
                    "JARVIS_PIXEL_SESSION_ID": "session-pixelverse-36",
                }
            )

            bundled_node = Path(
                "/Users/mark/.local/node-v22.22.3-darwin-arm64/bin/node"
            )
            node = shutil.which("node") or (
                str(bundled_node) if bundled_node.is_file() else None
            )
            self.assertIsNotNone(
                node,
                "RED environment: Node is required to execute the producer contract",
            )
            result = subprocess.run(
                [node, str(PIXEL_EVENT_PATH), "heartbeat", "designer"],
                text=True,
                capture_output=True,
                env=environment,
                timeout=10,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            after = json.loads(details_path.read_text(encoding="utf-8"))
            record = after["agents"]["designer"]
            for field in ("state", "current", "task", "project", "agentId", "runId", "sessionId", "history"):
                self.assertEqual(record[field], before["agents"]["designer"][field])
            self.assertNotEqual(record["heartbeatAt"], before["agents"]["designer"]["heartbeatAt"])
            self.assertFalse(details_path.with_suffix(".json.tmp").exists())

    def test_ac_5_producer_and_pipeline_define_atomic_bounded_heartbeat_lifecycle(self):
        producer = PIXEL_EVENT_PATH.read_text(encoding="utf-8")
        pipeline = PIPELINE_PATH.read_text(encoding="utf-8")

        for field in ("agentId", "runId", "sessionId", "heartbeatAt"):
            with self.subTest(producer_field=field):
                self.assertIn(field, producer)
        self.assertIn("case 'heartbeat'", producer)
        self.assertRegex(producer, r"writeFileSync\([^\n]*tmp")
        self.assertRegex(producer, r"renameSync\([^\n]*tmp")

        self.assertIn("JARVIS_PIXEL_HEARTBEAT_INTERVAL_SECONDS", pipeline)
        self.assertIn("pixel_event heartbeat", pipeline)
        self.assertRegex(pipeline, r"while[^\n]*(?:kill -0|provider)")
        self.assertRegex(pipeline, r"wait[^\n]*(?:heartbeat|HEARTBEAT)")
        self.assertRegex(pipeline, r"pixel_event (?:done|end)")


if __name__ == "__main__":
    unittest.main()
