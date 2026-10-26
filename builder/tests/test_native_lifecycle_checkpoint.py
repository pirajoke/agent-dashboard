"""RED contract for exact-owner native lifecycle attestation.

Fixtures contain synthetic metadata only.  The lifecycle database deliberately
contains private sentinels so the public checkpoint boundary is exercised too.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import inspect
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from dashboard_builder import native_activity as NATIVE


NOW = datetime(2026, 10, 25, 20, 45, tzinfo=timezone.utc)
MAX_BYTES = 4096
PRIVATE_SENTINELS = (
    "PRIVATE_TURN_SENTINEL_aa71",
    "PRIVATE_ERROR_SENTINEL_aa71",
    "PRIVATE_ITEM_SENTINEL_aa71",
    "PRIVATE_PATH_SENTINEL_aa71",
    "private-child-thread-aa71",
)


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _epoch(moment: datetime) -> int:
    return int(moment.timestamp())


def _record(kind: str, at: datetime, payload: dict) -> dict:
    return {"timestamp": _iso(at), "type": kind, "payload": payload}


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        b"".join(json.dumps(record, ensure_ascii=False).encode("utf-8") + b"\n" for record in records)
    )


def _agent(checkpoint: dict, route_id: str) -> dict:
    return next(agent for agent in checkpoint["agents"] if agent["route_id"] == route_id)


def _create_thread_turns_database(path: Path, rows: list[dict]) -> sqlite3.Connection:
    """Create the reviewed native schema and leave a WAL-capable writer open."""
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA wal_autocheckpoint=0")
    connection.execute(
        """
        CREATE TABLE thread_turns (
            thread_id TEXT NOT NULL,
            turn_id TEXT NOT NULL,
            rollout_ordinal INTEGER NOT NULL,
            status TEXT NOT NULL,
            error_json TEXT,
            started_at INTEGER,
            completed_at INTEGER,
            duration_ms INTEGER,
            first_user_item_id TEXT,
            final_agent_item_id TEXT,
            rollout_byte_offset INTEGER,
            rollout_end_ordinal INTEGER,
            rollout_end_byte_offset INTEGER,
            root_turn_id TEXT,
            PRIMARY KEY (thread_id, turn_id)
        )
        """
    )
    for row in rows:
        connection.execute(
            """
            INSERT INTO thread_turns (
                thread_id, turn_id, rollout_ordinal, status, error_json,
                started_at, completed_at, duration_ms, first_user_item_id,
                final_agent_item_id, rollout_byte_offset, rollout_end_ordinal,
                rollout_end_byte_offset, root_turn_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["thread_id"],
                row.get("turn_id", PRIVATE_SENTINELS[0]),
                row.get("rollout_ordinal", 1),
                row["status"],
                row.get("error_json", PRIVATE_SENTINELS[1]),
                row.get("started_at"),
                row.get("completed_at"),
                row.get("duration_ms"),
                row.get("first_user_item_id", PRIVATE_SENTINELS[2]),
                row.get("final_agent_item_id", PRIVATE_SENTINELS[2]),
                row.get("rollout_byte_offset", 0),
                row.get("rollout_end_ordinal"),
                row.get("rollout_end_byte_offset"),
                row.get("root_turn_id", PRIVATE_SENTINELS[0]),
            ),
        )
    connection.commit()
    return connection


class NativeLifecycleCheckpointRedTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.sessions = self.root / "sessions"
        self.sessions.mkdir()
        self.routes = self.root / "agent-routes.json"
        self.routes.write_text(
            json.dumps(
                {
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
                },
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )
        self.lifecycle = self.root / "thread-history.sqlite"
        self.connections: list[sqlite3.Connection] = []

    def tearDown(self) -> None:
        for connection in self.connections:
            connection.close()

    def _database(self, rows: list[dict], *, path: Path | None = None) -> Path:
        target = path or self.lifecycle
        connection = _create_thread_turns_database(target, rows)
        self.connections.append(connection)
        return target

    def _exact_records(
        self,
        *,
        started: datetime,
        progress: datetime,
        owner: str = "thread-main-manager",
        aliases: dict | None = None,
    ) -> list[dict]:
        metadata = {"id": owner, **(aliases or {})}
        return [
            _record("session_meta", started - timedelta(seconds=1), metadata),
            _record("event_msg", started, {"type": "task_started"}),
            _record(
                "response_item",
                progress,
                {"type": "function_call", "arguments": PRIVATE_SENTINELS[3]},
            ),
        ]

    def _collect(self, lifecycle: Path, probe) -> dict:
        parameters = inspect.signature(NATIVE.collect_native_activity).parameters
        kwargs = {
            "routes_path": self.routes,
            "roots": {"codex": [self.sessions]},
            "now": NOW,
            "process_probe": probe,
            "max_files": 16,
            "max_bytes": MAX_BYTES,
        }
        # On the unmodified implementation, call the real collector without
        # invented test shims.  Positive assertions then reproduce the audited
        # false negative instead of failing in fixture setup.
        if "lifecycle_path" in parameters:
            kwargs["lifecycle_path"] = lifecycle
        return NATIVE.collect_native_activity(**kwargs)

    def _row(
        self,
        *,
        thread_id: str = "thread-main-manager",
        status: str = "inProgress",
        started_at: datetime | None = None,
        ordinal: int = 2,
        completed_at: datetime | None = None,
    ) -> dict:
        return {
            "thread_id": thread_id,
            "turn_id": f"{PRIVATE_SENTINELS[0]}-{ordinal}",
            "rollout_ordinal": ordinal,
            "status": status,
            "started_at": _epoch(started_at or (NOW - timedelta(minutes=2))),
            "completed_at": _epoch(completed_at) if completed_at else None,
        }

    def _assert_private_boundary(self, checkpoint: dict) -> None:
        rendered = json.dumps(checkpoint, ensure_ascii=False)
        for sentinel in PRIVATE_SENTINELS:
            self.assertNotIn(sentinel, rendered)
        self.assertNotIn(str(self.root), rendered)
        for agent in checkpoint["agents"]:
            self.assertEqual(set(agent), set(NATIVE.PUBLIC_AGENT_FIELDS))

    def test_collector_has_an_explicit_injectable_lifecycle_source(self) -> None:
        self.assertIn(
            "lifecycle_path",
            inspect.signature(NATIVE.collect_native_activity).parameters,
            "RED: the native collector has no exact-owner lifecycle checkpoint input",
        )

    def test_exact_owner_in_progress_and_fresh_jsonl_progress_prove_running_without_probe(self) -> None:
        started = NOW - timedelta(minutes=2)
        progress = NOW - timedelta(seconds=12)
        _write_jsonl(
            self.sessions / "exact-owner.jsonl",
            self._exact_records(started=started, progress=progress),
        )
        lifecycle = self._database(
            [
                self._row(status="completed", ordinal=1, completed_at=NOW - timedelta(minutes=4)),
                self._row(status="inProgress", ordinal=2, started_at=started),
            ]
        )
        probe_calls: list[Path] = []

        def probe(path: Path, **_kwargs) -> bool:
            probe_calls.append(path)
            return False

        checkpoint = self._collect(lifecycle, probe)
        manager = _agent(checkpoint, "main-manager")

        self.assertEqual(manager["state"], "running")
        self.assertEqual(manager["availability"], "available")
        self.assertEqual(manager["freshness"], "fresh")
        self.assertEqual(manager["state_at"], _iso(progress))
        self.assertEqual(probe_calls, [], "SQLite lifecycle proof must not invoke lsof/process proof")
        self._assert_private_boundary(checkpoint)

    def test_windowed_tail_progress_uses_fresh_in_progress_start_outside_tail(self) -> None:
        started = NOW - timedelta(minutes=3)
        progress = NOW - timedelta(seconds=8)
        path = self.sessions / "oversized-exact-owner.jsonl"
        records = [
            _record("session_meta", started - timedelta(seconds=1), {"id": "thread-main-manager"}),
            _record("event_msg", started, {"type": "task_started"}),
            _record(
                "response_item",
                started + timedelta(seconds=1),
                {"type": "message", "content": PRIVATE_SENTINELS[1] + ("x" * MAX_BYTES * 3)},
            ),
            _record("response_item", progress, {"type": "function_call", "arguments": PRIVATE_SENTINELS[3]}),
        ]
        _write_jsonl(path, records)
        self.assertGreater(path.stat().st_size, MAX_BYTES)
        lifecycle = self._database([self._row(started_at=started)])
        probe_calls: list[Path] = []

        checkpoint = self._collect(lifecycle, lambda path, **_kwargs: probe_calls.append(path) or False)
        manager = _agent(checkpoint, "main-manager")

        self.assertEqual(manager["state"], "running")
        self.assertEqual(manager["state_at"], _iso(progress))
        self.assertEqual(probe_calls, [])
        self._assert_private_boundary(checkpoint)

    def test_newer_child_or_fork_alias_never_shadows_the_exact_registered_owner(self) -> None:
        exact_progress = NOW - timedelta(seconds=20)
        child_progress = NOW - timedelta(seconds=4)
        exact = self.sessions / "exact.jsonl"
        child = self.sessions / "newer-child.jsonl"
        _write_jsonl(
            exact,
            self._exact_records(
                started=NOW - timedelta(minutes=2),
                progress=exact_progress,
            ),
        )
        _write_jsonl(
            child,
            self._exact_records(
                owner=PRIVATE_SENTINELS[4],
                aliases={"parent_thread_id": "thread-main-manager", "forked_from_id": "thread-main-manager"},
                started=NOW - timedelta(minutes=1),
                progress=child_progress,
            ),
        )
        os.utime(exact, ns=(1_000_000_000, 1_000_000_000))
        os.utime(child, ns=(2_000_000_000, 2_000_000_000))
        lifecycle = self._database([self._row(started_at=NOW - timedelta(minutes=2))])

        checkpoint = self._collect(
            lifecycle,
            lambda *_args, **_kwargs: self.fail("exact lifecycle proof must not invoke process probe"),
        )
        manager = _agent(checkpoint, "main-manager")

        self.assertEqual(manager["state"], "running")
        self.assertEqual(
            manager["state_at"],
            _iso(exact_progress),
            "a child/fork alias is not authority for the registered owner route",
        )
        self._assert_private_boundary(checkpoint)

    def test_live_wal_read_uses_one_committed_snapshot_and_exports_only_public_fields(self) -> None:
        progress = NOW - timedelta(seconds=10)
        _write_jsonl(
            self.sessions / "wal-owner.jsonl",
            self._exact_records(started=NOW - timedelta(minutes=2), progress=progress),
        )
        lifecycle = self._database([self._row(started_at=NOW - timedelta(minutes=2))])
        writer = self.connections[-1]
        writer.execute(
            "UPDATE thread_turns SET status = ?, completed_at = ? WHERE thread_id = ?",
            ("completed", _epoch(NOW - timedelta(seconds=1)), "thread-main-manager"),
        )
        # The writer remains uncommitted.  A bounded reader must see the one
        # previously committed WAL snapshot, never a dirty mix of both states.
        checkpoint = self._collect(
            lifecycle,
            lambda *_args, **_kwargs: self.fail("committed lifecycle proof must not invoke process probe"),
        )
        writer.rollback()

        manager = _agent(checkpoint, "main-manager")
        self.assertEqual(manager["state"], "running")
        self.assertEqual(manager["state_at"], _iso(progress))
        self._assert_private_boundary(checkpoint)

    def test_lifecycle_sqlite_read_installs_deadline_before_queries_and_interrupts_closed(self) -> None:
        lifecycle = self._database([self._row(started_at=NOW - timedelta(minutes=2))])
        real_connect = sqlite3.connect
        events: list[tuple[str, object]] = []

        class InterruptingConnection:
            def __init__(self, connection: sqlite3.Connection):
                self.connection = connection
                self.progress_handler = None

            def __getattr__(self, name: str):
                return getattr(self.connection, name)

            def set_progress_handler(self, callback, instruction_count: int):
                events.append(("handler", instruction_count))
                self.progress_handler = callback
                return self.connection.set_progress_handler(callback, instruction_count)

            def execute(self, statement: str, parameters=()):
                normalized = " ".join(statement.split()).upper()
                query_kind = None
                if normalized.startswith("PRAGMA TABLE_INFO(THREAD_TURNS)"):
                    query_kind = "schema"
                elif "FROM THREAD_TURNS AS CURRENT" in normalized:
                    query_kind = "data"
                if query_kind is not None:
                    events.append(("query", query_kind))
                    if self.progress_handler is not None:
                        interrupted = self.progress_handler()
                        events.append(("interrupt", interrupted))
                        if interrupted:
                            raise sqlite3.OperationalError("interrupted")
                return self.connection.execute(statement, parameters)

        def observed_connect(*args, **kwargs):
            return InterruptingConnection(real_connect(*args, **kwargs))

        clock_calls = 0

        def expired_clock() -> float:
            nonlocal clock_calls
            clock_calls += 1
            return 100.0 if clock_calls == 1 else 10_000.0

        with (
            patch.object(NATIVE.sqlite3, "connect", side_effect=observed_connect),
            patch.object(NATIVE.time, "monotonic", side_effect=expired_clock),
        ):
            snapshot = NATIVE._read_lifecycle_snapshot(
                lifecycle,
                thread_routes={f"thread-{route_id}": route_id for route_id, *_ in NATIVE.ROUTE_CONTRACT},
            )

        self.assertTrue(events, "the lifecycle reader must execute a bounded SQLite operation")
        self.assertEqual(
            events[0][0],
            "handler",
            "the progress deadline must be installed before schema or data SQL",
        )
        self.assertIsInstance(events[0][1], int)
        self.assertGreater(events[0][1], 0)
        self.assertIn(("query", "schema"), events)
        self.assertIn(("interrupt", 1), events)
        self.assertIsNone(snapshot, "an interrupted lifecycle snapshot must fail closed")

    def test_lifecycle_source_changed_after_read_fails_closed_before_projection(self) -> None:
        started = NOW - timedelta(minutes=2)
        progress = NOW - timedelta(seconds=10)
        session = self.sessions / "changed-after-read.jsonl"
        _write_jsonl(session, self._exact_records(started=started, progress=progress))
        lifecycle = self._database([self._row(started_at=started)])
        original_read = NATIVE._read_source_window
        appended = False

        def append_after_read(path: Path, limit: int, bytes_read: list[int]):
            nonlocal appended
            opened = original_read(path, limit, bytes_read)
            if path == session and not appended:
                appended = True
                with path.open("ab") as handle:
                    handle.write(
                        json.dumps(
                            _record(
                                "event_msg",
                                NOW,
                                {"type": "task_complete", "message": PRIVATE_SENTINELS[1]},
                            )
                        ).encode("utf-8")
                        + b"\n"
                    )
            return opened

        with patch.object(NATIVE, "_read_source_window", side_effect=append_after_read):
            checkpoint = self._collect(
                lifecycle,
                lambda *_args, **_kwargs: self.fail(
                    "lifecycle mode must not use process proof after source mutation"
                ),
            )

        manager = _agent(checkpoint, "main-manager")
        self.assertTrue(appended)
        self.assertIsNone(
            manager["state"],
            "a completion appended after the bounded read invalidates the earlier running snapshot",
        )
        self.assertNotEqual(manager["availability"], "available")
        self.assertEqual(manager["freshness"], "invalid")
        self._assert_private_boundary(checkpoint)

    def test_progress_appended_during_scan_uses_safe_finish_boundary_not_scan_start(self) -> None:
        started = NOW - timedelta(minutes=2)
        initial_progress = NOW - timedelta(seconds=1)
        appended_progress = NOW + timedelta(seconds=2)
        session = self.sessions / "scan-race-owner.jsonl"
        _write_jsonl(
            session,
            self._exact_records(started=started, progress=initial_progress),
        )
        lifecycle = self._database([self._row(started_at=started)])
        original_read = NATIVE._read_source_window
        appended = False

        def append_after_scan_started(path: Path, limit: int, bytes_read: list[int]):
            nonlocal appended
            if path == session and not appended:
                appended = True
                with path.open("ab") as handle:
                    handle.write(
                        json.dumps(
                            _record(
                                "response_item",
                                appended_progress,
                                {"type": "function_call_output", "output": PRIVATE_SENTINELS[1]},
                            )
                        ).encode("utf-8")
                        + b"\n"
                    )
            return original_read(path, limit, bytes_read)

        monotonic_calls = 0

        def monotonic() -> float:
            nonlocal monotonic_calls
            monotonic_calls += 1
            return 100.0 if monotonic_calls == 1 else 103.0

        with (
            patch.object(NATIVE, "_read_source_window", side_effect=append_after_scan_started),
            patch.object(NATIVE.time, "monotonic", side_effect=monotonic),
        ):
            checkpoint = self._collect(
                lifecycle,
                lambda *_args, **_kwargs: self.fail(
                    "exact lifecycle proof must not invoke process probe"
                ),
            )

        manager = _agent(checkpoint, "main-manager")
        self.assertTrue(appended)
        self.assertEqual(
            (manager["state"], manager["state_at"], checkpoint["observed_at"]),
            ("running", _iso(appended_progress), _iso(NOW + timedelta(seconds=3))),
            "a record written inside the bounded scan must be compared with scan finish, not scan start",
        )
        self._assert_private_boundary(checkpoint)

    def test_untrusted_lifecycle_variants_fail_closed_without_process_fallback(self) -> None:
        progress = NOW - timedelta(seconds=10)
        _write_jsonl(
            self.sessions / "otherwise-running.jsonl",
            self._exact_records(started=NOW - timedelta(minutes=2), progress=progress),
        )

        cases: dict[str, Path] = {}
        cases["missing"] = self.root / "missing.sqlite"

        corrupt = self.root / "corrupt.sqlite"
        corrupt.write_bytes(b"not sqlite " + PRIVATE_SENTINELS[1].encode("utf-8"))
        cases["corrupt"] = corrupt

        wrong_schema = self.root / "wrong-schema.sqlite"
        with sqlite3.connect(wrong_schema) as connection:
            connection.execute("CREATE TABLE private_turns (private_body TEXT)")
            connection.execute("INSERT INTO private_turns VALUES (?)", (PRIVATE_SENTINELS[1],))
        cases["wrong_schema"] = wrong_schema

        cases["future"] = self._database(
            [self._row(started_at=NOW + timedelta(minutes=1))],
            path=self.root / "future.sqlite",
        )
        cases["stale"] = self._database(
            [self._row(started_at=NOW - timedelta(minutes=6))],
            path=self.root / "stale.sqlite",
        )
        cases["disagreeing_completed"] = self._database(
            [
                self._row(
                    status="completed",
                    started_at=NOW - timedelta(minutes=2),
                    completed_at=NOW - timedelta(seconds=30),
                )
            ],
            path=self.root / "completed.sqlite",
        )
        cases["unknown_status"] = self._database(
            [self._row(status="paused")],
            path=self.root / "unknown.sqlite",
        )
        cases["missing_exact_owner"] = self._database(
            [self._row(thread_id=PRIVATE_SENTINELS[4])],
            path=self.root / "child-only.sqlite",
        )
        real = self._database(
            [self._row()],
            path=self.root / "real.sqlite",
        )
        symlink = self.root / "linked.sqlite"
        symlink.symlink_to(real)
        cases["symlink"] = symlink

        for name, lifecycle in cases.items():
            with self.subTest(name=name):
                probe_calls: list[Path] = []
                checkpoint = self._collect(
                    lifecycle,
                    lambda path, **_kwargs: probe_calls.append(path) or True,
                )
                manager = _agent(checkpoint, "main-manager")
                self.assertIsNone(manager["state"])
                self.assertNotEqual(manager["availability"], "available")
                self.assertEqual(
                    probe_calls,
                    [],
                    "invalid lifecycle evidence must fail closed, not fall back to lsof",
                )
                self._assert_private_boundary(checkpoint)


if __name__ == "__main__":
    unittest.main()
