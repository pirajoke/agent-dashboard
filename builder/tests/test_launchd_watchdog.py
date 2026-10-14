from __future__ import annotations

import importlib.util
import json
import plistlib
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

BUILDER_DIR = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("launchd_watchdog", BUILDER_DIR / "launchd_watchdog.py")
WATCHDOG = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(WATCHDOG)

JARVIS = "com.pirajoke.jarvis-bot"
NEWS = "com.pirajoke.context-news-worker"
OLLAMA = "homebrew.mxcl.ollama"
OBSIDIAN = "com.pirajoke.obsidian-tg-bot"


class WatchdogRunTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.agents = root / "LaunchAgents"
        self.state = root / "state"
        self.agents.mkdir()
        for label in (JARVIS, NEWS, OLLAMA, OBSIDIAN, WATCHDOG.SELF_LABEL, "com.google.keystone.agent"):
            (self.agents / f"{label}.plist").write_bytes(plistlib.dumps({"Label": label}))
        (self.agents / "broken.plist").write_text("not a plist")
        self.loads: list[str] = []
        self.sleeps: list[int] = []
        self.load_ok = True

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, *views, in_release=True):
        """Each view is (loaded, disabled) as launchctl answers on successive reads."""
        views = list(views)
        self.removed = []

        def read_launchd():
            return views.pop(0) if len(views) > 1 else views[0]

        def load(plist):
            self.loads.append(plistlib.loads(plist.read_bytes())["Label"])
            return self.load_ok, "" if self.load_ok else "Bootstrap failed: 5: Input/output error"

        return WATCHDOG.run_once(
            state_dir=self.state,
            agents_dir=self.agents,
            read_launchd=read_launchd,
            load=load,
            sleep=self.sleeps.append,
            in_release=lambda: in_release,
            remove=lambda agents_dir, state_dir: self.removed.append(agents_dir),
        )

    def _state(self) -> dict:
        return json.loads((self.state / "state.json").read_text())

    def test_first_run_learns_what_runs_and_loads_nothing(self):
        result = self._run(({JARVIS, NEWS, "com.google.keystone.agent", WATCHDOG.SELF_LABEL}, set()))
        self.assertEqual(result["loaded"], {})
        self.assertEqual(self._state()["wanted"], [NEWS, JARVIS])
        self.assertEqual(self.loads, [])
        self.assertEqual(self.sleeps, [])

    def test_after_a_reboot_it_loads_back_what_was_running(self):
        self._run(({JARVIS, NEWS}, set()))
        result = self._run(({JARVIS}, set()), ({JARVIS}, set()))
        self.assertEqual(result["loaded"], {NEWS: "loaded"})
        self.assertEqual(self.loads, [NEWS])
        self.assertEqual(self.sleeps, [WATCHDOG.RECHECK_SECONDS])
        events = (self.state / "events.jsonl").read_text().splitlines()
        self.assertEqual(json.loads(events[-1])["label"], NEWS)

    def test_services_that_are_off_stay_off(self):
        # Ollama and the Obsidian bot were never seen running, so they are never loaded.
        self._run(({JARVIS}, {OBSIDIAN}))
        self._run((set(["other"]), {OBSIDIAN}), (set(["other"]), {OBSIDIAN}))
        self.assertEqual(self.loads, [JARVIS])

    def test_switched_off_or_removed_service_is_forgotten(self):
        self._run(({JARVIS, NEWS}, set()))
        (self.agents / f"{NEWS}.plist").unlink()
        self._run(({"other"}, {JARVIS}), ({"other"}, {JARVIS}))
        self.assertEqual(self.loads, [])
        self.assertEqual(self._state()["wanted"], [])

    def test_a_job_reloaded_by_a_deploy_meanwhile_is_left_alone(self):
        self._run(({JARVIS, NEWS}, set()))
        self._run(({JARVIS}, set()), ({JARVIS, NEWS}, set()))
        self.assertEqual(self.loads, [])

    def test_failed_load_is_logged_and_kept_wanted(self):
        self._run(({JARVIS, NEWS}, set()))
        self.load_ok = False
        result = self._run(({JARVIS}, set()), ({JARVIS}, set()))
        self.assertEqual(result["loaded"], {NEWS: "failed"})
        self.assertIn(NEWS, self._state()["wanted"])
        self.assertIn("Bootstrap failed", (self.state / "events.jsonl").read_text())

    def test_nothing_changes_when_launchctl_does_not_answer(self):
        self._run(({JARVIS, NEWS}, set()))
        for view in ((None, set()), ({JARVIS}, None)):
            with self.subTest(view=view):
                self.assertEqual(self._run(view), {"status": "launchctl_unavailable"})
        self.assertEqual(self.loads, [])
        self.assertEqual(self._state()["wanted"], [NEWS, JARVIS])


    def test_rollback_to_a_release_without_the_watchdog_removes_it(self):
        self._run(({JARVIS, NEWS}, set()))
        result = self._run(({JARVIS}, set()), in_release=False)
        self.assertEqual(result, {"status": "removed"})
        self.assertEqual(self.removed, [self.agents])
        self.assertEqual(self.loads, [])

    def test_unknown_release_keeps_the_watchdog(self):
        self._run(({JARVIS, NEWS}, set()))
        result = self._run(({JARVIS}, set()), ({JARVIS}, set()), in_release=None)
        self.assertEqual(result["loaded"], {NEWS: "loaded"})
        self.assertEqual(self.removed, [])

    def test_remove_self_deletes_its_plist_and_logs(self):
        with patch.object(WATCHDOG, "run", return_value=(0, "")) as run:
            WATCHDOG.remove_self(self.agents, self.state)
        self.assertFalse((self.agents / f"{WATCHDOG.SELF_LABEL}.plist").exists())
        self.assertTrue((self.agents / f"{JARVIS}.plist").exists())
        self.assertIn("removed", (self.state / "events.jsonl").read_text())
        self.assertEqual(run.call_args[0][0][:2], ["launchctl", "bootout"])


class ReleaseHasWatchdogTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.repo = root / "repo"
        self.state_file = root / "state.json"
        git = ["git", "-C", str(self.repo), "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false"]
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        (self.repo / "README").write_text("old release")
        subprocess.run(git + ["add", "-A"], check=True)
        subprocess.run(git + ["commit", "-qm", "old"], check=True)
        self.old = subprocess.run(git + ["rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
        (self.repo / "builder").mkdir()
        (self.repo / "builder" / "launchd_watchdog.py").write_text("# watchdog")
        subprocess.run(git + ["add", "-A"], check=True)
        subprocess.run(git + ["commit", "-qm", "new"], check=True)
        self.new = subprocess.run(git + ["rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()

    def tearDown(self):
        self.tmp.cleanup()

    def _check(self, state):
        if state is not None:
            self.state_file.write_text(json.dumps(state))
        return WATCHDOG.release_has_watchdog(self.state_file, self.repo)

    def test_release_with_and_without_the_watchdog(self):
        self.assertTrue(self._check({"deployed_sha": self.new}))
        self.assertFalse(self._check({"deployed_sha": self.old}))

    def test_unknown_release_is_none(self):
        self.assertIsNone(self._check(None))
        self.assertIsNone(self._check({}))
        self.assertIsNone(self._check({"deployed_sha": "0" * 40}))


class DeployInstallsWatchdogTest(unittest.TestCase):
    def test_deploy_copies_compiles_and_installs_the_watchdog(self):
        deploy = (BUILDER_DIR / "deploy_to_scripts.sh").read_text()
        self.assertIn('cp "$SRC_DIR/launchd_watchdog.py" "$SCRIPTS_DIR/launchd_watchdog.py"', deploy)
        self.assertIn("auto_deploy.py launchd_watchdog.py dashboard_builder/*.py", deploy)
        self.assertIn('launchctl bootstrap "gui/$(id -u)" "$WATCHDOG_PLIST"', deploy)
        # Installed after the deployed commit is recorded, or its first run would see the old release.
        self.assertLess(deploy.index('auto_deploy.py" --record'), deploy.index('"$WATCHDOG_PLIST"'))
        template = plistlib.loads(
            (BUILDER_DIR / "launchd" / "com.pirajoke.launchd-watchdog.plist.template").read_bytes()
        )
        self.assertEqual(template["Label"], WATCHDOG.SELF_LABEL)
        self.assertEqual(template["StartInterval"], 300)
        self.assertTrue(template["RunAtLoad"])
        self.assertEqual(template["ProgramArguments"][1], "__SCRIPTS_DIR__/launchd_watchdog.py")


if __name__ == "__main__":
    unittest.main()
