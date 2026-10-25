"""Independent GREEN review regressions, synthetic sources only."""
from contextlib import ExitStack
import unittest
import test_bounded_native_collector as fixture
from test_bounded_native_collector import BUDGET, NATIVE, NOW, encode, read_meter, record

class CollectorReviewBoundaryTests(unittest.TestCase):
    setUp = fixture.BoundedNativeCollectorTests.setUp
    source = fixture.BoundedNativeCollectorTests.source
    collect = fixture.BoundedNativeCollectorTests.collect

    def test_conflicting_owner_in_consumed_prefix_is_not_ignored(self):
        path = self.source()
        original = path.read_bytes()
        header, body = original.split(b"\n", 1)
        conflict = encode([record("session_meta", 3599, {"id": "thread-context-news"})])
        self.assertLess(len(header) + len(conflict), BUDGET // 4)
        path.write_bytes(header + b"\n" + conflict + body)
        self.assertIsNone(self.collect()["main-manager"]["state"])

    def test_rejected_sources_still_consume_global_io_budget(self):
        paths = []
        for index in range(8):
            path = self.sessions / ("rejected-%02d.jsonl" % index)
            path.write_bytes(encode([record("session_meta", 3600, {"id": "unregistered"})]) + b"x" * BUDGET * 16)
            paths.append(path)
        with ExitStack() as stack:
            meters = [stack.enter_context(read_meter(path)) for path in paths]
            self.collect()
        actual = sum(meter["bytes"] for meter in meters)
        self.assertLessEqual(actual, BUDGET * 4, "failed parse/read attempts must debit the global I/O budget")

    def test_changed_source_emits_valid_uncertain_checkpoint(self):
        path = self.source(large=False)
        def mutate(*args, **kwargs):
            with path.open("ab") as handle:
                handle.write(encode([record("event_msg", 1, {"type": "task_complete"})]))
            return True
        result = NATIVE.collect_native_activity(routes_path=self.routes, roots={"codex": [self.sessions]}, now=NOW, process_probe=mutate, max_files=16, max_bytes=BUDGET)
        manager = next(a for a in result["agents"] if a["route_id"] == "main-manager")
        self.assertIsNone(manager["state"])
        self.assertEqual(manager["freshness"], "invalid")
        self.assertIsNone(manager["state_at"], "invalid snapshot cannot retain a trusted state timestamp")
        self.assertIsNotNone(NATIVE.validate_native_activity_checkpoint(result, now=NOW))

if __name__ == "__main__":
    unittest.main()
