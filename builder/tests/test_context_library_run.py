"""Synthetic CLI contract for the single manual-intake + catalog runner.

RUN1 lossless ordered import/export and idempotency; DRY1 zero-write preview;
SAFE1 fail-closed config/root boundaries and last-good preservation;
LOCK1 exclusive runner lock; PRIV1 stdout is counts/state, not private context.
"""
from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

BUILDER = Path(__file__).resolve().parents[1]
RUNNER = BUILDER / 'context_library_run.py'
PRIVATE = 'SYNTHETIC_PRIVATE_MEETING_BODY_DO_NOT_LOG'


class ContextLibraryRunTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(RUNNER.is_file(), 'RED: context_library_run.py is not implemented')
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.vault = self.base / 'FixtureVault'
        self.output = self.base / 'FixtureDrive'
        self.state = self.base / 'PrivateRuntime'
        self.intake = self.base / 'ManualExports'
        for path in (self.vault, self.output, self.state, self.intake):
            path.mkdir()
        self.source = self.intake / 'krisp' / 'synthetic.txt'
        self.source.parent.mkdir()
        self.source.write_text(PRIVATE + '\nSynthetic speaker: inspect the lighthouse.\n')
        self.config = self.base / 'runner-config.json'
        self.write_config()

    def write_config(self, **changes):
        values = dict(vault=str(self.vault), output=str(self.output),
                      state_dir=str(self.state), intake=str(self.intake))
        values.update(changes)
        self.config.write_text(json.dumps(values))

    def snapshot(self, root=None):
        root = root or self.base
        return {str(p.relative_to(root)): (p.read_bytes(), p.stat().st_mtime_ns)
                if p.is_file() else None for p in root.rglob('*')}

    def run_cli(self, dry=False):
        args = [sys.executable, str(RUNNER), '--config', str(self.config)]
        if dry:
            args.append('--dry-run')
        env = dict(os.environ, PYTHONPATH=str(BUILDER))
        completed = subprocess.run(args, capture_output=True, text=True, env=env,
                                   cwd=str(BUILDER.parent), timeout=20)
        for channel in (completed.stdout, completed.stderr):
            self.assertNotIn(PRIVATE, channel, 'Private source content must never be printed')
            self.assertNotIn(str(self.base), channel, 'Private filesystem paths must not be printed')
        return completed

    def output_json(self, completed):
        # A single result or multiple bounded component results are both acceptable.
        rows = [json.loads(line) for line in completed.stdout.splitlines() if line.strip()]
        self.assertTrue(rows, 'CLI must report bounded machine-readable status')
        self.assertTrue(all(isinstance(row, dict) for row in rows))
        return rows[-1]

    def test_dry1_preview_does_not_create_notes_exports_state_or_locks(self):
        before = self.snapshot()
        result = self.run_cli(dry=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.output_json(result)
        self.assertEqual(self.snapshot(), before)

    def test_run1_real_import_precedes_export_and_second_run_is_idempotent(self):
        source_before = self.snapshot(self.intake)
        first = self.run_cli()
        self.assertEqual(first.returncode, 0, first.stderr)
        self.output_json(first)
        notes = list((self.vault / '00-Inbox/krisp').glob('*.md'))
        self.assertEqual(len(notes), 1)
        self.assertIn(PRIVATE, notes[0].read_text())
        exports = [p for p in self.output.rglob('*.txt') if PRIVATE in p.read_text()]
        self.assertEqual(len(exports), 1, 'The same run must export the just-imported note')
        snapshot = self.state / 'catalog.json'
        self.assertTrue(snapshot.is_file())
        data = json.loads(snapshot.read_text())
        self.assertEqual(len(data['records']), 1)
        note_before, output_before = self.snapshot(self.vault), self.snapshot(self.output)
        second = self.run_cli()
        self.assertEqual(second.returncode, 0, second.stderr)
        self.output_json(second)
        self.assertEqual(self.snapshot(self.vault), note_before)
        self.assertEqual(self.snapshot(self.output), output_before)
        self.assertEqual(self.snapshot(self.intake), source_before)

    def test_safe1_missing_vault_preserves_last_good_catalog_and_exports(self):
        self.assertEqual(self.run_cli().returncode, 0)
        before_catalog = (self.state / 'catalog.json').read_bytes()
        before_output = self.snapshot(self.output)
        self.vault.rename(self.base / 'VaultTemporarilyUnavailable')
        result = self.run_cli()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.output_json(result)['state'], 'unavailable')
        self.assertEqual((self.state / 'catalog.json').read_bytes(), before_catalog)
        self.assertEqual(self.snapshot(self.output), before_output)
        self.assertFalse(self.vault.exists())

    def test_safe1_every_missing_configured_root_fails_before_any_import(self):
        for field in ('vault', 'output', 'state_dir', 'intake'):
            with self.subTest(field=field):
                missing = self.base / ('Missing-' + field)
                self.write_config(**{field: str(missing)})
                before = self.snapshot()
                result = self.run_cli()
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.snapshot(), before)
                self.assertFalse(missing.exists())

    def test_safe1_state_directory_nested_in_data_roots_is_rejected(self):
        for root in (self.vault, self.output, self.intake):
            with self.subTest(root=root.name):
                forbidden = root / 'NestedRuntime'
                forbidden.mkdir()
                self.write_config(state_dir=str(forbidden))
                before = self.snapshot()
                result = self.run_cli()
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.snapshot(), before)

    def test_safe1_malformed_or_incomplete_config_creates_nothing(self):
        for payload in ('{"broken":', '[]', '{}', '{"vault": 42}'):
            with self.subTest(payload=payload):
                self.config.write_text(payload)
                before = self.snapshot()
                result = self.run_cli()
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.output_json(result)['state'], 'unavailable')
                self.assertEqual(self.snapshot(), before)

    def test_lock1_overlapping_runner_does_not_import_or_publish(self):
        lock = self.state / 'runner.lock'
        with lock.open('a') as held:
            fcntl.flock(held.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            before = self.snapshot()
            result = self.run_cli()
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(self.output_json(result)['state'], 'unavailable')
            self.assertEqual(self.snapshot(), before)


if __name__ == '__main__':
    unittest.main()
