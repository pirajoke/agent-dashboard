from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import unittest


BUILDER_DIR = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("verify_release", BUILDER_DIR / "verify_release.py")
VERIFY = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(VERIFY)

MAIN = "b" * 40
LIVE = "a" * 40


def status(state, changed=("builder/x.py",), ancestor=False):
    return VERIFY.deploy_status(
        MAIN, state,
        changed_since_deploy=lambda old, new: None if changed is None else list(changed),
        is_ancestor=lambda a, b: ancestor,
    )


class DeployStatusTest(unittest.TestCase):
    def test_live_when_auto_deploy_recorded_the_commit(self):
        self.assertEqual(status({"deployed_sha": MAIN})["status"], "ok")

    def test_live_when_commit_is_inside_a_later_deploy(self):
        self.assertEqual(status({"deployed_sha": LIVE}, ancestor=True)["status"], "ok")

    def test_generated_only_commit_counts_as_live(self):
        self.assertEqual(status({"deployed_sha": LIVE}, changed=("index.html", "live-feed.json"))["status"], "ok")

    def test_builder_change_not_yet_deployed_waits(self):
        result = status({"deployed_sha": LIVE})
        self.assertEqual(result["status"], "wait")
        self.assertIn(LIVE[:7], result["summary"])

    def test_waiting_for_ci_says_why(self):
        result = status({"deployed_sha": LIVE, "waiting_sha": MAIN, "waiting_reason": "ci_pending"})
        self.assertEqual(result["status"], "wait")
        self.assertIn("ci_pending", result["summary"])

    def test_failed_commit_fails_even_if_history_is_unknown(self):
        result = status({"deployed_sha": LIVE, "failed_sha": MAIN, "last_result": "health_failed_rollback_ok"},
                        changed=None)
        self.assertEqual(result["status"], "fail")
        self.assertIn("health_failed_rollback_ok", result["summary"])

    def test_unknown_history_does_not_claim_live(self):
        self.assertEqual(status({"deployed_sha": LIVE}, changed=None)["status"], "wait")

    def test_no_recorded_deploy_fails(self):
        self.assertEqual(status({})["status"], "fail")


class DeployLogTest(unittest.TestCase):
    NOW = datetime(2026, 10, 26, 18, 0, tzinfo=timezone.utc)

    def test_only_recent_non_deploys_are_problems(self):
        entries = [
            {"at": "2026-10-26T17:00:00Z", "sha": MAIN, "result": "deployed"},
            {"at": "2026-10-26T16:00:00Z", "sha": MAIN, "result": "health_failed", "rollback": "ok", "output": "x"},
            {"at": "2026-10-20T16:00:00Z", "sha": LIVE, "result": "ci_red"},
            {"at": "not a time", "result": "deploy_failed"},
        ]
        problems = VERIFY.recent_problems(entries, self.NOW)
        self.assertEqual(problems, [{"at": "2026-10-26T16:00:00Z", "sha": MAIN, "result": "health_failed",
                                     "rollback": "ok"}])


class HealthTest(unittest.TestCase):
    def test_ok_with_expected_text(self):
        result = VERIFY.check_health("http://x/", ["mm-week-strip"], fetcher=lambda url: (200, "<div class=mm-week-strip>"))
        self.assertEqual(result["status"], "ok")

    def test_missing_text_fails(self):
        result = VERIFY.check_health("http://x/", ["mm-week-strip"], fetcher=lambda url: (200, "<div>"))
        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["missing"], ["mm-week-strip"])

    def test_down_site_fails(self):
        self.assertEqual(VERIFY.check_health("http://x/", [], fetcher=lambda url: (0, "refused"))["status"], "fail")
        self.assertEqual(VERIFY.check_health("http://x/", [], fetcher=lambda url: (502, ""))["status"], "fail")


class UnittestOutputTest(unittest.TestCase):
    def test_passing_run(self):
        self.assertEqual(VERIFY.parse_unittest("....\n---\nRan 877 tests in 33.6s\n\nOK\n"), (877, True, []))

    def test_passing_run_with_skips(self):
        self.assertEqual(VERIFY.parse_unittest("Ran 3 tests in 1s\n\nOK (skipped=1)\n")[1], True)

    def test_failing_run_names_tests(self):
        output = ("FAIL: test_a (test_x.T)\n---\nERROR: test_b (test_y.T)\n---\n"
                  "Ran 9 tests in 1s\n\nFAILED (failures=1, errors=1)\n")
        self.assertEqual(VERIFY.parse_unittest(output), (9, False, ["test_a (test_x.T)", "test_b (test_y.T)"]))


class ScreensTest(unittest.TestCase):
    EXPECTED = {"phone": (390, 844)}

    def shot(self, **overrides):
        return {"name": "phone", "path": "/tmp/phone.png", "loaded": True, "nav_error": "",
                "http_status": 200, "viewport": [390, 844],
                "scroll_width": 390, "errors": [], **overrides}

    def test_clean_shot_passes(self):
        self.assertEqual(VERIFY.judge_shots([self.shot()], self.EXPECTED)["status"], "ok")

    def test_sideways_scroll_fails(self):
        result = VERIFY.judge_shots([self.shot(scroll_width=512)], self.EXPECTED)
        self.assertEqual(result["status"], "fail")
        self.assertIn("512px", result["summary"])

    def test_error_page_fails(self):
        result = VERIFY.judge_shots([self.shot(http_status=404)], self.EXPECTED)
        self.assertEqual(result["status"], "fail")
        self.assertIn("404", result["summary"])

    def test_failed_navigation_fails(self):
        result = VERIFY.judge_shots([self.shot(nav_error="net::ERR_CONNECTION_REFUSED", http_status=0)],
                                    self.EXPECTED)
        self.assertIn("ERR_CONNECTION_REFUSED", result["summary"])

    def test_wrong_viewport_fails(self):
        self.assertEqual(VERIFY.judge_shots([self.shot(viewport=[500, 844])], self.EXPECTED)["status"], "fail")

    def test_page_error_fails(self):
        result = VERIFY.judge_shots([self.shot(errors=["TypeError: x is undefined"])], self.EXPECTED)
        self.assertIn("TypeError", result["summary"])

    def test_page_errors_come_from_own_tab_only(self):
        events = [
            {"sessionId": "s1", "method": "Runtime.exceptionThrown",
             "params": {"exceptionDetails": {"exception": {"description": "TypeError: boom\n    at x"}}}},
            {"sessionId": "s2", "method": "Runtime.exceptionThrown",
             "params": {"exceptionDetails": {"text": "other tab"}}},
        ]
        self.assertEqual(VERIFY.page_errors(events, "s1"), ["TypeError: boom"])


class ExitCodeTest(unittest.TestCase):
    def test_fail_beats_wait_beats_ok(self):
        ok, wait, fail, skip = ({"status": s} for s in ("ok", "wait", "fail", "skip"))
        self.assertEqual(VERIFY.exit_code({"a": ok, "b": skip}), 0)
        self.assertEqual(VERIFY.exit_code({"a": ok, "b": wait}), 2)
        self.assertEqual(VERIFY.exit_code({"a": wait, "b": fail}), 1)


if __name__ == "__main__":
    unittest.main()
