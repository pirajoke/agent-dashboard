from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import urllib.request


BUILDER_DIR = Path(__file__).resolve().parents[1]
SERVER_PATH = BUILDER_DIR / "dashboard-server-m4.py"
NOW = datetime(2026, 8, 12, 12, 0, tzinfo=timezone.utc)
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
QUEUE_ID_FIELDS = (
    "dedupe_key",
    "project",
    "repository",
    "source_task_id",
    "completed_at",
    "evidence_fingerprint",
    "decision",
    "owner_gate",
    "next_step",
    "next_task",
)


def canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


class DepartmentCampusContinuationQueueTests(unittest.TestCase):
    def setUp(self) -> None:
        server_spec = importlib.util.spec_from_file_location(
            "dashboard_server_continuation_queue_red", SERVER_PATH
        )
        self.assertIsNotNone(server_spec)
        self.assertIsNotNone(server_spec.loader)
        self.server = importlib.util.module_from_spec(server_spec)
        server_spec.loader.exec_module(self.server)

        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.queue_path = self.root / "continuation-queue.json"
        self.routes_path = self.root / "agent-routes.json"
        self.routes = {
            "schema": "main_manager_agent_routes_v1",
            "version": 1,
            "routes": {
                "dictionary-builder": {
                    "hostId": "remote-ssh-discovered:maxxs-mac-mini",
                    "threadId": "019fdcb4-af7b-7270-9c6d-000000000001",
                    "project": "MY DICTIONARY",
                    "repository": "pirajoke/mydictionary",
                    "departmentId": "development",
                    "zoneId": "zone-development",
                    "agentRole": "BUILDER",
                    "enabled": True,
                }
            },
        }

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _write_json(self, path: Path, value: object) -> None:
        path.write_text(
            json.dumps(value, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )

    def _claim(self) -> dict:
        return {
            "claim_id": "claim-pixel-red",
            "claimer": "main-manager-heartbeat",
            "claimed_at": "2026-08-12T11:56:00+00:00",
            "lease_expires_at": "2026-08-12T12:04:00+00:00",
        }

    def _dispatch(
        self,
        *,
        prepared_at: str = "2026-08-12T11:57:00+00:00",
        delivery_reason: str | None = None,
        observed_at: str | None = None,
    ) -> dict:
        return {
            "route_id": "dictionary-builder",
            "hostId": "remote-ssh-discovered:maxxs-mac-mini",
            "threadId": "019fdcb4-af7b-7270-9c6d-000000000001",
            "registry_sha256": "a" * 64,
            "message_fingerprint": "b" * 64,
            "prepared_at": prepared_at,
            "delivery_reason": delivery_reason,
            "observed_at": observed_at,
        }

    def _item(
        self,
        status: str = "queued",
        *,
        index: int = 1,
        project: str = "MY DICTIONARY",
        repository: str = "pirajoke/mydictionary",
        agent_role: str = "BUILDER",
        decision: str = "auto_continue",
        owner_gate: str = "none",
        next_step: str = "Continue safe verification.",
        terminal_status: str = "completed",
    ) -> dict:
        fingerprint = f"{index:064x}"
        next_task = (
            {
                "description": "Inspect the registered project and report safe status.",
                "agent_role": agent_role,
                "project": project,
                "metadata": {"allowed_side_effects": ["read_repository"]},
            }
            if decision == "auto_continue"
            else None
        )
        item = {
            "queue_id": "",
            "dedupe_key": f"{project}|{fingerprint}|{decision}",
            "project": project,
            "repository": repository,
            "source_task_id": f"pixel-red-{index}",
            "completed_at": "2026-08-12T11:55:00+00:00",
            "evidence_fingerprint": fingerprint,
            "decision": decision,
            "owner_gate": owner_gate,
            "next_step": next_step,
            "next_task": next_task,
            "status": status,
            "claim": None,
            "ack": None,
        }
        if status != "queued":
            item["claim"] = self._claim()
        if status in {"sending", "delivery_unknown", "active"}:
            item["dispatch"] = self._dispatch(
                delivery_reason=(
                    "tool_timeout" if status == "delivery_unknown" else None
                ),
                observed_at=(
                    "2026-08-12T11:58:00+00:00"
                    if status == "delivery_unknown"
                    else None
                ),
            )
        if status == "active":
            item["ack"] = {
                "reason": "sent_to_thread",
                "acked_at": "2026-08-12T11:58:30+00:00",
                "thread_id": self._dispatch()["threadId"],
            }
        if status == "acked" and decision == "auto_continue":
            item["dispatch"] = self._dispatch()
            item["ack"] = {
                "reason": "sent_to_thread",
                "acked_at": "2026-08-12T11:58:30+00:00",
                "thread_id": self._dispatch()["threadId"],
                "terminal_status": terminal_status,
                "terminal_at": "2026-08-12T11:59:00+00:00",
            }
        elif status == "acked":
            item["ack"] = {
                "reason": "owner_gate_reported" if decision == "owner_gate" else "terminal_notice_reported",
                "acked_at": "2026-08-12T11:58:30+00:00",
                "thread_id": None,
            }

        immutable = {field: item[field] for field in QUEUE_ID_FIELDS}
        item["queue_id"] = "mmq_" + hashlib.sha256(canonical_json(immutable)).hexdigest()
        return item

    def _write_sources(
        self,
        items: list[dict],
        *,
        routes: dict | None = None,
    ) -> None:
        self._write_json(self.queue_path, {"version": 1, "items": items})
        self._write_json(self.routes_path, routes or self.routes)

    def _project(
        self,
        *,
        bridge_data: object | None = None,
        queue_path: Path | None | object = ...,
        routes_path: Path | None | object = ...,
    ) -> dict:
        projector = getattr(
            self.server,
            "_department_campus_payload_from_sources",
            None,
        )
        self.assertTrue(
            callable(projector),
            "RED: Dashboard lacks direct continuation-queue projection boundary",
        )
        selected_queue = self.queue_path if queue_path is ... else queue_path
        selected_routes = self.routes_path if routes_path is ... else routes_path
        return projector(
            queue_path=selected_queue,
            routes_path=selected_routes,
            bridge_data={"tasks": []} if bridge_data is None else bridge_data,
            now=NOW,
        )

    def _bridge_task(self) -> dict:
        return {
            "id": "bridge-should-not-overlay",
            "status": "running",
            "agent_role": "INFRASTRUCTURE",
            "project": "JARVIS",
            "created_at": "2026-08-12T11:55:00Z",
            "claimed_at": "2026-08-12T11:59:00Z",
        }

    def test_AC01_AC04_queue_is_direct_primary_and_keeps_exact_public_shape(self) -> None:
        item = self._item("sending")
        self._write_sources([item])

        projected = self._project(bridge_data={"tasks": [self._bridge_task()]})

        self.assertEqual(tuple(projected), TOP_LEVEL_FIELDS)
        self.assertEqual(projected["state"], "active")
        self.assertEqual(projected["visible_task_count"], 1)
        self.assertEqual(projected["omitted_task_count"], 0)
        self.assertEqual(projected["privacy"], "public_projection")
        self.assertEqual(len(projected["events"]), 1)
        event = projected["events"][0]
        self.assertEqual(tuple(event), PUBLIC_EVENT_FIELDS)
        self.assertEqual(event["event_id"], item["queue_id"])
        self.assertEqual(event["task_id"], item["queue_id"])
        self.assertEqual(event["project"], "MY DICTIONARY")
        self.assertEqual(event["department_id"], "development")
        self.assertEqual(event["department_label"], "Development")
        self.assertEqual(event["agent_id"], "BUILDER")
        self.assertEqual(event["role"], "Builder")
        self.assertEqual(event["zone_id"], "campus-zone-development")
        self.assertNotIn("JARVIS", repr(projected))

    def test_AC02_AC03_lifecycle_and_transition_times_are_honest(self) -> None:
        cases = (
            (self._item("queued", index=1), "queued", "2026-08-12T11:55:00Z"),
            (self._item("claimed", index=2), "active", "2026-08-12T11:56:00Z"),
            (self._item("sending", index=3), "active", "2026-08-12T11:57:00Z"),
            (self._item("active", index=4), "active", "2026-08-12T11:57:00Z"),
            (self._item("delivery_unknown", index=5), "failed", "2026-08-12T11:58:00Z"),
            (self._item("acked", index=6), "done", "2026-08-12T11:59:00Z"),
            (
                self._item(
                    "acked",
                    index=7,
                    decision="owner_gate",
                    owner_gate="merge",
                ),
                "waiting",
                "2026-08-12T11:58:30Z",
            ),
            (
                self._item("acked", index=8, terminal_status="failed"),
                "failed",
                "2026-08-12T11:59:00Z",
            ),
        )
        for item, public_status, updated_at in cases:
            with self.subTest(queue_status=item["status"], public_status=public_status):
                self._write_sources([item])
                event = self._project()["events"][0]
                self.assertEqual(event["status"], public_status)
                self.assertEqual(event["updated_at"], updated_at)

    def test_AC05_EC01_caps_three_queue_lanes_and_reports_omitted_count(self) -> None:
        projects = (
            ("MAIN MANAGER", "pirajoke/main-manager", "hq", "COORDINATOR"),
            ("AI STUDIO", "pirajoke/grachev-ai-studio", "sales", "RESEARCHER"),
            ("MY DICTIONARY", "pirajoke/mydictionary", "development", "BUILDER"),
            ("SKILLS LIBRARY", "pirajoke/skills-library", "internal", "VAULT"),
            ("FINANCIAL OS", "pirajoke/financial-os", "finance", "ANALYST"),
        )
        items = []
        routes = deepcopy(self.routes)
        routes["routes"] = {}
        for index, (project, repository, department, role) in enumerate(projects, 1):
            route_id = f"pixel-route-{index}"
            thread_id = f"019fdcb4-af7b-7270-9c6d-{index:012d}"
            routes["routes"][route_id] = {
                "hostId": "remote-ssh-discovered:maxxs-mac-mini",
                "threadId": thread_id,
                "project": project,
                "repository": repository,
                "departmentId": department,
                "zoneId": f"zone-{department}",
                "agentRole": role,
                "enabled": True,
            }
            item = self._item(
                "sending",
                index=index,
                project=project,
                repository=repository,
                agent_role=role,
            )
            item["dispatch"]["route_id"] = route_id
            item["dispatch"]["threadId"] = thread_id
            items.append(item)
        self._write_sources(items, routes=routes)

        projected = self._project()

        self.assertEqual(projected["visible_task_count"], 3)
        self.assertEqual(projected["omitted_task_count"], 2)
        self.assertEqual(
            [event["project"] for event in projected["events"]],
            [project[0] for project in projects[:3]],
        )

    def test_AC06_projection_is_read_only_and_starts_no_external_work(self) -> None:
        self._write_sources([self._item("sending")])
        queue_before = self.queue_path.read_bytes()
        routes_before = self.routes_path.read_bytes()
        names_before = sorted(path.name for path in self.root.iterdir())

        with (
            patch.object(subprocess, "run", side_effect=AssertionError("subprocess forbidden")),
            patch.object(subprocess, "Popen", side_effect=AssertionError("subprocess forbidden")),
            patch.object(urllib.request, "urlopen", side_effect=AssertionError("network forbidden")),
            patch.object(os, "replace", side_effect=AssertionError("write forbidden")),
            patch.object(Path, "write_text", side_effect=AssertionError("write forbidden")),
            patch.object(Path, "write_bytes", side_effect=AssertionError("write forbidden")),
        ):
            projected = self._project()

        self.assertEqual(projected["state"], "active")
        self.assertEqual(self.queue_path.read_bytes(), queue_before)
        self.assertEqual(self.routes_path.read_bytes(), routes_before)
        self.assertEqual(sorted(path.name for path in self.root.iterdir()), names_before)

    def test_AC07_ERR01_ERR03_missing_malformed_and_stale_authoritative_state_clears_agents(self) -> None:
        bridge = {"tasks": [self._bridge_task()]}
        self._write_json(self.routes_path, self.routes)
        missing = self._project(bridge_data=bridge)
        self.assertEqual(missing["state"], "unavailable")
        self.assertEqual(missing["events"], [])

        malformed_cases = (
            {"version": 2, "items": [self._item()]},
            {"version": 1, "items": [dict(self._item(), raw_prompt="private")]},
            {"version": 1, "items": [dict(self._item(), status="unknown")]},
        )
        for malformed in malformed_cases:
            with self.subTest(malformed=malformed):
                self._write_json(self.queue_path, malformed)
                projected = self._project(bridge_data=bridge)
                self.assertEqual(projected["state"], "unavailable")
                self.assertEqual(projected["events"], [])

        stale = self._item("sending")
        stale["dispatch"]["prepared_at"] = "2026-08-12T11:20:00+00:00"
        self._write_sources([stale])
        projected = self._project(bridge_data=bridge)
        self.assertEqual(projected["state"], "stale")
        self.assertEqual(projected["events"], [])

    def test_AC07_EC03_EC04_EC05_invalid_or_ambiguous_routes_fail_closed(self) -> None:
        self._write_sources([self._item("sending")])
        invalid_routes = []

        extra_field = deepcopy(self.routes)
        extra_field["routes"]["dictionary-builder"]["prompt"] = "forbidden"
        invalid_routes.append(extra_field)

        disabled = deepcopy(self.routes)
        disabled["routes"]["dictionary-builder"]["enabled"] = False
        invalid_routes.append(disabled)

        wrong_identity = deepcopy(self.routes)
        wrong_identity["routes"]["dictionary-builder"]["repository"] = "pirajoke/other"
        invalid_routes.append(wrong_identity)

        duplicate_destination = deepcopy(self.routes)
        duplicate_destination["routes"]["duplicate"] = {
            **duplicate_destination["routes"]["dictionary-builder"],
            "project": "ACCOUNTABLE OS",
            "repository": "pirajoke/accountable-os",
        }
        invalid_routes.append(duplicate_destination)

        ambiguous = deepcopy(self.routes)
        ambiguous["routes"]["dictionary-tester"] = {
            **ambiguous["routes"]["dictionary-builder"],
            "threadId": "019fdcb4-af7b-7270-9c6d-000000000002",
            "agentRole": "TESTER",
        }
        item = self._item("claimed", agent_role="ANALYST")

        for routes in invalid_routes:
            with self.subTest(routes=routes):
                self._write_sources([self._item("sending")], routes=routes)
                projected = self._project()
                self.assertEqual(projected["state"], "unavailable")
                self.assertEqual(projected["events"], [])

        self._write_sources([item], routes=ambiguous)
        projected = self._project()
        self.assertEqual(projected["state"], "unavailable")
        self.assertEqual(projected["events"], [])

    def test_ERR02_private_queue_and_route_data_never_reaches_public_projection(self) -> None:
        item = self._item("sending")
        item["next_task"]["description"] = "Private client prompt body"
        routes = deepcopy(self.routes)
        routes["routes"]["dictionary-builder"]["hostId"] = "private-host"
        routes["routes"]["dictionary-builder"]["threadId"] = "private-thread"
        item["dispatch"]["hostId"] = "private-host"
        item["dispatch"]["threadId"] = "private-thread"
        self._write_sources([item], routes=routes)

        projected = self._project()

        self.assertEqual(projected["state"], "active")
        rendered = repr(projected)
        for private_value in (
            "Private client prompt body",
            "private-host",
            "private-thread",
            item["repository"],
            item["dedupe_key"],
            item["evidence_fingerprint"],
            item["dispatch"]["message_fingerprint"],
        ):
            self.assertNotIn(private_value, rendered)

        unsafe = self._item(
            "sending",
            index=2,
            next_step="Read /Users/private/vault and token=super-secret-value.",
        )
        unsafe["dispatch"]["hostId"] = "private-host"
        unsafe["dispatch"]["threadId"] = "private-thread"
        self._write_sources([unsafe], routes=routes)
        rejected = self._project()
        self.assertEqual(rejected["state"], "unavailable")
        self.assertEqual(rejected["events"], [])
        self.assertNotIn("super-secret-value", repr(rejected))

    def test_AC08_EC02_bridge_is_exclusive_fallback_only_when_queue_is_unconfigured(self) -> None:
        bridge = {"tasks": [self._bridge_task()]}

        fallback = self._project(
            bridge_data=bridge,
            queue_path=None,
            routes_path=None,
        )
        self.assertEqual(fallback["state"], "active")
        self.assertEqual([event["project"] for event in fallback["events"]], ["JARVIS"])

        half_configured = self._project(
            bridge_data=bridge,
            queue_path=self.queue_path,
            routes_path=None,
        )
        self.assertEqual(half_configured["state"], "unavailable")
        self.assertEqual(half_configured["events"], [])

        self._write_sources([])
        authoritative_empty = self._project(bridge_data=bridge)
        self.assertEqual(authoritative_empty["state"], "empty")
        self.assertEqual(authoritative_empty["events"], [])


if __name__ == "__main__":
    unittest.main()
