"""Synthetic metadata only; bounded large-file identity/lifecycle contract."""
from contextlib import ExitStack, contextmanager
from datetime import datetime, timedelta, timezone
import builtins
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.environ.get("NATIVE_COLLECTOR_BUILDER", str(Path(__file__).resolve().parents[1])))
from dashboard_builder import native_activity as NATIVE

NOW = datetime(2026, 10, 25, 20, 0, tzinfo=timezone.utc)
BUDGET = 4096
SENTINEL = "PRIVATE_BODY_MUST_NOT_ESCAPE"


def record(kind, seconds, payload):
    return {"timestamp": (NOW - timedelta(seconds=seconds)).isoformat(), "type": kind, "payload": payload}


def encode(records):
    return b"".join(json.dumps(row).encode() + b"\n" for row in records)


def turn(route="main-manager", *, progress="function_call"):
    return [
        record("event_msg", 30, {"type": "task_started"}),
        record("response_item", 10, {"type": progress, "arguments": SENTINEL}),
    ]


@contextmanager
def read_meter(path, after_read=None):
    """Count actual bytes read from the source inode through standard file APIs."""
    identity = (path.stat().st_dev, path.stat().st_ino)
    counts = {"bytes": 0, "mutated": False}

    def relevant(fd):
        try:
            value = os.fstat(fd)
            return (value.st_dev, value.st_ino) == identity
        except (OSError, ValueError):
            return False

    def observed(fd, value):
        if relevant(fd):
            counts["bytes"] += len(value)
            if after_read and not counts["mutated"]:
                counts["mutated"] = True
                after_read()
        return value

    class Reader:
        _red_meter = True
        def __init__(self, raw):
            self.raw = raw
        def __getattr__(self, name):
            return getattr(self.raw, name)
        def __enter__(self):
            self.raw.__enter__()
            return self
        def __exit__(self, *args):
            return self.raw.__exit__(*args)
        def read(self, *args):
            return observed(self.raw.fileno(), self.raw.read(*args))
        def readline(self, *args):
            return observed(self.raw.fileno(), self.raw.readline(*args))
        def readinto(self, buffer):
            count = self.raw.readinto(buffer)
            observed(self.raw.fileno(), memoryview(buffer)[:count])
            return count
        def __iter__(self):
            return self
        def __next__(self):
            value = self.readline()
            if not value:
                raise StopIteration
            return value

    def opener(original):
        def wrapped(*args, **kwargs):
            result = original(*args, **kwargs)
            if not getattr(result, "_red_meter", False) and relevant(result.fileno()):
                return Reader(result)
            return result
        return wrapped

    original_read, original_pread = os.read, os.pread
    with ExitStack() as stack:
        for owner, name in ((builtins, "open"), (io, "open"), (os, "fdopen")):
            stack.enter_context(patch.object(owner, name, opener(getattr(owner, name))))
        stack.enter_context(patch.object(os, "read", lambda fd, count: observed(fd, original_read(fd, count))))
        stack.enter_context(patch.object(os, "pread", lambda fd, count, offset: observed(fd, original_pread(fd, count, offset))))
        yield counts


class BoundedNativeCollectorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.sessions = self.root / "sessions"
        self.sessions.mkdir()
        self.routes = self.root / "routes.json"
        self.routes.write_text(json.dumps({
            "schema": NATIVE.ROUTE_SCHEMA, "version": 1,
            "routes": {route_id: {
                "hostId": "local", "threadId": "thread-" + route_id,
                "project": project, "repository": "owner/repo", "departmentId": department,
                "zoneId": "zone-" + department, "agentRole": role, "enabled": True,
            } for route_id, project, department, role in NATIVE.ROUTE_CONTRACT},
        }))

    def source(self, name="rollout-current.jsonl", *, owner="main-manager", tail=None, large=True):
        path = self.sessions / name
        header = record("session_meta", 3600, {"id": "thread-" + owner})
        body = record("response_item", 3500, {"type": "message", "content": SENTINEL + "x" * BUDGET * 16})
        records = [header] + ([body] if large else []) + (turn() if tail is None else tail)
        path.write_bytes(encode(records))
        return path

    def collect(self, probe=lambda *args, **kwargs: True):
        result = NATIVE.collect_native_activity(
            routes_path=self.routes, roots={"codex": [self.sessions]}, now=NOW,
            process_probe=probe, max_files=16, max_bytes=BUDGET,
        )
        serialized = json.dumps(result)
        self.assertNotIn(SENTINEL, serialized)
        self.assertNotIn(str(self.root), serialized)
        self.assertNotIn("thread-main-manager", serialized)
        return {agent["route_id"]: agent for agent in result["agents"]}

    def test_large_codex_latest_complete_turn_is_bounded_and_running(self):
        path = self.source()
        self.assertGreater(path.stat().st_size, BUDGET)
        with read_meter(path) as reads:
            agent = self.collect()["main-manager"]
        self.assertEqual(agent["state"], "running")
        self.assertEqual(agent["availability"], "available")
        self.assertLessEqual(reads["bytes"], BUDGET, "do not raise or bypass the per-source I/O budget")

    def test_large_codex_without_complete_tail_start_cannot_claim_running(self):
        self.source(tail=[turn()[1]])
        self.assertIsNone(self.collect()["main-manager"]["state"])

    def test_conflicting_header_and_tail_owners_cannot_claim_any_route(self):
        self.source(tail=[record("session_meta", 40, {"id": "thread-context-news"}), *turn()])
        agents = self.collect()
        self.assertIsNone(agents["main-manager"]["state"])
        self.assertIsNone(agents["context-news"]["state"])

    def test_trailing_partial_record_is_not_discarded_as_boundary_fragment(self):
        path = self.source()
        with path.open("ab") as handle:
            handle.write(b'{"timestamp":"2026-10-25T19:59:59Z","type":"event_msg"')
        self.assertIsNone(self.collect()["main-manager"]["state"])

    def test_growth_during_read_does_not_attest_a_stale_snapshot(self):
        path = self.source()
        def grow():
            with path.open("ab") as handle:
                handle.write(encode([record("event_msg", 1, {"type": "task_complete"})]))
        with read_meter(path, grow):
            agent = self.collect()["main-manager"]
        self.assertIsNone(agent["state"])

    def test_replacement_during_read_does_not_attest_a_different_inode(self):
        path = self.source()
        def replace():
            replacement = self.root / "replacement"
            replacement.write_bytes(encode([record("session_meta", 40, {"id": "thread-main-manager"}), *turn()]))
            os.replace(replacement, path)
        with read_meter(path, replace):
            agent = self.collect()["main-manager"]
        self.assertIsNone(agent["state"])

    def test_stable_unrelated_large_owner_does_not_poison_a_proven_route(self):
        older = self.source("rollout-manager.jsonl", large=False)
        unrelated = self.source("rollout-unrelated.jsonl", owner="unregistered-session")
        os.utime(older, (1000, 1000))
        os.utime(unrelated, (2000, 2000))
        self.assertEqual(self.collect()["main-manager"]["state"], "running")

    def test_mutation_during_process_attestation_cannot_claim_running(self):
        path = self.source(large=False)
        def mutate(*args, **kwargs):
            with path.open("ab") as handle:
                handle.write(encode([record("event_msg", 1, {"type": "task_complete"})]))
            return True
        self.assertIsNone(self.collect(mutate)["main-manager"]["state"])

    def test_current_codex_custom_tool_envelopes_are_progress_proof(self):
        for kind in ("custom_tool_call", "custom_tool_call_output"):
            with self.subTest(kind=kind):
                self.source(large=False, tail=turn(progress=kind))
                self.assertEqual(self.collect()["main-manager"]["state"], "running")


if __name__ == "__main__":
    unittest.main()
