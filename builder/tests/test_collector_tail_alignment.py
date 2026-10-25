"""A retained tail already beginning at a record boundary must preserve that record."""
import unittest
import test_bounded_native_collector as fixture
from test_bounded_native_collector import BUDGET, encode, record, turn

class CollectorTailAlignmentTests(unittest.TestCase):
    setUp = fixture.BoundedNativeCollectorTests.setUp
    source = fixture.BoundedNativeCollectorTests.source
    collect = fixture.BoundedNativeCollectorTests.collect

    def test_aligned_tail_conflicting_owner_is_not_dropped_as_partial(self):
        tail_budget = BUDGET - BUDGET // 4
        records = [record("session_meta", 40, {"id": "thread-context-news"}), *turn(), record("event_msg", 1, {"type": "opaque", "content": ""})]
        padding = tail_budget - len(encode(records))
        self.assertGreater(padding, 0)
        records[-1]["payload"]["content"] = "x" * padding
        self.assertEqual(len(encode(records)), tail_budget)
        self.source(tail=records)
        self.assertIsNone(self.collect()["main-manager"]["state"])

if __name__ == "__main__":
    unittest.main()
