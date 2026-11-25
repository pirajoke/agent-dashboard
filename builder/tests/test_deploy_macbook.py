"""builder/deploy_macbook.sh in a sandbox: no real launchd, HOME or collectors (Mark 2026-11-21 «Б + Г»)."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

BUILDER_DIR = Path(__file__).resolve().parents[1]


class DeployMacbookTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.home = self.root / "home"
        self.scripts = self.home / "scripts"
        self.scripts.mkdir(parents=True)
        (self.home / "Library" / "LaunchAgents").mkdir(parents=True)
        self.repo = self.root / "repo"
        builder = self.repo / "builder"
        builder.mkdir(parents=True)
        for name in ("deploy_macbook.sh", "auto_deploy.py"):
            shutil.copy2(BUILDER_DIR / name, builder / name)
        shutil.copytree(BUILDER_DIR / "launchd", builder / "launchd")
        # The collectors' own installer has its own tests; here it only notes that it ran.
        (builder / "install_daily_work_collector.sh").write_text('#!/bin/bash\necho "$*" >> "$MOCK_CALLS.collectors"\n')
        (builder / "install_daily_work_collector.sh").chmod(0o755)
        self.health_source = builder / "macbook" / "macbook-pro-health.py"
        self.health_target = self.scripts / "macbook-pro-health.py"
        self.health_target.write_text("print('old, not in git')\n")
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        subprocess.run(["git", "-C", str(self.repo), "-c", "user.email=t@t", "-c", "user.name=t",
                        "commit", "-q", "--allow-empty", "-m", "x"], check=True)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.calls = self.root / "calls"
        for name, body in {
            "plutil": "exit 0",
            "launchctl": 'echo "$*" >> "$MOCK_CALLS"; case "$1" in print) [[ "$2" == *macbook-pro-health ]];; *) exit 0;; esac',
        }.items():
            path = self.bin / name
            path.write_text(f"#!/bin/bash\n{body}\n")
            path.chmod(0o755)

    def deploy(self, **env):
        run_env = dict(os.environ, HOME=str(self.home), PATH=f"{self.bin}:{os.environ['PATH']}", MOCK_CALLS=str(self.calls), **env)
        subprocess.run([str(self.repo / "builder" / "deploy_macbook.sh")], check=True, env=run_env,
                       capture_output=True, text=True)
        calls = self.calls.read_text().splitlines() if self.calls.exists() else []
        self.calls.unlink(missing_ok=True)
        return calls

    def kickstarts(self, calls):
        return [c for c in calls if c.startswith("kickstart")]

    def test_health_script_from_git_replaces_the_old_one_and_restarts_only_on_change(self):
        self.health_source.parent.mkdir()
        self.health_source.write_text("print('from git')\n")
        first = self.deploy()
        self.assertEqual(self.health_target.read_text(), "print('from git')\n")
        self.assertEqual((self.scripts / "macbook-pro-health.py.pre-git").read_text(), "print('old, not in git')\n")
        self.assertEqual(len(self.kickstarts(first)), 1)
        self.assertIn("com.pirajoke.macbook-pro-health", self.kickstarts(first)[0])
        self.assertEqual(self.kickstarts(self.deploy()), [])  # nothing changed, no restart

    def test_rollback_to_a_commit_without_the_script_restores_the_pre_git_copy(self):
        self.health_source.parent.mkdir()
        self.health_source.write_text("print('from git')\n")
        self.deploy()
        self.health_source.unlink()
        calls = self.deploy()
        self.assertEqual(self.health_target.read_text(), "print('old, not in git')\n")
        self.assertEqual(len(self.kickstarts(calls)), 1)

    def test_installs_the_updater_records_the_commit_and_runs_the_collectors(self):
        self.deploy()
        plist = (self.home / "Library" / "LaunchAgents" / "com.pirajoke.macbook-auto-update.plist").read_text()
        for expected in ("builder/deploy_macbook.sh", "http://127.0.0.1:8880/api/all", "macbook-pro/deploy",
                         f"{self.scripts}/auto_deploy.py", str(self.repo)):
            self.assertIn(expected, plist)
        # Every __PLACEHOLDER__ is filled in. (A bare "__" can be part of the random temp folder name.)
        self.assertNotRegex(plist, r"__[A-Z_]+__")
        state = json.loads((self.home / ".agent-bridge" / "macbook-auto-update" / "state.json").read_text())
        head = subprocess.run(["git", "-C", str(self.repo), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
        self.assertEqual(state["deployed_sha"], head)
        self.assertIn("--machine macbook-pro --push-to maxxs-mac-mini", Path(f"{self.calls}.collectors").read_text())
        self.assertEqual(self.health_target.read_text(), "print('old, not in git')\n")  # no script in git yet: untouched

    def test_a_run_from_the_updater_does_not_reinstall_itself(self):
        calls = self.deploy(DASHBOARD_INSTALL_AUTO_DEPLOY="0")
        self.assertFalse((self.home / "Library" / "LaunchAgents" / "com.pirajoke.macbook-auto-update.plist").exists())
        self.assertFalse(any(c.startswith("bootstrap") for c in calls))


if __name__ == "__main__":
    unittest.main()


class AutoDeployMacbookSettingsTest(unittest.TestCase):
    def test_the_updater_plist_settings_reach_auto_deploy(self):
        import importlib.util
        import plistlib
        from unittest.mock import patch

        template = (BUILDER_DIR / "launchd" / "com.pirajoke.macbook-auto-update.plist.template").read_text()
        env = plistlib.loads(template.encode())["EnvironmentVariables"]
        with patch.dict(os.environ, env):
            spec = importlib.util.spec_from_file_location("auto_deploy_macbook", BUILDER_DIR / "auto_deploy.py")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        self.assertEqual(module.DEPLOY_SCRIPT, "builder/deploy_macbook.sh")
        self.assertEqual(module.STATUS_CONTEXT, "macbook-pro/deploy")
        self.assertEqual(module.HEALTH_URL, "http://127.0.0.1:8880/api/all")
        self.assertEqual(module.DEPLOY_PATHS, ("builder/",))
