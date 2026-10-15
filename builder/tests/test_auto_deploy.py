from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


BUILDER_DIR = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("auto_deploy", BUILDER_DIR / "auto_deploy.py")
AUTO = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(AUTO)


class AutoDeployRunTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state_dir = Path(self.tmp.name)
        self.deploys: list[str] = []
        self.deploy_ok = {}
        self.health = [True]

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, head, changed=("builder/x.py",), ci="green"):
        def deploy(sha):
            self.deploys.append(sha)
            return self.deploy_ok.get(sha, True), "log"

        return AUTO.run(
            fetch_head=lambda: head,
            changed_between=lambda old, new: list(changed),
            get_ci=lambda sha: ci,
            do_deploy=deploy,
            is_healthy=lambda: self.health.pop(0) if self.health else True,
            state_dir=self.state_dir,
        )

    def _state(self):
        return json.loads((self.state_dir / "state.json").read_text())

    def test_up_to_date_does_nothing(self):
        AUTO.record_deployed("aaa", self.state_dir)
        self.assertEqual(self._run("aaa"), "up_to_date")
        self.assertEqual(self.deploys, [])

    def test_up_to_date_but_unhealthy_redeploys_current_main(self):
        AUTO.record_deployed("aaa", self.state_dir)
        self.health = [False, True]

        outcome = self._run("aaa")

        self.assertNotEqual(outcome, "up_to_date")
        self.assertEqual(self.deploys, ["aaa"])

    def test_failed_same_sha_repair_is_not_rolled_back_or_retried(self):
        AUTO.record_deployed("aaa", self.state_dir)
        self.health = [False]
        self.deploy_ok["aaa"] = False

        first_outcome = self._run("aaa")
        first_deploys = list(self.deploys)
        first_state = self._state()
        first_log = (self.state_dir / "deploys.jsonl").read_text().splitlines()

        self.health = [False]
        second_outcome = self._run("aaa")
        second_log = (self.state_dir / "deploys.jsonl").read_text().splitlines()

        self.assertTrue(first_outcome.startswith("deploy_failed"))
        self.assertEqual(first_state["failed_sha"], "aaa")
        self.assertTrue(first_state["last_result"].startswith("deploy_failed"))
        self.assertEqual(
            {
                "first_deploys": first_deploys,
                "first_log_count": len(first_log),
                "second_outcome": second_outcome,
                "all_deploys": self.deploys,
                "second_log_count": len(second_log),
            },
            {
                "first_deploys": ["aaa"],
                "first_log_count": 1,
                "second_outcome": "skipped_failed",
                "all_deploys": ["aaa"],
                "second_log_count": 1,
            },
        )

    def test_successful_same_sha_repair_clears_stale_failure_state(self):
        AUTO.save_state(
            {
                "deployed_sha": "aaa",
                "failed_sha": "older-sha",
                "failed_at": "2026-10-12T00:00:00Z",
                "last_result": "deploy_failed_rollback_failed",
            },
            self.state_dir,
        )
        self.health = [False, True]

        self.assertEqual(self._run("aaa"), "deployed")

        state = self._state()
        self.assertEqual(self.deploys, ["aaa"])
        self.assertEqual(state["last_result"], "deployed")
        self.assertNotIn("failed_sha", state)
        self.assertNotIn("failed_at", state)

    def test_generated_files_only_move_the_marker(self):
        AUTO.record_deployed("aaa", self.state_dir)
        self.assertEqual(self._run("bbb", changed=("index.html", "live-feed.json")), "no_builder_changes")
        self.assertEqual(self.deploys, [])
        self.assertEqual(self._state()["deployed_sha"], "bbb")

    def test_builder_change_with_green_ci_deploys(self):
        AUTO.record_deployed("aaa", self.state_dir)
        self.assertEqual(self._run("bbb"), "deployed")
        self.assertEqual(self.deploys, ["bbb"])
        self.assertEqual(self._state()["deployed_sha"], "bbb")
        log = (self.state_dir / "deploys.jsonl").read_text().splitlines()
        self.assertEqual(json.loads(log[-1])["result"], "deployed")

    def test_pending_ci_waits(self):
        AUTO.record_deployed("aaa", self.state_dir)
        self.assertEqual(self._run("bbb", ci="pending"), "ci_pending")
        self.assertEqual(self.deploys, [])
        self.assertEqual(self._state()["deployed_sha"], "aaa")
        self.assertEqual(self._run("bbb"), "deployed")

    def test_red_ci_is_never_deployed_again(self):
        AUTO.record_deployed("aaa", self.state_dir)
        self.assertEqual(self._run("bbb", ci="red"), "ci_red")
        self.assertEqual(self._run("bbb"), "skipped_failed")
        self.assertEqual(self.deploys, [])
        self.assertEqual(self._run("ccc"), "deployed")

    def test_failed_deploy_rolls_back(self):
        AUTO.record_deployed("aaa", self.state_dir)
        self.deploy_ok["bbb"] = False
        self.assertEqual(self._run("bbb"), "deploy_failed_rollback_ok")
        self.assertEqual(self.deploys, ["bbb", "aaa"])
        state = self._state()
        self.assertEqual(state["deployed_sha"], "aaa")
        self.assertEqual(state["failed_sha"], "bbb")

    def test_unhealthy_site_rolls_back(self):
        AUTO.record_deployed("aaa", self.state_dir)
        self.health = [False, True]
        self.assertEqual(self._run("bbb"), "health_failed_rollback_ok")
        self.assertEqual(self.deploys, ["bbb", "aaa"])

    def test_first_run_deploys_current_main(self):
        self.assertEqual(self._run("bbb", changed=()), "deployed")
        self.assertEqual(self.deploys, ["bbb"])


class CiStateTest(unittest.TestCase):
    def _ci(self, runs):
        return AUTO.ci_state("sha", fetch=lambda url: {"check_runs": runs})

    def test_states(self):
        self.assertEqual(self._ci([]), "pending")
        self.assertEqual(self._ci([{"status": "in_progress"}]), "pending")
        self.assertEqual(self._ci([{"status": "completed", "conclusion": "success"}]), "green")
        self.assertEqual(
            self._ci([{"status": "completed", "conclusion": "success"},
                      {"status": "completed", "conclusion": "failure"}]),
            "red",
        )


class PublishSafetyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state_dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _check(self, remote_sha, changed=()):
        return AUTO.publish_safety(
            remote_sha,
            changed_between=lambda old, new: list(changed),
            state_dir=self.state_dir,
        )

    def test_publish_is_blocked_without_a_recorded_runtime(self):
        self.assertEqual(self._check("bbb"), (False, "runtime_sha_missing"))

    def test_publish_is_allowed_when_runtime_matches_remote_main(self):
        AUTO.record_deployed("bbb", self.state_dir)
        self.assertEqual(self._check("bbb"), (True, "runtime_matches_main"))

    def test_publish_is_blocked_while_runtime_lags_builder_changes(self):
        AUTO.record_deployed("aaa", self.state_dir)
        self.assertEqual(
            self._check("bbb", changed=("builder/dashboard_builder/html_builder.py", "index.html")),
            (False, "runtime_behind_builder"),
        )

    def test_publish_is_allowed_when_only_generated_files_are_newer(self):
        AUTO.record_deployed("aaa", self.state_dir)
        self.assertEqual(
            self._check("bbb", changed=("index.html", "live-feed.json")),
            (True, "runtime_matches_builder"),
        )


class DeployScriptWiringTest(unittest.TestCase):
    def test_deploy_script_installs_and_records(self):
        script = (BUILDER_DIR / "deploy_to_scripts.sh").read_text()
        self.assertIn('cp "$SRC_DIR/auto_deploy.py"', script)
        self.assertIn("DASHBOARD_INSTALL_AUTO_DEPLOY", script)
        self.assertIn("auto_deploy.py\" --record", script)
        # The agent starts at load, so the deployed commit must be recorded first.
        self.assertLess(script.index("--record"), script.index('launchctl bootstrap "gui/$(id -u)" "$AUTO_DEPLOY_PLIST"'))
        self.assertTrue((BUILDER_DIR / "launchd" / "com.pirajoke.dashboard-auto-deploy.plist.template").exists())

    def test_deploy_script_restarts_or_bootstraps_dashboard_server(self):
        script = (BUILDER_DIR / "deploy_to_scripts.sh").read_text()
        fragments = (
            'SERVER_PLIST="$HOME/Library/LaunchAgents/$SERVER_LABEL.plist"',
            'if launchctl print "gui/$(id -u)/$SERVER_LABEL" >/dev/null 2>&1; then',
            'launchctl kickstart -k "gui/$(id -u)/$SERVER_LABEL"',
            'elif [[ -f "$SERVER_PLIST" ]]; then',
            'launchctl bootstrap "gui/$(id -u)" "$SERVER_PLIST"',
        )
        for fragment in fragments:
            self.assertIn(fragment, script)
        self.assertEqual(sorted(map(script.index, fragments)), list(map(script.index, fragments)))

    def test_rebuild_checks_runtime_freshness_before_copying_or_pushing(self):
        script = (BUILDER_DIR / "dashboard-rebuild.sh").read_text()
        guard = 'auto_deploy.py" --can-publish "$REMOTE_SHA"'
        copy = 'cp "$HTML_OUT" "$PUBLISH_WT/index.html"'
        push = "git push origin HEAD:main"
        for fragment in (guard, copy, push):
            self.assertIn(fragment, script)
        self.assertLess(script.index(guard), script.index(copy))
        self.assertLess(script.index(guard), script.index(push))


if __name__ == "__main__":
    unittest.main()
