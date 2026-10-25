from __future__ import annotations

from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from dashboard_builder import native_activity as NATIVE


BUILDER = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


PUBLISHER = _load("native_hardening_publisher", BUILDER / "main_manager_status_publisher.py")
SERVER = _load("native_hardening_server", BUILDER / "dashboard-server-m4.py")


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _routes() -> dict:
    return {
        "schema": NATIVE.ROUTE_SCHEMA,
        "version": 1,
        "routes": {
            route_id: {
                "hostId": "local",
                "threadId": f"thread-{route_id}",
                "project": project,
                "repository": "owner/repo",
                "departmentId": department,
                "zoneId": f"zone-{department}",
                "agentRole": role,
                "enabled": True,
            }
            for route_id, project, department, role in NATIVE.ROUTE_CONTRACT
        },
    }


def _checkpoint(observed: datetime = NOW) -> dict:
    return {
        "schema": NATIVE.SCHEMA,
        "observed_at": _iso(observed),
        "route_registry_sha256": "a" * 64,
        "agents": [NATIVE._empty_agent(route) for route in NATIVE.ROUTE_CONTRACT],
    }


def _set_agent(checkpoint: dict, route_id: str, **values) -> dict:
    next(agent for agent in checkpoint["agents"] if agent["route_id"] == route_id).update(values)
    return checkpoint


def _task(checkpoint: object, envelope: datetime, *, events: list | None = None) -> dict:
    return {
        "id": f"safe-{int(envelope.timestamp())}",
        "status": "done",
        "completed_at": _iso(envelope),
        "metadata": {
            "source_agent": "main-manager",
            "event": "status",
            "entrypoint": "bridge.status_event",
            "executable": False,
            "pixel_events": events or [],
            "native_activity": checkpoint,
        },
    }


def _records(route_id: str, started: datetime, *, progress: datetime | None = None) -> list[dict]:
    records = [
        {
            "timestamp": _iso(started - timedelta(seconds=1)),
            "type": "session_meta",
            "payload": {"id": f"thread-{route_id}"},
        },
        {"timestamp": _iso(started), "type": "event_msg", "payload": {"type": "task_started"}},
    ]
    if progress is not None:
        records.append(
            {"timestamp": _iso(progress), "type": "response_item", "payload": {"type": "function_call"}}
        )
    return records


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8")


class NativeCheckpointHardeningTests(unittest.TestCase):
    def test_server_reages_states_and_rejects_invented_outcome_states(self):
        stale_running = _set_agent(
            _checkpoint(),
            "main-manager",
            state="running",
            availability="available",
            freshness="fresh",
            state_at=_iso(NOW - timedelta(minutes=20)),
        )
        payload = SERVER._department_campus_payload(
            {"tasks": [_task(stale_running, NOW)]},
            now=NOW,
        )
        self.assertEqual(len(payload["agents"]), len(NATIVE.ROUTE_CONTRACT))
        manager = next(agent for agent in payload["agents"] if agent["route_id"] == "main-manager")
        self.assertIsNone(manager["state"])
        self.assertEqual(manager["availability"], "unavailable")
        self.assertEqual(manager["freshness"], "stale")
        self.assertIsNone(manager["outcome_stage"])

        for invented in ("waiting", "blocked", "done"):
            with self.subTest(invented=invented):
                checkpoint = _set_agent(
                    _checkpoint(),
                    "main-manager",
                    state=invented,
                    availability="available",
                    freshness="fresh",
                    state_at=_iso(NOW - timedelta(seconds=10)),
                )
                self.assertIsNone(NATIVE.validate_native_activity_checkpoint(checkpoint, now=NOW))

        invalid_old_running = _set_agent(
            _checkpoint(),
            "main-manager",
            state="running",
            availability="uncertain",
            freshness="fresh",
            state_at=_iso(NOW - timedelta(minutes=20)),
        )
        self.assertIsNone(
            NATIVE.validate_native_activity_checkpoint(invalid_old_running, now=NOW),
            "aging must not launder an invalid original cross-field claim",
        )

    def test_newest_declared_lane_fails_closed_and_valid_selection_uses_observed_at(self):
        older_valid = _set_agent(
            _checkpoint(NOW - timedelta(minutes=2)),
            "main-manager",
            state="running",
            availability="available",
            freshness="fresh",
            state_at=_iso(NOW - timedelta(minutes=2)),
        )
        newer_invalid = _task({}, NOW - timedelta(minutes=1))
        payload = SERVER._department_campus_payload(
            {"tasks": [_task(older_valid, NOW - timedelta(minutes=2)), newer_invalid]},
            now=NOW,
        )
        self.assertEqual(payload["agents"], [])
        future = SERVER._department_campus_payload(
            {"tasks": [_task(older_valid, NOW - timedelta(minutes=2)), _task({}, NOW + timedelta(seconds=1))]},
            now=NOW,
        )
        self.assertEqual(future["agents"], [])
        observed_after_envelope = _checkpoint(NOW - timedelta(seconds=30))
        impossible = SERVER._department_campus_payload(
            {
                "tasks": [
                    _task(older_valid, NOW - timedelta(minutes=2)),
                    _task(observed_after_envelope, NOW - timedelta(minutes=1)),
                ]
            },
            now=NOW,
        )
        self.assertEqual(impossible["agents"], [])

        newer_envelope_older_observation = _set_agent(
            _checkpoint(NOW - timedelta(minutes=4)),
            "main-manager",
            state="running",
            availability="available",
            freshness="fresh",
            state_at=_iso(NOW - timedelta(minutes=4)),
        )
        older_envelope_newer_observation = _set_agent(
            _checkpoint(NOW - timedelta(minutes=2)),
            "ai-studio",
            state="idle",
            availability="available",
            freshness="fresh",
            state_at=_iso(NOW - timedelta(minutes=2)),
            outcome_stage="turn_completed",
        )
        selected = SERVER._department_campus_payload(
            {
                "tasks": [
                    _task(newer_envelope_older_observation, NOW - timedelta(seconds=30)),
                    _task(older_envelope_newer_observation, NOW - timedelta(minutes=1)),
                ]
            },
            now=NOW,
        )
        self.assertEqual(
            next(agent for agent in selected["agents"] if agent["route_id"] == "ai-studio")["state"],
            "idle",
        )

    def test_fresh_orderable_declaration_recovers_from_old_unorderable_record(self):
        checkpoint = _set_agent(
            _checkpoint(NOW - timedelta(seconds=20)),
            "main-manager",
            state="running",
            availability="available",
            freshness="fresh",
            state_at=_iso(NOW - timedelta(seconds=30)),
        )
        malformed = _task({}, NOW - timedelta(minutes=10))
        malformed["completed_at"] = "not-a-time"
        payload = SERVER._department_campus_payload(
            {"tasks": [malformed, _task(checkpoint, NOW - timedelta(seconds=10))]},
            now=NOW,
        )
        self.assertEqual(len(payload["agents"]), len(NATIVE.ROUTE_CONTRACT))
        manager = next(agent for agent in payload["agents"] if agent["route_id"] == "main-manager")
        self.assertEqual(manager["state"], "running")

    def test_uncertain_is_counted_as_without_confirmation(self):
        checkpoint = _set_agent(
            _checkpoint(),
            "main-manager",
            availability="uncertain",
            freshness="fresh",
            state_at=_iso(NOW - timedelta(seconds=20)),
        )
        payload = SERVER._department_campus_payload({"tasks": [_task(checkpoint, NOW)]}, now=NOW)
        self.assertEqual(payload["activity_counts"]["unavailable"], 12)


class NativeSourceHardeningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.routes = self.root / "routes.json"
        self.routes.write_text(json.dumps(_routes()), encoding="utf-8")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_private_subtrees_are_never_decoded_by_the_envelope_parser(self):
        decoded: list[bytes] = []
        original = NATIVE._EnvelopeJsonParser._selected_string

        def observed(token: bytes) -> str:
            decoded.append(token)
            return original(token)

        line = (
            b'{"timestamp":"2026-10-25T11:59:00Z","type":"event_msg",'
            b'"payload":{"type":"task_started","message":{"poison":"PRIVATE_VALUE"},'
            b'"arguments":"PRIVATE_TOOL_BODY"}}'
        )
        with (
            patch.object(NATIVE._EnvelopeJsonParser, "_selected_string", side_effect=observed),
            patch.object(NATIVE.json, "loads", side_effect=AssertionError("whole record decoded")),
        ):
            envelope = NATIVE._parse_jsonl_envelope(line)
        self.assertEqual(envelope["payload"]["type"], "task_started")
        self.assertNotIn(b"PRIVATE_VALUE", b"".join(decoded))
        self.assertNotIn(b"PRIVATE_TOOL_BODY", b"".join(decoded))

    def test_skipped_private_strings_and_keys_are_not_returned_or_copied(self):
        returned: list[bytes | None] = []
        original = NATIVE._EnvelopeJsonParser._string_token

        def observed(parser, *args, **kwargs):
            token = original(parser, *args, **kwargs)
            returned.append(token)
            return token

        line = (
            b'{"timestamp":"2026-10-25T11:59:00Z","type":"event_msg",'
            b'"payload":{"type":"task_started","deep_private_key":'
            b'{"nested_private_key":"PRIVATE_VALUE"}}}'
        )
        with patch.object(NATIVE._EnvelopeJsonParser, "_string_token", new=observed):
            envelope = NATIVE._parse_jsonl_envelope(line)
        self.assertEqual(envelope["payload"]["type"], "task_started")
        self.assertNotIn(b'"deep_private_key"', returned)
        self.assertNotIn(b'"nested_private_key"', returned)
        self.assertNotIn(b'"PRIVATE_VALUE"', returned)

    def test_invalid_utf8_inside_skipped_private_data_fails_closed(self):
        line = (
            b'{"timestamp":"2026-10-25T11:59:00Z","type":"event_msg",'
            b'"payload":{"type":"task_started","message":"\xff"}}'
        )
        with self.assertRaises(NATIVE._EnvelopeJsonError):
            NATIVE._parse_jsonl_envelope(line)

    def test_recognized_untimestamped_transition_invalidates_newest_source(self):
        source = self.root / "codex"
        old = source / "old.jsonl"
        new = source / "new.jsonl"
        _write_jsonl(old, _records("main-manager", NOW - timedelta(minutes=2), progress=NOW - timedelta(minutes=1)))
        records = _records("main-manager", NOW - timedelta(seconds=40), progress=NOW - timedelta(seconds=30))
        records.append({"type": "event_msg", "payload": {"type": "task_started"}})
        _write_jsonl(new, records)
        old_time = (NOW - timedelta(minutes=1)).timestamp()
        new_time = NOW.timestamp()
        os.utime(old, (old_time, old_time))
        os.utime(new, (new_time, new_time))

        checkpoint = NATIVE.collect_native_activity(
            routes_path=self.routes,
            roots={"codex": [source]},
            now=NOW,
            process_probe=lambda *args, **kwargs: True,
            max_files=8,
            max_bytes=256 * 1024,
        )
        manager = next(agent for agent in checkpoint["agents"] if agent["route_id"] == "main-manager")
        self.assertIsNone(manager["state"])
        self.assertEqual(manager["freshness"], "invalid")

    def test_unrelated_file_opener_is_not_process_proof(self):
        with patch.object(NATIVE, "_bounded_process_output", return_value=(0, b"p1\nctail\n")):
            self.assertFalse(NATIVE.default_process_probe(self.root / "session.jsonl", source="codex"))
        trusted = Path.home() / ".codex/packages/standalone/releases/1.0/bin/codex"
        with (
            patch.object(NATIVE, "_bounded_process_output", return_value=(0, b"p2\ncCodex\n")),
            patch.object(NATIVE, "_kernel_executable_path", return_value=trusted),
        ):
            self.assertTrue(NATIVE.default_process_probe(self.root / "session.jsonl", source="codex"))

    def test_spoofed_codex_basename_requires_a_trusted_kernel_executable_path(self):
        lsof = (0, b"p4242\ncCodex\n")
        with (
            patch.object(NATIVE, "_bounded_process_output", return_value=lsof),
            patch.object(
                NATIVE,
                "_kernel_executable_path",
                create=True,
                return_value=Path("/tmp/untrusted/codex"),
            ),
        ):
            self.assertFalse(
                NATIVE.default_process_probe(self.root / "session.jsonl", source="codex")
            )
        with (
            patch.object(NATIVE, "_bounded_process_output", return_value=lsof),
            patch.object(NATIVE, "_kernel_executable_path", create=True, return_value=None),
        ):
            self.assertFalse(
                NATIVE.default_process_probe(self.root / "session.jsonl", source="codex")
            )
        trusted = Path.home() / ".codex/packages/standalone/releases/1.0/bin/codex"
        with (
            patch.object(NATIVE, "_bounded_process_output", return_value=lsof),
            patch.object(
                NATIVE,
                "_kernel_executable_path",
                create=True,
                return_value=trusted,
            ),
        ):
            self.assertTrue(
                NATIVE.default_process_probe(self.root / "session.jsonl", source="codex")
            )

    def test_only_reviewed_codex_and_claude_install_structures_are_trusted(self):
        home = Path("/Users/safe-owner")
        trusted = {
            "codex": (
                Path("/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex"),
                home / ".codex/packages/standalone/current/bin/codex",
                home / ".codex/packages/standalone/releases/1.2.3/bin/codex",
            ),
            "claude": (
                Path("/Applications/Claude.app/Contents/MacOS/Claude"),
                home
                / "Library/Application Support/Claude/claude-code/2.1.295/build/claude.app/Contents/MacOS/claude",
                home / ".claude/remote/ccd-cli/2.1.299-abcdef",
                home / ".claude/remote/srv/" / ("a" * 40) / "server",
            ),
        }
        for source, paths in trusted.items():
            for path in paths:
                with self.subTest(source=source, path=path.name):
                    self.assertTrue(NATIVE._trusted_executable_path(source, path, home=home))
        self.assertFalse(
            NATIVE._trusted_executable_path("codex", Path("/tmp/codex"), home=home)
        )
        self.assertFalse(
            NATIVE._trusted_executable_path(
                "claude",
                home / ".claude/remote/not-reviewed/claude",
                home=home,
            )
        )

    def test_jsonl_iteration_uses_views_instead_of_copying_every_line(self):
        source = self.root / "codex"
        session = source / "session.jsonl"
        _write_jsonl(
            session,
            _records("main-manager", NOW - timedelta(minutes=1), progress=NOW - timedelta(seconds=5)),
        )
        seen: list[bool] = []
        original = NATIVE._parse_jsonl_envelope

        def observed(line):
            seen.append(isinstance(line, memoryview))
            return original(line)

        with patch.object(NATIVE, "_parse_jsonl_envelope", side_effect=observed):
            NATIVE.collect_native_activity(
                routes_path=self.routes,
                roots={"codex": [source]},
                now=NOW,
                process_probe=lambda *args, **kwargs: True,
                max_files=8,
                max_bytes=256 * 1024,
            )
        self.assertTrue(seen)
        self.assertTrue(all(seen))

    def test_caller_scan_bounds_have_absolute_hard_ceilings(self):
        for name, values in (
            ("max_files", {"max_files": 257, "max_bytes": 256 * 1024}),
            ("max_bytes", {"max_files": 8, "max_bytes": 16 * 1024 * 1024 + 1}),
        ):
            with self.subTest(name=name), self.assertRaises(NATIVE.NativeActivityError):
                NATIVE.collect_native_activity(
                    routes_path=self.routes,
                    roots={"codex": [self.root / "codex"]},
                    now=NOW,
                    process_probe=lambda *args, **kwargs: True,
                    **values,
                )

    def test_roots_receive_fair_scan_slots_and_only_selected_source_is_probed(self):
        codex = self.root / "codex"
        claude = self.root / "claude"
        _write_jsonl(
            codex / "manager-old.jsonl",
            _records("main-manager", NOW - timedelta(minutes=3), progress=NOW - timedelta(minutes=2)),
        )
        _write_jsonl(
            codex / "manager-new.jsonl",
            _records("main-manager", NOW - timedelta(minutes=1), progress=NOW - timedelta(seconds=20)),
        )
        _write_jsonl(
            claude / "studio.jsonl",
            _records("ai-studio", NOW - timedelta(minutes=1), progress=NOW - timedelta(seconds=10)),
        )
        calls: list[str] = []

        def probe(path: Path, **_kwargs) -> bool:
            calls.append(path.name)
            return True

        checkpoint = NATIVE.collect_native_activity(
            routes_path=self.routes,
            roots={"codex": [codex], "claude": [claude]},
            now=NOW,
            process_probe=probe,
            max_files=4,
            max_bytes=256 * 1024,
        )
        self.assertEqual(
            [
                next(agent for agent in checkpoint["agents"] if agent["route_id"] == route)["state"]
                for route in ("main-manager", "ai-studio")
            ],
            ["running", "running"],
        )
        self.assertEqual(sorted(calls), ["manager-new.jsonl", "studio.jsonl"])

    def test_newer_oversized_same_route_source_blocks_older_running_evidence(self):
        source = self.root / "codex"
        older = source / "older.jsonl"
        rejected = source / "thread-main-manager.jsonl"
        _write_jsonl(
            older,
            _records("main-manager", NOW - timedelta(minutes=2), progress=NOW - timedelta(minutes=1)),
        )
        rejected.write_bytes(b"{" + b"x" * 2048 + b"}\n")
        old_time = (NOW - timedelta(minutes=1)).timestamp()
        new_time = NOW.timestamp()
        os.utime(older, (old_time, old_time))
        os.utime(rejected, (new_time, new_time))

        checkpoint = NATIVE.collect_native_activity(
            routes_path=self.routes,
            roots={"codex": [source]},
            now=NOW,
            process_probe=lambda *args, **kwargs: True,
            max_files=8,
            max_bytes=1024,
        )
        manager = next(agent for agent in checkpoint["agents"] if agent["route_id"] == "main-manager")
        self.assertIsNone(manager["state"])
        self.assertEqual(manager["availability"], "unavailable")
        self.assertIn(manager["freshness"], {"invalid", "unavailable"})

    def test_newer_same_route_symlink_blocks_older_running_without_following_link(self):
        source = self.root / "codex"
        older = source / "older.jsonl"
        outside = self.root / "outside-private.jsonl"
        link = source / "thread-main-manager.jsonl"
        _write_jsonl(
            older,
            _records("main-manager", NOW - timedelta(minutes=2), progress=NOW - timedelta(minutes=1)),
        )
        _write_jsonl(
            outside,
            _records("main-manager", NOW - timedelta(seconds=30), progress=NOW - timedelta(seconds=10)),
        )
        link.symlink_to(outside)
        old_time = (NOW - timedelta(minutes=1)).timestamp()
        new_time = NOW.timestamp()
        os.utime(older, (old_time, old_time))
        os.utime(link, (new_time, new_time), follow_symlinks=False)

        checkpoint = NATIVE.collect_native_activity(
            routes_path=self.routes,
            roots={"codex": [source]},
            now=NOW,
            process_probe=lambda *args, **kwargs: True,
            max_files=8,
            max_bytes=1024,
        )
        manager = next(agent for agent in checkpoint["agents"] if agent["route_id"] == "main-manager")
        self.assertIsNone(manager["state"])
        self.assertEqual(manager["availability"], "unavailable")
        self.assertIn(manager["freshness"], {"invalid", "unavailable"})

    def test_newer_rejected_source_with_unknown_identity_blocks_older_running(self):
        source = self.root / "codex"
        older = source / "older.jsonl"
        rejected = source / "unmapped-newer.jsonl"
        _write_jsonl(
            older,
            _records("main-manager", NOW - timedelta(minutes=2), progress=NOW - timedelta(minutes=1)),
        )
        rejected.write_bytes(b"{" + b"private" * 300 + b"}\n")
        old_time = (NOW - timedelta(minutes=1)).timestamp()
        new_time = NOW.timestamp()
        os.utime(older, (old_time, old_time))
        os.utime(rejected, (new_time, new_time))

        checkpoint = NATIVE.collect_native_activity(
            routes_path=self.routes,
            roots={"codex": [source]},
            now=NOW,
            process_probe=lambda *args, **kwargs: True,
            max_files=8,
            max_bytes=1024,
        )
        manager = next(agent for agent in checkpoint["agents"] if agent["route_id"] == "main-manager")
        self.assertIsNone(manager["state"])
        self.assertEqual(manager["availability"], "unavailable")
        self.assertEqual(manager["freshness"], "invalid")

    def test_process_attestation_cannot_validate_a_replaced_jsonl_inode(self):
        source = self.root / "codex"
        session = source / "session.jsonl"
        _write_jsonl(
            session,
            _records("main-manager", NOW - timedelta(minutes=2), progress=NOW - timedelta(seconds=10)),
        )
        evidence: list[tuple[Path, str]] = []

        def replacing_probe(path: Path, *, source: str) -> bool:
            evidence.append((path, source))
            replacement = path.with_name("replacement.jsonl")
            _write_jsonl(
                replacement,
                _records(
                    "main-manager",
                    NOW - timedelta(minutes=1),
                    progress=NOW - timedelta(seconds=5),
                ),
            )
            os.replace(replacement, path)
            return True

        checkpoint = NATIVE.collect_native_activity(
            routes_path=self.routes,
            roots={"codex": [source]},
            now=NOW,
            process_probe=replacing_probe,
            max_files=8,
            max_bytes=256 * 1024,
        )
        manager = next(agent for agent in checkpoint["agents"] if agent["route_id"] == "main-manager")
        self.assertIsNone(manager["state"])
        self.assertEqual(manager["availability"], "unavailable")
        self.assertEqual(evidence, [(session, "codex")])

    def test_process_probe_keeps_original_strict_callback_signature(self):
        source_root = self.root / "codex"
        session = source_root / "session.jsonl"
        _write_jsonl(
            session,
            _records(
                "main-manager",
                NOW - timedelta(minutes=2),
                progress=NOW - timedelta(seconds=10),
            ),
        )
        calls: list[tuple[Path, str]] = []

        def strict_probe(candidate: Path, *, source: str) -> bool:
            calls.append((candidate, source))
            return True

        checkpoint = NATIVE.collect_native_activity(
            routes_path=self.routes,
            roots={"codex": [source_root]},
            now=NOW,
            process_probe=strict_probe,
            max_files=8,
            max_bytes=256 * 1024,
        )
        manager = next(agent for agent in checkpoint["agents"] if agent["route_id"] == "main-manager")
        self.assertEqual(manager["state"], "running")
        self.assertEqual(manager["availability"], "available")
        self.assertEqual(calls, [(session, "codex")])


class PublisherAndUiHardeningTests(unittest.TestCase):
    def test_collection_failure_publishes_explicit_safe_unavailable_lane(self):
        status = {
            "ok": True,
            "counts": {},
            "pixel_events": [],
            "human_projection": [],
        }
        output = io.StringIO()
        with (
            patch.object(PUBLISHER, "collect_native_activity", side_effect=NATIVE.NativeActivityError("private")),
            patch.object(PUBLISHER, "run_scheduler_status", return_value=status),
            redirect_stdout(output),
        ):
            result = PUBLISHER.main(["--dry-run"])
        self.assertEqual(result, 0)
        snapshot = json.loads(output.getvalue())
        self.assertEqual(snapshot["native_activity"], {})
        self.assertNotIn("private", output.getvalue())

    def test_ui_keeps_gate_as_overlay_without_resetting_native_manager(self):
        script = (BUILDER / "dashboard-assets" / "script.js").read_text(encoding="utf-8")
        self.assertIn("nativeProjects.has(event.project)", script)
        self.assertIn("agent?.route_id === 'main-manager'", script)
        self.assertIn("single agent presence", script)


if __name__ == "__main__":
    unittest.main()
