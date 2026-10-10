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


class DeployScriptWiringTest(unittest.TestCase):
    def test_deploy_script_installs_and_records(self):
        script = (BUILDER_DIR / "deploy_to_scripts.sh").read_text()
        self.assertIn('cp "$SRC_DIR/auto_deploy.py"', script)
        self.assertIn("DASHBOARD_INSTALL_AUTO_DEPLOY", script)
        self.assertIn("auto_deploy.py\" --record", script)
        # The agent starts at load, so the deployed commit must be recorded first.
        self.assertLess(script.index("--record"), script.index('launchctl bootstrap "gui/$(id -u)" "$AUTO_DEPLOY_PLIST"'))
        self.assertTrue((BUILDER_DIR / "launchd" / "com.pirajoke.dashboard-auto-deploy.plist.template").exists())


if __name__ == "__main__":
    unittest.main()
