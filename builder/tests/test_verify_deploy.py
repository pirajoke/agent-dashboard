from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


BUILDER_DIR = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("verify_deploy", BUILDER_DIR / "verify_deploy.py")
VERIFY = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(VERIFY)

# main history: a -> b -> c
ORDER = ["a", "b", "c"]


def contains(ancestor, descendant):
    return ORDER.index(ancestor) <= ORDER.index(descendant)


class VerdictTest(unittest.TestCase):
    def test_merged_commit_inside_deployed_history_is_live(self):
        self.assertEqual(VERIFY.verdict("b", {"deployed_sha": "c"}, [], contains, 200), "live")

    def test_live_but_site_down_is_reported(self):
        self.assertEqual(VERIFY.verdict("b", {"deployed_sha": "b"}, [], contains, 0), "live_unhealthy")

    def test_newer_than_deployed_is_pending(self):
        self.assertEqual(VERIFY.verdict("c", {"deployed_sha": "a"}, [], contains, 200), "pending")

    def test_rolled_back_commit_is_failed(self):
        state = {"deployed_sha": "a", "failed_sha": "c"}
        log = [{"sha": "c", "result": "health_failed", "rollback": "ok"}]
        self.assertEqual(VERIFY.verdict("c", state, log, contains, 200), "failed")

    def test_failed_rollback_confirms_nothing(self):
        state = {"deployed_sha": "b", "failed_sha": "c", "last_result": "deploy_failed_rollback_failed"}
        self.assertEqual(VERIFY.verdict("a", state, [], contains, 200), "rollback_failed")
        self.assertEqual(VERIFY.verdict("c", state, [], contains, 200), "rollback_failed")

    def test_later_good_deploy_clears_a_failed_rollback(self):
        state = {"deployed_sha": "c", "failed_sha": "b", "last_result": "deployed"}
        self.assertEqual(VERIFY.verdict("c", state, [], contains, 200), "live")

    def test_red_ci_is_told_apart_from_a_failed_deploy(self):
        state = {"deployed_sha": "a", "failed_sha": "c"}
        log = [{"sha": "c", "result": "ci_red"}]
        self.assertEqual(VERIFY.verdict("b", state, log, contains, 200), "ci_red")

    def test_waiting_for_ci(self):
        state = {"deployed_sha": "a", "waiting_sha": "c"}
        self.assertEqual(VERIFY.verdict("c", state, [], contains, 200), "waiting_ci")

    def test_no_state_yet_is_pending_not_live(self):
        self.assertEqual(VERIFY.verdict("a", {}, [], contains, 200), "pending")

    def test_every_status_has_a_message(self):
        for status in ("live", "live_unhealthy", "rollback_failed", "failed", "ci_red", "waiting_ci", "pending", "unknown_commit"):
            self.assertIn(status, VERIFY.MESSAGES)


if __name__ == "__main__":
    unittest.main()
