from __future__ import annotations

import importlib.util
import json
import plistlib
import tempfile
import unittest
from pathlib import Path

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

    def _run(self, *views):
        """Each view is (loaded, disabled) as launchctl answers on successive reads."""
        views = list(views)

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


class DeployInstallsWatchdogTest(unittest.TestCase):
    def test_deploy_copies_compiles_and_installs_the_watchdog(self):
        deploy = (BUILDER_DIR / "deploy_to_scripts.sh").read_text()
        self.assertIn('cp "$SRC_DIR/launchd_watchdog.py" "$SCRIPTS_DIR/launchd_watchdog.py"', deploy)
        self.assertIn("auto_deploy.py launchd_watchdog.py dashboard_builder/*.py", deploy)
        self.assertIn('launchctl bootstrap "gui/$(id -u)" "$WATCHDOG_PLIST"', deploy)
        template = plistlib.loads(
            (BUILDER_DIR / "launchd" / "com.pirajoke.launchd-watchdog.plist.template").read_bytes()
        )
        self.assertEqual(template["Label"], WATCHDOG.SELF_LABEL)
        self.assertEqual(template["StartInterval"], 300)
        self.assertTrue(template["RunAtLoad"])
        self.assertEqual(template["ProgramArguments"][1], "__SCRIPTS_DIR__/launchd_watchdog.py")


if __name__ == "__main__":
    unittest.main()
