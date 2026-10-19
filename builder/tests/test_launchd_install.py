"""Run the real installation blocks without touching this machine's launchd."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile
import unittest


BUILDER_DIR = Path(__file__).resolve().parents[1]


class LaunchdInstallTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.calls = self.root / "calls"
        self.loaded = self.root / "loaded"
        self.plist = self.root / "service.plist"
        self.candidate = self.root / "service.plist.tmp"
        self.label = "com.example.install-regression"
        self._executable("plutil", "#!/bin/bash\nexit 0\n")
        self._executable("sleep", "#!/bin/bash\nexit 0\n")
        self._executable("launchctl", '''#!/bin/bash
printf '%s\\n' "$*" >> "$MOCK_CALLS"
case "$1" in
  print)
    if [[ -f "$MOCK_LOADED.pending" ]]; then
      read -r remaining < "$MOCK_LOADED.pending"
      if ((remaining > 0)); then
        echo "$((remaining - 1))" > "$MOCK_LOADED.pending"
      else
        rm -f "$MOCK_LOADED" "$MOCK_LOADED.pending"
      fi
    fi
    test -f "$MOCK_LOADED"
    ;;
  bootout)
    if (( ${MOCK_UNLOAD_READS:-0} > 0 )); then
      echo "$MOCK_UNLOAD_READS" > "$MOCK_LOADED.pending"
    else
      rm -f "$MOCK_LOADED"
    fi
    ;;
  bootstrap)
    if [[ -f "$MOCK_LOADED" ]]; then
      echo "Bootstrap failed: 37: Operation already in progress" >&2
      exit 37
    fi
    if [[ "${MOCK_BOOTSTRAP_FAIL:-0}" == 1 ]]; then
      echo "Bootstrap failed: 5: Input/output error" >&2
      exit 5
    fi
    touch "$MOCK_LOADED"
    ;;
  *) echo "Unexpected launchctl command" >&2; exit 99 ;;
esac
''')

    def _executable(self, name, content):
        path = self.bin / name
        path.write_text(content)
        path.chmod(0o755)

    def _block(self, caller):
        # Extract the active caller block, not a copy of its implementation.
        # The helper is sourced separately so these focused tests do not run
        # the surrounding deployment, collectors, or write to the user's HOME.
        if caller == "publisher":
            script = (BUILDER_DIR / "deploy_to_scripts.sh").read_text()
            start = script.index('  plutil -lint "$PUBLISHER_PLIST.tmp"')
            return script[start:script.index("\nfi", start)]
        script = (BUILDER_DIR / "install_daily_work_collector.sh").read_text()
        start = script.index('  plutil -lint "$plist.tmp"')
        return script[start:script.index("\n}", start)]

    def _run(self, caller, *, installed="same", loaded=True, fail=False, unload_reads=0):
        self.calls.write_text("")
        self.loaded.unlink(missing_ok=True)
        Path(str(self.loaded) + ".pending").unlink(missing_ok=True)
        self.plist.unlink(missing_ok=True)
        self.candidate.write_text("desired plist\n")
        if installed != "missing":
            self.plist.write_text("desired plist\n" if installed == "same" else "old plist\n")
        if loaded:
            self.loaded.touch()
        env = dict(os.environ)
        env.update(
            PATH=f"{self.bin}:/usr/bin:/bin",
            MOCK_CALLS=str(self.calls), MOCK_LOADED=str(self.loaded),
            MOCK_BOOTSTRAP_FAIL="1" if fail else "0",
            MOCK_UNLOAD_READS=str(unload_reads),
            PUBLISHER_LABEL=self.label, PUBLISHER_PLIST=str(self.plist),
            label=self.label, plist=str(self.plist),
            TEST_INSTALL_HELPER=str(BUILDER_DIR / "launchd" / "install_agent.sh"),
        )
        result = subprocess.run(
            ["/bin/bash", "-c", 'set -euo pipefail\n'
             'if [[ -f "$TEST_INSTALL_HELPER" ]]; then source "$TEST_INSTALL_HELPER"; fi\n'
             + self._block(caller)],
            env=env, capture_output=True, text=True, timeout=20,
        )
        self.mutations = [line.split()[0] for line in self.calls.read_text().splitlines()
                          if not line.startswith("print ")]
        return result

    def test_unchanged_loaded_agent_is_not_restarted(self):
        for caller in ("publisher", "collector"):
            with self.subTest(caller=caller):
                result = self._run(caller)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.mutations, [], "A frontend-only deploy must not unload an unchanged agent")
                self.assertTrue(self.loaded.exists())
                self.assertEqual(self.plist.read_text(), "desired plist\n")

    def test_changed_loaded_agent_is_reinstalled(self):
        for caller in ("publisher", "collector"):
            with self.subTest(caller=caller):
                result = self._run(caller, installed="different")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.mutations, ["bootout", "bootstrap"])
                self.assertEqual(self.plist.read_text(), "desired plist\n")
                self.assertTrue(self.loaded.exists())

    def test_unloaded_agent_is_bootstrapped_even_with_identical_plist(self):
        for caller in ("publisher", "collector"):
            with self.subTest(caller=caller):
                result = self._run(caller, loaded=False)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.mutations, ["bootstrap"])
                self.assertTrue(self.loaded.exists())

    def test_changed_agent_waits_for_asynchronous_bootout_before_bootstrap(self):
        for caller in ("publisher", "collector"):
            with self.subTest(caller=caller):
                result = self._run(caller, installed="different", unload_reads=2)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.mutations, ["bootout", "bootstrap"])
                self.assertTrue(self.loaded.exists())

    def test_missing_plist_is_installed_and_bootstrapped(self):
        for caller in ("publisher", "collector"):
            with self.subTest(caller=caller):
                result = self._run(caller, installed="missing", loaded=False)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.mutations, ["bootstrap"])
                self.assertEqual(self.plist.read_text(), "desired plist\n")
                self.assertTrue(self.loaded.exists())

    def test_stuck_unload_fails_without_bootstrapping_or_replacing_plist(self):
        for caller in ("publisher", "collector"):
            with self.subTest(caller=caller):
                result = self._run(caller, installed="different", unload_reads=100000)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(self.label, result.stdout + result.stderr)
                self.assertEqual(self.mutations, ["bootout"])
                self.assertEqual(self.plist.read_text(), "old plist\n")
                self.assertTrue(self.loaded.exists())

    def test_bootstrap_failure_propagates_and_names_the_agent(self):
        for caller in ("publisher", "collector"):
            with self.subTest(caller=caller):
                result = self._run(caller, loaded=False, fail=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(self.label, result.stdout + result.stderr)
                self.assertIn("Bootstrap failed", result.stderr)
                self.assertFalse(self.loaded.exists())


if __name__ == "__main__":
    unittest.main()
