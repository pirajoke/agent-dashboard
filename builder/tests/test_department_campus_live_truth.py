from __future__ import annotations

from datetime import datetime, timedelta, timezone
import importlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import tempfile
import time
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

    def _pipeline_process_fixture(
        self,
        root: Path,
        *,
        fake_claude_source: str,
        run_id: str,
    ) -> tuple[dict[str, str], Path, Path, Path]:
        home = root / "home"
        scripts = home / "scripts"
        report_dir = home / "reports"
        project_dir = home / "project"
        scripts.mkdir(parents=True)
        report_dir.mkdir()
        project_dir.mkdir()
        child_pid_path = home / "provider-child.pid"
        event_log = home / "pixel-events.log"

        fake_pixel = scripts / "jarvis-pixel-agent-event"
        fake_pixel.write_text(
            """#!/bin/sh
alive=no
if [ "${1:-}" = done ] && [ -s "$FAKE_PROVIDER_CHILD_PID" ]; then
  child_pid="$(cat "$FAKE_PROVIDER_CHILD_PID")"
  if kill -0 "$child_pid" 2>/dev/null; then alive=yes; fi
fi
printf '%s|%s|child_alive=%s\n' "${1:-}" "${2:-}" "$alive" >> "$FAKE_PIXEL_LOG"
""",
            encoding="utf-8",
        )
        fake_pixel.chmod(0o755)

        fake_claude = home / "fake-claude.py"
        fake_claude.write_text(fake_claude_source, encoding="utf-8")
        fake_claude.chmod(0o755)

        environment = os.environ.copy()
        environment.update(
            {
                "HOME": str(home),
                "JARVIS_AGENT_ENV_FILE": str(home / "missing.env"),
                "JARVIS_PROJECT_DIR": str(project_dir),
                "JARVIS_PROJECT_NAME": "PIXELVERSE DASHBOARD",
                "JARVIS_AGENT_REPORT_DIR": str(report_dir),
                "JARVIS_AGENT_RUN_ID": run_id,
                "JARVIS_AGENT_PROVIDER": "claude",
                "JARVIS_CLAUDE_BIN": str(fake_claude),
                "JARVIS_AGENT_SELF_HEAL_ENABLED": "0",
                "JARVIS_OMNI_APPROVAL_ENABLED": "0",
                "JARVIS_PIXEL_HEARTBEAT_INTERVAL_SECONDS": "5",
                "FAKE_PROVIDER_CHILD_PID": str(child_pid_path),
                "FAKE_PIXEL_LOG": str(event_log),
            }
        )
        return environment, child_pid_path, event_log, report_dir

    def _wait_for_path(self, file_path: Path, timeout: float = 8) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and not file_path.is_file():
            time.sleep(0.02)
        self.assertTrue(file_path.is_file(), f"timed out waiting for {file_path.name}")

    def _stop_pipeline_process(self, process: subprocess.Popen) -> None:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            pass
        if process.stdout is not None:
            process.stdout.close()
        if process.stderr is not None:
            process.stderr.close()

    def _stop_recorded_provider_group(self, child_pid_path: Path) -> None:
        if not child_pid_path.is_file():
            return
        try:
            child_pid = int(child_pid_path.read_text(encoding="utf-8"))
            provider_group = os.getpgid(child_pid)
            if provider_group != os.getpgrp():
                os.killpg(provider_group, signal.SIGKILL)
            else:
                os.kill(child_pid, signal.SIGKILL)
        except (OSError, ProcessLookupError, ValueError):
            pass

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

            bundled_node = (
                Path.home() / ".local/node-v22.22.3-darwin-arm64/bin/node"
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

    def test_ac_6_ec_3_two_independent_heartbeat_writers_preserve_both_agents(self):
        bundled_node = Path.home() / ".local/node-v22.22.3-darwin-arm64/bin/node"
        node = shutil.which("node") or (
            str(bundled_node) if bundled_node.is_file() else None
        )
        self.assertIsNotNone(
            node,
            "RED environment: Node is required to execute the producer contract",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir)
            details_path = home / ".pixel-agents" / "jarvis-agent-details.json"
            details_path.parent.mkdir(parents=True)
            old_heartbeat = "2026-08-18T05:50:00.000Z"
            details_path.write_text(
                json.dumps(
                    {
                        "updatedAt": old_heartbeat,
                        "agents": {
                            "designer": {
                                "role": "designer",
                                "state": "working",
                                "project": "PIXELVERSE DASHBOARD",
                                "agentId": "DESIGNER",
                                "runId": "run-designer",
                                "sessionId": "session-designer",
                                "heartbeatAt": old_heartbeat,
                            },
                            "infrastructure": {
                                "role": "infrastructure",
                                "state": "working",
                                "project": "JARVIS",
                                "agentId": "INFRASTRUCTURE",
                                "runId": "run-infrastructure",
                                "sessionId": "session-infrastructure",
                                "heartbeatAt": old_heartbeat,
                            },
                        },
                    }
                ),
                encoding="utf-8",
            )

            # Force both unprotected writers to finish their read before either
            # can write. A correct inter-process lock serializes the reads; the
            # first writer's bounded barrier then expires and releases the lock.
            barrier_dir = home / "race-barrier"
            barrier_dir.mkdir()
            preload = home / "race-read-barrier.mjs"
            preload.write_text(
                """
import fs from 'node:fs';
import path from 'node:path';

const originalRead = fs.readFileSync.bind(fs);
const sleeper = new Int32Array(new SharedArrayBuffer(4));
fs.readFileSync = function (filePath, ...args) {
  const value = originalRead(filePath, ...args);
  if (path.resolve(String(filePath)) !== path.resolve(process.env.RACE_DETAILS_PATH)) {
    return value;
  }
  fs.writeFileSync(path.join(process.env.RACE_BARRIER_DIR, process.env.RACE_MARKER), 'read');
  const deadline = Date.now() + 600;
  while (Date.now() < deadline) {
    if (fs.readdirSync(process.env.RACE_BARRIER_DIR).length >= 2) break;
    Atomics.wait(sleeper, 0, 0, 5);
  }
  return value;
};
""".strip(),
                encoding="utf-8",
            )

            processes = []
            identities = (
                (
                    "designer",
                    "PIXELVERSE DASHBOARD",
                    "DESIGNER",
                    "run-designer",
                    "session-designer",
                ),
                (
                    "infrastructure",
                    "JARVIS",
                    "INFRASTRUCTURE",
                    "run-infrastructure",
                    "session-infrastructure",
                ),
            )
            for role, project, agent_id, run_id, session_id in identities:
                environment = os.environ.copy()
                environment.update(
                    {
                        "HOME": str(home),
                        "NODE_OPTIONS": f"--import={preload}",
                        "RACE_DETAILS_PATH": str(details_path),
                        "RACE_BARRIER_DIR": str(barrier_dir),
                        "RACE_MARKER": role,
                        "JARVIS_PIXEL_PROJECT_NAME": project,
                        "JARVIS_PIXEL_AGENT_ID": agent_id,
                        "JARVIS_PIXEL_RUN_ID": run_id,
                        "JARVIS_PIXEL_SESSION_ID": session_id,
                    }
                )
                processes.append(
                    subprocess.Popen(
                        [node, str(PIXEL_EVENT_PATH), "heartbeat", role],
                        text=True,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        env=environment,
                    )
                )

            results = [process.communicate(timeout=5) for process in processes]
            for process, (_, stderr) in zip(processes, results):
                self.assertEqual(process.returncode, 0, stderr)

            after = json.loads(details_path.read_text(encoding="utf-8"))
            self.assertEqual(set(after["agents"]), {"designer", "infrastructure"})
            for role in ("designer", "infrastructure"):
                with self.subTest(role=role):
                    self.assertNotEqual(
                        after["agents"][role]["heartbeatAt"],
                        old_heartbeat,
                        "one concurrent read-modify-write discarded the other agent",
                    )

    def test_ac_6_abandoned_lock_is_bounded_and_never_loses_existing_agents(self):
        producer = PIXEL_EVENT_PATH.read_text(encoding="utf-8")
        self.assertIn("lock", producer.lower(), "producer has no lock contract")
        self.assertIsNotNone(
            re.search(r"(?:['\"]wx['\"]|O_EXCL|mkdirSync)", producer),
            "producer lock acquisition is not exclusive",
        )
        self.assertIsNotNone(
            re.search(r"(?i)(?:deadline|timeout|maxWait|lockWait)", producer),
            "producer lock acquisition is not bounded",
        )
        self.assertIsNotNone(
            re.search(r"(?s)finally.*(?:unlinkSync|rmdirSync|rmSync)", producer),
            "producer lock release is not guaranteed",
        )

    def test_ac_6_stale_recovery_never_removes_a_concurrent_replacement_lock(self):
        bundled_node = Path.home() / ".local/node-v22.22.3-darwin-arm64/bin/node"
        node = shutil.which("node") or (
            str(bundled_node) if bundled_node.is_file() else None
        )
        self.assertIsNotNone(node, "Node is required for stale-lock recovery smoke")

        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir)
            details_path = home / ".pixel-agents" / "jarvis-agent-details.json"
            lock_path = Path(f"{details_path}.lock")
            details_path.parent.mkdir(parents=True)
            original_heartbeat = "2026-08-18T05:50:00.000Z"
            before = {
                "updatedAt": original_heartbeat,
                "agents": {
                    "designer": {
                        "role": "designer",
                        "state": "working",
                        "project": "PIXELVERSE DASHBOARD",
                        "agentId": "DESIGNER",
                        "runId": "run-designer",
                        "sessionId": "session-designer",
                        "heartbeatAt": original_heartbeat,
                    }
                },
            }
            details_path.write_text(
                json.dumps(before),
                encoding="utf-8",
            )
            lock_path.mkdir()
            (lock_path / "owner.json").write_text(
                json.dumps({"pid": 2_000_000_000, "token": "stale-owner"}),
                encoding="utf-8",
            )
            stale_time = time.time() - 30
            os.utime(lock_path, (stale_time, stale_time))

            swap_marker = home / "replacement-installed"
            preload = home / "swap-before-recursive-remove.mjs"
            preload.write_text(
                """
import fs from 'node:fs';
import path from 'node:path';

const originalRm = fs.rmSync.bind(fs);
let swapped = false;
fs.rmSync = function (target, ...args) {
  if (!swapped && path.resolve(String(target)) === path.resolve(process.env.RACE_LOCK_PATH)) {
    swapped = true;
    fs.renameSync(process.env.RACE_LOCK_PATH, `${process.env.RACE_LOCK_PATH}.displaced`);
    fs.mkdirSync(process.env.RACE_LOCK_PATH);
    fs.writeFileSync(
      path.join(process.env.RACE_LOCK_PATH, 'owner.json'),
      JSON.stringify({pid: Number(process.env.RACE_REPLACEMENT_PID), token: 'replacement-owner'}),
    );
    fs.writeFileSync(process.env.RACE_SWAP_MARKER, 'installed');
  }
  return originalRm(target, ...args);
};
""".strip(),
                encoding="utf-8",
            )
            environment = os.environ.copy()
            environment.update(
                {
                    "HOME": str(home),
                    "NODE_OPTIONS": f"--import={preload}",
                    "RACE_LOCK_PATH": str(lock_path),
                    "RACE_SWAP_MARKER": str(swap_marker),
                    "RACE_REPLACEMENT_PID": str(os.getpid()),
                    "JARVIS_PIXEL_PROJECT_NAME": "PIXELVERSE DASHBOARD",
                    "JARVIS_PIXEL_AGENT_ID": "DESIGNER",
                    "JARVIS_PIXEL_RUN_ID": "run-designer",
                    "JARVIS_PIXEL_SESSION_ID": "session-designer",
                }
            )
            result = subprocess.run(
                [node, str(PIXEL_EVENT_PATH), "heartbeat", "designer"],
                text=True,
                capture_output=True,
                env=environment,
                timeout=6,
                check=False,
            )

            after = json.loads(details_path.read_text(encoding="utf-8"))
            if swap_marker.is_file():
                self.assertTrue(
                    lock_path.is_dir(),
                    "stale recovery recursively deleted the concurrently replaced lock",
                )
                replacement = json.loads(
                    (lock_path / "owner.json").read_text(encoding="utf-8")
                )
                self.assertEqual(replacement["token"], "replacement-owner")
            elif result.returncode == 0:
                self.assertNotEqual(
                    after["agents"]["designer"]["heartbeatAt"],
                    original_heartbeat,
                    "safe stale-lock recovery returned success without the heartbeat",
                )
            else:
                self.assertEqual(
                    after,
                    before,
                    "bounded fail-closed recovery partially changed heartbeat storage",
                )

    def test_ac_7_pipeline_declares_process_group_cleanup_contract(self):
        pipeline = PIPELINE_PATH.read_text(encoding="utf-8")
        for pattern, message in (
            (r"ACTIVE_PROVIDER_(?:PGID|PROCESS_GROUP)", "provider group is not tracked"),
            (r"kill[^\n]*(?:PGID|PROCESS_GROUP)", "provider group is not terminated"),
            (
                r"wait[^\n]*(?:PGID|PROCESS_GROUP|ACTIVE_PROVIDER)",
                "provider group cleanup is not waited",
            ),
        ):
            with self.subTest(pattern=pattern):
                self.assertIsNotNone(re.search(pattern, pipeline), message)

    @unittest.skipUnless(shutil.which("zsh"), "zsh is required for process-tree smoke")
    def test_ac_7_ec_4_signal_waits_for_provider_process_group_before_done(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir)
            scripts = home / "scripts"
            report_dir = home / "reports"
            project_dir = home / "project"
            scripts.mkdir()
            report_dir.mkdir()
            project_dir.mkdir()
            child_pid_path = home / "provider-child.pid"
            event_log = home / "pixel-events.log"

            fake_pixel = scripts / "jarvis-pixel-agent-event"
            fake_pixel.write_text(
                """#!/bin/sh
alive=no
if [ "${1:-}" = done ] && [ -s "$FAKE_PROVIDER_CHILD_PID" ]; then
  child_pid="$(cat "$FAKE_PROVIDER_CHILD_PID")"
  if kill -0 "$child_pid" 2>/dev/null; then alive=yes; fi
fi
printf '%s|%s|child_alive=%s\n' "${1:-}" "${2:-}" "$alive" >> "$FAKE_PIXEL_LOG"
""",
                encoding="utf-8",
            )
            fake_pixel.chmod(0o755)

            fake_claude = home / "fake-claude.py"
            fake_claude.write_text(
                """#!/usr/bin/env python3
import os
import subprocess
import sys

child = subprocess.Popen([
    sys.executable,
    '-c',
    'import os, time; open(os.environ["FAKE_PROVIDER_CHILD_PID"], "w").write(str(os.getpid())); time.sleep(60)',
])
child.wait()
print('provider complete')
""",
                encoding="utf-8",
            )
            fake_claude.chmod(0o755)

            environment = os.environ.copy()
            environment.update(
                {
                    "HOME": str(home),
                    "JARVIS_AGENT_ENV_FILE": str(home / "missing.env"),
                    "JARVIS_PROJECT_DIR": str(project_dir),
                    "JARVIS_PROJECT_NAME": "PIXELVERSE DASHBOARD",
                    "JARVIS_AGENT_REPORT_DIR": str(report_dir),
                    "JARVIS_AGENT_RUN_ID": "signal-cleanup-red",
                    "JARVIS_AGENT_PROVIDER": "claude",
                    "JARVIS_CLAUDE_BIN": str(fake_claude),
                    "JARVIS_AGENT_SELF_HEAL_ENABLED": "0",
                    "JARVIS_OMNI_APPROVAL_ENABLED": "0",
                    "JARVIS_PIXEL_HEARTBEAT_INTERVAL_SECONDS": "5",
                    "FAKE_PROVIDER_CHILD_PID": str(child_pid_path),
                    "FAKE_PIXEL_LOG": str(event_log),
                }
            )
            process = subprocess.Popen(
                ["zsh", str(PIPELINE_PATH), "исправь конкретную ошибку dashboard"],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=environment,
                start_new_session=True,
            )
            try:
                deadline = time.monotonic() + 8
                while time.monotonic() < deadline and not child_pid_path.is_file():
                    if process.poll() is not None:
                        break
                    time.sleep(0.02)
                self.assertTrue(
                    child_pid_path.is_file(),
                    "fake provider descendant never started",
                )

                process.send_signal(signal.SIGTERM)
                process.wait(timeout=8)

                events = event_log.read_text(encoding="utf-8")
                terminal_events = [
                    line for line in events.splitlines() if line.startswith("done|")
                ]
                self.assertTrue(terminal_events, events)
                self.assertTrue(
                    all("child_alive=no" in line for line in terminal_events),
                    "terminal Pixel done was emitted while provider work survived",
                )
                self.assertEqual(
                    list(report_dir.glob(".provider-output.*")),
                    [],
                    "interrupted provider output must not remain on disk",
                )
            finally:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    pass
                if process.stdout is not None:
                    process.stdout.close()
                if process.stderr is not None:
                    process.stderr.close()

    @unittest.skipUnless(shutil.which("zsh"), "zsh is required for process-tree smoke")
    def test_ac_7_early_signal_after_spawn_cannot_escape_unregistered_provider(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            environment, child_pid_path, event_log, report_dir = (
                self._pipeline_process_fixture(
                    root,
                    run_id="early-signal-red",
                    fake_claude_source="""#!/usr/bin/env python3
import os, subprocess, sys
child = subprocess.Popen([
    sys.executable, '-c',
    'import os, time; open(os.environ["FAKE_PROVIDER_CHILD_PID"], "w").write(str(os.getpid())); time.sleep(60)',
])
child.wait()
""",
                )
            )
            spawn_marker = root / "spawned-before-registration"
            environment["EARLY_PROVIDER_SPAWN_FILE"] = str(spawn_marker)
            source = PIPELINE_PATH.read_text(encoding="utf-8")
            needle = '      zsh "$PIPELINE_SCRIPT" "$TASK" > "$provider_output" 2>&1 &\n  ACTIVE_PROVIDER_PID=$!'
            injected = (
                '      zsh "$PIPELINE_SCRIPT" "$TASK" > "$provider_output" 2>&1 &\n'
                '  while [[ ! -s "$FAKE_PROVIDER_CHILD_PID" ]]; do sleep 0.01; done\n'
                '  print -rn -- "$!" > "$EARLY_PROVIDER_SPAWN_FILE"\n'
                '  sleep 5\n'
                '  ACTIVE_PROVIDER_PID=$!'
            )
            self.assertEqual(source.count(needle), 1, "provider spawn seam changed")
            test_pipeline = root / "jarvis-agent-pipeline-early-signal"
            test_pipeline.write_text(source.replace(needle, injected), encoding="utf-8")
            test_pipeline.chmod(0o755)

            process = subprocess.Popen(
                ["zsh", str(test_pipeline), "исправь конкретную ошибку dashboard"],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=environment,
                start_new_session=True,
            )
            try:
                self._wait_for_path(spawn_marker)
                process.send_signal(signal.SIGTERM)
                process.wait(timeout=8)
                events = event_log.read_text(encoding="utf-8")
                terminal_events = [
                    line for line in events.splitlines() if line.startswith("done|")
                ]
                self.assertTrue(terminal_events, events)
                self.assertTrue(
                    all("child_alive=no" in line for line in terminal_events),
                    "signal landed before provider PID/group registration and work escaped",
                )
                self.assertEqual(list(report_dir.glob(".provider-*")), [])
            finally:
                self._stop_recorded_provider_group(child_pid_path)
                self._stop_pipeline_process(process)

    @unittest.skipUnless(shutil.which("zsh"), "zsh is required for process-tree smoke")
    def test_ac_7_normal_leader_exit_cannot_leave_descendant_live_before_done(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            environment, child_pid_path, event_log, _ = self._pipeline_process_fixture(
                root,
                run_id="leader-exit-red",
                fake_claude_source="""#!/usr/bin/env python3
import os, subprocess, sys, time
subprocess.Popen([
    sys.executable, '-c',
    'import os, time; open(os.environ["FAKE_PROVIDER_CHILD_PID"], "w").write(str(os.getpid())); time.sleep(60)',
], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
deadline = time.monotonic() + 3
while time.monotonic() < deadline and not os.path.exists(os.environ['FAKE_PROVIDER_CHILD_PID']):
    time.sleep(0.01)
print('provider leader exited normally')
""",
            )
            process = subprocess.Popen(
                ["zsh", str(PIPELINE_PATH), "исправь конкретную ошибку dashboard"],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=environment,
                start_new_session=True,
            )
            try:
                self._wait_for_path(child_pid_path)
                deadline = time.monotonic() + 8
                terminal_events = []
                while time.monotonic() < deadline:
                    if event_log.is_file():
                        terminal_events = [
                            line
                            for line in event_log.read_text(encoding="utf-8").splitlines()
                            if line.startswith("done|")
                        ]
                    if terminal_events:
                        break
                    time.sleep(0.02)
                self.assertTrue(terminal_events, "pipeline never emitted terminal done")
                self.assertIn(
                    "child_alive=no",
                    terminal_events[0],
                    "provider leader exited but its working descendant survived done",
                )
            finally:
                self._stop_recorded_provider_group(child_pid_path)
                self._stop_pipeline_process(process)

    @unittest.skipUnless(shutil.which("zsh"), "zsh is required for process-tree smoke")
    def test_ac_7_cleanup_confirms_group_disappearance_after_kill_before_done(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            environment, child_pid_path, event_log, _ = self._pipeline_process_fixture(
                root,
                run_id="post-kill-red",
                fake_claude_source="""#!/usr/bin/env python3
import os, subprocess, sys
child = subprocess.Popen([
    sys.executable, '-c',
    'import os, signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); open(os.environ["FAKE_PROVIDER_CHILD_PID"], "w").write(str(os.getpid())); time.sleep(60)',
])
child.wait()
""",
            )
            source = PIPELINE_PATH.read_text(encoding="utf-8")
            seam = "unsetopt BG_NICE\n"
            delayed_kill = """unsetopt BG_NICE
kill() {
  if [[ "${1:-}" == "-KILL" ]]; then
    ( sleep 1; command kill "$@" ) &
    return 0
  fi
  command kill "$@"
}
"""
            self.assertEqual(source.count(seam), 1, "kill seam changed")
            test_pipeline = root / "jarvis-agent-pipeline-delayed-kill"
            test_pipeline.write_text(
                source.replace(seam, delayed_kill), encoding="utf-8"
            )
            test_pipeline.chmod(0o755)
            process = subprocess.Popen(
                ["zsh", str(test_pipeline), "исправь конкретную ошибку dashboard"],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=environment,
                start_new_session=True,
            )
            try:
                self._wait_for_path(child_pid_path)
                process.send_signal(signal.SIGTERM)
                process.wait(timeout=10)
                events = event_log.read_text(encoding="utf-8")
                terminal_events = [
                    line for line in events.splitlines() if line.startswith("done|")
                ]
                self.assertTrue(terminal_events, events)
                self.assertTrue(
                    all("child_alive=no" in line for line in terminal_events),
                    "cleanup emitted done before delayed KILL removed the group",
                )
            finally:
                self._stop_recorded_provider_group(child_pid_path)
                self._stop_pipeline_process(process)


if __name__ == "__main__":
    unittest.main()
