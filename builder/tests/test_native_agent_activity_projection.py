from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import importlib
import importlib.util
import json
from pathlib import Path
import re
import tempfile
import unittest


BUILDER_DIR = Path(__file__).resolve().parents[1]
SERVER_PATH = BUILDER_DIR / "dashboard-server-m4.py"
NOW = datetime(2026, 10, 25, 10, 0, tzinfo=timezone.utc)

ROUTES = (
    ("accountable-os", "ACCOUNTABLE OS", "finance", "ANALYST"),
    ("ai-studio", "AI STUDIO", "hq", "COORDINATOR"),
    ("context-news", "CONTEXT_NEWS", "development", "BUILDER"),
    ("financial-os", "FINANCIAL OS", "finance", "ANALYST"),
    ("github-hygiene", "GITHUB HYGIENE", "infrastructure", "ANALYST"),
    ("health-os", "HEALTH OS", "internal", "ANALYST"),
    ("jarvis", "JARVIS", "infrastructure", "BUILDER"),
    ("main-manager", "MAIN MANAGER", "hq", "COORDINATOR"),
    ("my-dictionary", "MY DICTIONARY", "development", "BUILDER"),
    ("pixelverse-dashboard", "PIXELVERSE DASHBOARD", "infrastructure", "BUILDER"),
    ("skills-library", "SKILLS LIBRARY", "internal", "RESEARCHER"),
    ("unfinished-stuff", "UNFINISHED STUFF", "internal", "COORDINATOR"),
)
PRIVATE_SENTINELS = (
    "PRIVATE_PROMPT_SENTINEL_7ed5",
    "PRIVATE_MESSAGE_SENTINEL_7ed5",
    "PRIVATE_TOOL_BODY_SENTINEL_7ed5",
    "PRIVATE_NOTE_SENTINEL_7ed5",
    "PRIVATE_PATH_SENTINEL_7ed5",
    "private-session-7ed5",
    "private-thread-7ed5",
    "pid-998877",
)
FORBIDDEN_KEYS = {
    "hostId",
    "threadId",
    "repository",
    "session_id",
    "sessionId",
    "thread_id",
    "path",
    "cwd",
    "pid",
    "prompt",
    "message",
    "tool_body",
    "notes",
}
PUBLIC_AGENT_FIELDS = {
    "route_id",
    "project",
    "department_id",
    "agent_role",
    "state",
    "availability",
    "freshness",
    "state_at",
    "outcome_stage",
}


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


PUBLISHER = _load(
    "main_manager_status_publisher_native_activity_red",
    BUILDER_DIR / "main_manager_status_publisher.py",
)
SERVER = _load(
    "dashboard_server_native_activity_red",
    SERVER_PATH,
)
try:
    NATIVE = importlib.import_module("dashboard_builder.native_activity")
except ModuleNotFoundError:
    NATIVE = None


def _route_registry() -> dict:
    return {
        "schema": "main_manager_agent_routes_v1",
        "version": 1,
        "routes": {
            route_id: {
                "hostId": "private-host-7ed5",
                "threadId": f"private-thread-{route_id}",
                "project": project,
                "repository": f"pirajoke/{route_id}",
                "departmentId": department_id,
                "zoneId": f"zone-{department_id}",
                "agentRole": agent_role,
                "enabled": True,
            }
            for route_id, project, department_id, agent_role in ROUTES
        },
    }


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(record, ensure_ascii=False) for record in records) + "\n",
        encoding="utf-8",
    )


def _session_records(
    route_id: str,
    *,
    started_at: datetime,
    progress_at: datetime | None = None,
    completed_at: datetime | None = None,
) -> list[dict]:
    records = [
        {
            "timestamp": _iso(started_at - timedelta(seconds=2)),
            "type": "session_meta",
            "payload": {
                "id": f"private-thread-{route_id}",
                "cwd": f"/private/tmp/{PRIVATE_SENTINELS[4]}/{route_id}",
                "agent_path": f"/root/{PRIVATE_SENTINELS[5]}",
            },
        },
        {
            "timestamp": _iso(started_at),
            "type": "event_msg",
            "payload": {
                "type": "task_started",
                "message": PRIVATE_SENTINELS[0],
                "notes": PRIVATE_SENTINELS[3],
                "pid": PRIVATE_SENTINELS[7],
            },
        },
    ]
    if progress_at is not None:
        records.append(
            {
                "timestamp": _iso(progress_at),
                "type": "response_item",
                "payload": {
                    "type": "function_call",
                    "name": "exec_command",
                    "arguments": json.dumps(
                        {
                            "cmd": PRIVATE_SENTINELS[2],
                            "workdir": f"/private/tmp/{PRIVATE_SENTINELS[4]}",
                        }
                    ),
                },
            }
        )
    if completed_at is not None:
        records.append(
            {
                "timestamp": _iso(completed_at),
                "type": "event_msg",
                "payload": {
                    "type": "task_complete",
                    "last_agent_message": PRIVATE_SENTINELS[1],
                },
            }
        )
    return records


def _agent(checkpoint: dict, route_id: str) -> dict:
    return next(agent for agent in checkpoint["agents"] if agent["route_id"] == route_id)


def _all_keys(value: object) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, dict):
        keys.update(str(key) for key in value)
        for child in value.values():
            keys.update(_all_keys(child))
    elif isinstance(value, list):
        for child in value:
            keys.update(_all_keys(child))
    return keys


def _scheduler_status() -> dict:
    return {
        "ok": True,
        "outcome": "status",
        "counts": {
            "queued": 5,
            "owner_gate": 2,
            "active": 0,
            "claimed": 0,
            "agent_stalled": 0,
        },
        "work_counts": {
            "executable_queued": 0,
            "owner_gate": 2,
            "stop_notice": 3,
        },
        "items": [],
        "pixel_events": [
            {
                "project": "JARVIS",
                "agentId": "route",
                "agentRole": "BUILDER",
                "departmentId": "infrastructure",
                "zoneId": "zone-infrastructure",
                "state": "waiting",
                "updatedAt": "2026-10-25T09:45:00Z",
            }
        ],
        "human_projection": [
            {
                "project": "JARVIS",
                "agent": "route",
                "status": "NEEDS MARK",
                "needs_mark": True,
            }
        ],
    }


def _bridge(snapshot: dict, completed_at: str = "2026-10-25T10:00:01Z") -> dict:
    return {
        "tasks": [
            {
                "id": "status-event-safe-id",
                "status": "done",
                "created_at": completed_at,
                "completed_at": completed_at,
                "description": PRIVATE_SENTINELS[0],
                "messages": [{"body": PRIVATE_SENTINELS[1]}],
                "metadata": {
                    **{
                        key: value
                        for key, value in snapshot.items()
                        if key not in {"source_agent", "project"}
                    },
                    "source_agent": "main-manager",
                    "entrypoint": "bridge.status_event",
                    "executable": False,
                    "prompt": PRIVATE_SENTINELS[0],
                    "notes": PRIVATE_SENTINELS[3],
                    "path": PRIVATE_SENTINELS[4],
                    "sessionId": PRIVATE_SENTINELS[5],
                    "pid": PRIVATE_SENTINELS[7],
                },
            }
        ]
    }


class NativeMetadataAdapterRedTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.routes_path = self.root / "agent-routes.json"
        self.route_bytes = json.dumps(
            _route_registry(), ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
        self.routes_path.write_bytes(self.route_bytes)
        self.codex_root = self.root / "codex"
        self.claude_root = self.root / "claude"
        self.codex_root.mkdir()
        self.claude_root.mkdir()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _native(self):
        self.assertIsNotNone(
            NATIVE,
            "RED: the bounded privacy-safe native activity adapter is missing",
        )
        self.assertTrue(
            hasattr(NATIVE, "collect_native_activity"),
            "RED: native_activity must expose collect_native_activity",
        )
        return NATIVE

    def _collect(
        self,
        *,
        alive_names: set[str] | None = None,
        max_files: int = 32,
        max_bytes: int = 256 * 1024,
        roots: dict | None = None,
    ) -> dict:
        alive_names = alive_names or set()

        def process_probe(*args, **kwargs):
            candidates = [*args, *kwargs.values()]
            return any(
                isinstance(candidate, (str, Path))
                and Path(candidate).name in alive_names
                for candidate in candidates
            )

        return self._native().collect_native_activity(
            routes_path=self.routes_path,
            roots=roots
            or {"codex": [self.codex_root], "claude": [self.claude_root]},
            now=NOW,
            process_probe=process_probe,
            max_files=max_files,
            max_bytes=max_bytes,
        )

    def test_exact_enabled_registry_is_hashed_and_projected_once_without_private_identity(self):
        checkpoint = self._collect()

        self.assertEqual(checkpoint["schema"], "manager_native_activity_v1")
        self.assertEqual(checkpoint["observed_at"], _iso(NOW))
        self.assertEqual(
            checkpoint["route_registry_sha256"],
            hashlib.sha256(self.route_bytes).hexdigest(),
        )
        self.assertEqual(
            [agent["route_id"] for agent in checkpoint["agents"]],
            [route[0] for route in ROUTES],
        )
        self.assertEqual(len(checkpoint["agents"]), len(ROUTES))
        for agent, (route_id, project, department_id, agent_role) in zip(
            checkpoint["agents"], ROUTES
        ):
            with self.subTest(route_id=route_id):
                self.assertEqual(set(agent), PUBLIC_AGENT_FIELDS)
                self.assertEqual(
                    (
                        agent["route_id"],
                        agent["project"],
                        agent["department_id"],
                        agent["agent_role"],
                    ),
                    (route_id, project, department_id, agent_role),
                )
                self.assertIsNone(agent["state"])
                self.assertEqual(agent["availability"], "unavailable")
                self.assertEqual(agent["freshness"], "unavailable")
        self.assertFalse(_all_keys(checkpoint) & FORBIDDEN_KEYS)
        rendered = json.dumps(checkpoint, ensure_ascii=False)
        self.assertNotIn("private-host-7ed5", rendered)
        self.assertNotIn("private-thread-", rendered)
        self.assertNotIn("pirajoke/", rendered)

    def test_running_requires_start_progress_freshness_and_process_evidence(self):
        running = self.codex_root / "running.jsonl"
        start_only = self.codex_root / "start-only.jsonl"
        stale = self.codex_root / "stale.jsonl"
        _write_jsonl(
            running,
            _session_records(
                "main-manager",
                started_at=NOW - timedelta(minutes=4),
                progress_at=NOW - timedelta(seconds=30),
            ),
        )
        _write_jsonl(
            start_only,
            _session_records(
                "health-os",
                started_at=NOW - timedelta(seconds=30),
            ),
        )
        _write_jsonl(
            stale,
            _session_records(
                "pixelverse-dashboard",
                started_at=NOW - timedelta(hours=2),
                progress_at=NOW - timedelta(hours=1, minutes=59),
            ),
        )

        checkpoint = self._collect(
            alive_names={running.name, start_only.name, stale.name}
        )

        manager = _agent(checkpoint, "main-manager")
        self.assertEqual(manager["state"], "running")
        self.assertEqual(manager["availability"], "available")
        self.assertEqual(manager["freshness"], "fresh")
        self.assertIsNone(manager["outcome_stage"])

        uncertain = _agent(checkpoint, "health-os")
        self.assertIsNone(
            uncertain["state"],
            "a recent task_started record alone must not manufacture running",
        )
        self.assertEqual(uncertain["availability"], "uncertain")
        self.assertEqual(uncertain["freshness"], "fresh")

        old = _agent(checkpoint, "pixelverse-dashboard")
        self.assertIsNone(old["state"])
        self.assertEqual(old["freshness"], "stale")
        self.assertNotEqual(old["availability"], "available")

    def test_task_complete_is_turn_outcome_only_and_never_project_done(self):
        completed = self.codex_root / "completed.jsonl"
        _write_jsonl(
            completed,
            _session_records(
                "ai-studio",
                started_at=NOW - timedelta(minutes=8),
                progress_at=NOW - timedelta(minutes=2),
                completed_at=NOW - timedelta(minutes=1),
            ),
        )

        ai_studio = _agent(self._collect(), "ai-studio")

        self.assertEqual(ai_studio["state"], "idle")
        self.assertEqual(ai_studio["outcome_stage"], "turn_completed")
        self.assertNotEqual(
            ai_studio["state"],
            "done",
            "task_complete closes a native turn, not the project acceptance criteria",
        )
        self.assertEqual(ai_studio["freshness"], "fresh")

    def test_corrupt_future_out_of_order_and_oversized_sources_fail_closed(self):
        cases: dict[str, tuple[list[dict] | None, str | None, int]] = {
            "future": (
                _session_records(
                    "main-manager",
                    started_at=NOW - timedelta(minutes=2),
                    progress_at=NOW + timedelta(minutes=1),
                ),
                None,
                256 * 1024,
            ),
            "out-of-order": (
                list(
                    reversed(
                        _session_records(
                            "main-manager",
                            started_at=NOW - timedelta(minutes=2),
                            progress_at=NOW - timedelta(minutes=1),
                        )
                    )
                ),
                None,
                256 * 1024,
            ),
            "corrupt": (None, "{not-json}\n", 256 * 1024),
            "oversized": (
                _session_records(
                    "main-manager",
                    started_at=NOW - timedelta(minutes=2),
                    progress_at=NOW - timedelta(minutes=1),
                ),
                None,
                64,
            ),
        }
        for case, (records, raw, max_bytes) in cases.items():
            with self.subTest(case=case):
                case_root = self.root / case
                case_root.mkdir()
                path = case_root / f"{case}.jsonl"
                if records is not None:
                    _write_jsonl(path, records)
                else:
                    path.write_text(raw or "", encoding="utf-8")
                checkpoint = self._collect(
                    roots={"codex": [case_root], "claude": []},
                    alive_names={path.name},
                    max_bytes=max_bytes,
                )
                agent = _agent(checkpoint, "main-manager")
                self.assertIsNone(agent["state"])
                self.assertEqual(agent["availability"], "unavailable")
                self.assertIn(agent["freshness"], {"invalid", "unavailable"})

    def test_scan_is_bounded_and_never_follows_a_source_symlink(self):
        outside = self.root / "outside-private.jsonl"
        _write_jsonl(
            outside,
            _session_records(
                "main-manager",
                started_at=NOW - timedelta(minutes=2),
                progress_at=NOW - timedelta(seconds=10),
            ),
        )
        link = self.codex_root / "linked.jsonl"
        link.symlink_to(outside)

        checkpoint = self._collect(alive_names={link.name}, max_files=1)

        manager = _agent(checkpoint, "main-manager")
        self.assertIsNone(manager["state"])
        self.assertEqual(manager["availability"], "unavailable")
        for sentinel in PRIVATE_SENTINELS:
            self.assertNotIn(sentinel, json.dumps(checkpoint, ensure_ascii=False))


class NativeActivityProjectionRedTests(unittest.TestCase):
    def _checkpoint(self) -> dict:
        agents = []
        for route_id, project, department_id, agent_role in ROUTES:
            state = None
            availability = "unavailable"
            freshness = "unavailable"
            state_at = None
            outcome_stage = None
            if route_id == "main-manager":
                state = "running"
                availability = "available"
                freshness = "fresh"
                state_at = "2026-10-25T09:59:30Z"
            elif route_id == "ai-studio":
                state = "idle"
                availability = "available"
                freshness = "fresh"
                state_at = "2026-10-25T09:59:00Z"
                outcome_stage = "turn_completed"
            agents.append(
                {
                    "route_id": route_id,
                    "project": project,
                    "department_id": department_id,
                    "agent_role": agent_role,
                    "state": state,
                    "availability": availability,
                    "freshness": freshness,
                    "state_at": state_at,
                    "outcome_stage": outcome_stage,
                }
            )
        return {
            "schema": "manager_native_activity_v1",
            "observed_at": _iso(NOW),
            "route_registry_sha256": "a" * 64,
            "agents": agents,
        }

    def _snapshot(self, checkpoint: dict | None = None) -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            queue = Path(tmp) / "continuation-queue.json"
            queue.write_text("{}", encoding="utf-8")
            try:
                return PUBLISHER.build_snapshot(
                    _scheduler_status(),
                    now=NOW,
                    queue_path=queue,
                    native_activity=checkpoint or self._checkpoint(),
                )
            except TypeError as error:
                self.fail(
                    "RED: the existing publisher does not accept the separate "
                    f"native activity checkpoint: {error}"
                )

    def test_publisher_keeps_execution_outcomes_owner_gate_and_work_counts_separate(self):
        snapshot = self._snapshot()

        self.assertEqual(snapshot["native_activity"], self._checkpoint())
        self.assertEqual(
            snapshot["work_counts"],
            {"executable_queued": 0, "owner_gate": 2, "stop_notice": 3},
        )
        self.assertEqual(len(snapshot["pixel_events"]), 1)
        gate = snapshot["pixel_events"][0]
        self.assertEqual(gate["project"], "JARVIS")
        self.assertEqual(gate["status"], "waiting")
        self.assertIs(gate["needs_mark"], True)

    def test_server_projects_full_roster_truthful_counts_and_legacy_gate_together(self):
        payload = SERVER._department_campus_payload(
            _bridge(self._snapshot()),
            now=NOW + timedelta(minutes=1),
            owner_view=True,
        )

        self.assertEqual(len(payload["agents"]), 12)
        self.assertEqual(
            [agent["route_id"] for agent in payload["agents"]],
            [route[0] for route in ROUTES],
        )
        self.assertEqual(
            payload["activity_counts"],
            {
                "enabled": 12,
                "running": 1,
                "idle": 1,
                "waiting": 0,
                "blocked": 0,
                "done": 0,
                "unavailable": 10,
                "turn_completed": 1,
            },
        )
        manager = _agent(payload, "main-manager")
        ai_studio = _agent(payload, "ai-studio")
        self.assertEqual(manager["state"], "running")
        self.assertEqual(ai_studio["state"], "idle")
        self.assertEqual(ai_studio["outcome_stage"], "turn_completed")
        self.assertNotEqual(ai_studio["state"], "done")
        self.assertEqual(payload["work_counts"]["owner_gate"], 2)
        self.assertEqual(len(payload["events"]), 1)
        self.assertEqual(payload["events"][0]["project"], "JARVIS")
        self.assertEqual(payload["events"][0]["status"], "waiting")
        self.assertIs(payload["events"][0]["needs_mark"], True)

    def test_public_and_owner_projection_share_the_same_strict_native_allowlist(self):
        checkpoint = self._checkpoint()
        checkpoint["agents"][0].update(
            {
                "prompt": PRIVATE_SENTINELS[0],
                "message": PRIVATE_SENTINELS[1],
                "tool_body": PRIVATE_SENTINELS[2],
                "notes": PRIVATE_SENTINELS[3],
                "path": PRIVATE_SENTINELS[4],
                "session_id": PRIVATE_SENTINELS[5],
                "thread_id": PRIVATE_SENTINELS[6],
                "pid": PRIVATE_SENTINELS[7],
            }
        )
        bridge = _bridge(self._snapshot(checkpoint))

        for owner_view in (False, True):
            with self.subTest(owner_view=owner_view):
                payload = SERVER._department_campus_payload(
                    bridge,
                    now=NOW + timedelta(minutes=1),
                    owner_view=owner_view,
                )
                rendered = json.dumps(payload, ensure_ascii=False)
                for sentinel in PRIVATE_SENTINELS:
                    self.assertNotIn(sentinel, rendered)
                self.assertFalse(_all_keys(payload) & FORBIDDEN_KEYS)
                for agent in payload["agents"]:
                    self.assertEqual(set(agent), PUBLIC_AGENT_FIELDS)

    def test_invalid_native_checkpoint_fails_closed_without_hiding_owner_gate(self):
        invalid_checkpoints = (
            {**self._checkpoint(), "observed_at": "2030-01-01T00:00:00Z"},
            {**self._checkpoint(), "route_registry_sha256": "not-a-hash"},
            {**self._checkpoint(), "agents": self._checkpoint()["agents"][:-1]},
            {**self._checkpoint(), "agents": list(reversed(self._checkpoint()["agents"]))},
        )
        for checkpoint in invalid_checkpoints:
            with self.subTest(checkpoint=checkpoint.get("observed_at")):
                payload = SERVER._department_campus_payload(
                    _bridge(self._snapshot(checkpoint)),
                    now=NOW + timedelta(minutes=1),
                )
                self.assertEqual(payload.get("agents"), [])
                self.assertEqual(payload.get("activity_counts", {}).get("running"), 0)
                self.assertEqual(len(payload["events"]), 1)
                self.assertIs(payload["events"][0]["needs_mark"], True)

    def test_existing_needs_mark_waiting_contract_is_unchanged(self):
        legacy_snapshot = {
            "source_agent": "main-manager",
            "event": "status",
            "project": "MAIN MANAGER",
            "observed_at": _iso(NOW),
            "queue_updated_at": "2026-10-25T09:45:00Z",
            "pixel_events": PUBLISHER.build_events(_scheduler_status()),
        }
        payload = SERVER._department_campus_payload(
            _bridge(legacy_snapshot),
            now=NOW + timedelta(minutes=1),
            owner_view=True,
        )

        self.assertEqual(payload["events"][0]["status"], "waiting")
        self.assertIs(payload["events"][0]["needs_mark"], True)

    def test_ui_consumes_route_roster_counts_and_only_moves_verified_running_activity(self):
        script = (BUILDER_DIR / "dashboard-assets" / "script.js").read_text(
            encoding="utf-8"
        )

        for contract in (
            "payload.agents",
            "activity_counts",
            "route_id",
            "outcome_stage",
        ):
            with self.subTest(contract=contract):
                self.assertTrue(
                    contract in script,
                    f"RED: campus UI is missing native activity contract {contract!r}",
                )
        movement_guard = (
            r"state\s*===\s*['\"]running['\"][\s\S]{0,320}"
            r"availability\s*===\s*['\"]available['\"][\s\S]{0,320}"
            r"freshness\s*===\s*['\"]fresh['\"]"
        )
        self.assertTrue(
            re.search(movement_guard, script) is not None,
            "RED: movement must require running + available + fresh evidence",
        )
        collapsed_role_count = re.search(
            r"new Set\(\s*matchedEvents\.map\([^)]*agent_id", script
        )
        self.assertIsNone(
            collapsed_role_count,
            "route counts must not collapse multiple registered routes sharing one role",
        )


if __name__ == "__main__":
    unittest.main()
