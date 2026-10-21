"""Synthetic RED contract for one-way Krisp/Granola transcript intake.

AC1 source allowlist + lossless canonical notes; AC2 stable identity/recovery;
AC3 existing-ID dedup/conflict safety; EC1 untrusted input/path boundaries;
ERR1 atomic publish/state/locking; DRY1 dry-run must perform zero writes.
No private vaults, provider services, network, Git or model calls.
"""
from __future__ import annotations

import hashlib
import importlib.util
import os
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

MODULE_PATH = Path(__file__).resolve().parents[1] / 'transcript_intake.py'
if MODULE_PATH.is_file():
    spec = importlib.util.spec_from_file_location('transcript_intake_contract_target', MODULE_PATH)
    INTAKE = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(INTAKE)
else:
    INTAKE = None

TEXT = 'Synthetic planning meeting\nSpeaker A: Review the lighthouse milestone.\n'


class TranscriptIntakeTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(INTAKE, 'RED: transcript_intake.py is not implemented')
        self.assertTrue(callable(getattr(INTAKE, 'import_transcript_exports', None)),
                        'RED: import_transcript_exports is missing')
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.vault = self.base / 'FixtureVault'
        self.vault.mkdir()
        self.inbox = self.base / 'ManualExports'
        self.inbox.mkdir()
        self.state = self.base / 'PrivateRuntime' / 'intake.json'
        self.state.parent.mkdir()

    def source(self, relative='krisp/meeting.txt', text=TEXT):
        p = self.inbox / relative
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding='utf-8')
        return p

    def run_import(self, dry_run=False):
        result = INTAKE.import_transcript_exports(self.vault, self.inbox, self.state, dry_run=dry_run)
        self.assertIsInstance(result, dict)
        for key in ('imported', 'already_present', 'conflicts', 'unsupported'):
            self.assertIsInstance(result[key], int)
            self.assertGreaterEqual(result[key], 0)
        return result

    def refused(self):
        try:
            return self.run_import()
        except (OSError, ValueError, RuntimeError):
            return None

    def notes(self):
        return sorted(self.vault.rglob('*.md'))

    def files(self, root=None):
        root = root or self.base
        return {str(p.relative_to(root)): (p.read_bytes(), p.stat().st_mtime_ns)
                for p in root.rglob('*') if p.is_file() and not p.is_symlink()}

    def test_ac1_krisp_and_granola_preserve_original_and_record_source_hash(self):
        first = self.source()
        second = self.source('granola/export.md', '# Synthetic second meeting\nFull original body\n')
        before = self.files(self.inbox)
        result = self.run_import()
        self.assertEqual(result['imported'], 2)
        self.assertEqual(len(self.notes()), 2)
        for source, path in [('krisp', first), ('granola', second)]:
            notes = list((self.vault / '00-Inbox' / source).glob('*.md'))
            self.assertEqual(len(notes), 1)
            text = notes[0].read_text()
            self.assertIn(path.read_text(), text)
            self.assertIn('source: ' + source, text)
            self.assertIn('import_sha256:', text)
            self.assertIn(hashlib.sha256(path.read_bytes()).hexdigest(), text)
            self.assertNotIn('meeting', notes[0].stem, 'Use stable ID, not source filename')
        self.assertEqual(self.files(self.inbox), before)
        self.assertTrue(self.state.is_file())

    def test_ac2_repeat_and_renamed_identical_export_create_no_duplicate(self):
        src = self.source()
        self.assertEqual(self.run_import()['imported'], 1)
        before = self.files(self.vault)
        second = self.run_import()
        self.assertEqual(second['imported'], 0)
        self.assertEqual(second['already_present'], 1)
        src.rename(src.with_name('renamed-export.txt'))
        third = self.run_import()
        self.assertEqual(third['imported'], 0)
        self.assertEqual(third['already_present'], 1)
        self.assertEqual(self.files(self.vault), before)

    def test_ac2_same_bytes_from_distinct_sources_keep_source_identity(self):
        self.source('krisp/a.txt')
        self.source('granola/a.txt')
        self.assertEqual(self.run_import()['imported'], 2)
        self.assertEqual(len(self.notes()), 2)
        self.assertEqual({p.parent.name for p in self.notes()}, {'krisp', 'granola'})

    def test_ac2_crash_after_note_before_state_recovers_from_note_hash(self):
        self.source()
        self.run_import()
        before = self.files(self.vault)
        self.state.unlink()  # Represents successful publish followed by lost state write.
        result = self.run_import()
        self.assertEqual(result['imported'], 0)
        self.assertEqual(result['already_present'], 1)
        self.assertEqual(self.files(self.vault), before)
        self.assertTrue(self.state.is_file(), 'Recovered import should rebuild durable state')

    def test_ac3_existing_upstream_note_after_move_is_not_imported_again(self):
        self.source('krisp/a.md', '---\nmeeting_id: synthetic-krisp-1\n---\n' + TEXT)
        self.run_import()
        existing = self.notes()[0]
        moved = self.vault / '10-Transcripts' / 'organized.md'
        moved.parent.mkdir()
        existing.rename(moved)
        self.state.unlink()
        before = self.files(self.vault)
        result = self.run_import()
        self.assertEqual(result['already_present'], 1)
        self.assertEqual(result['imported'], 0)
        self.assertEqual(self.files(self.vault), before)

    def test_ac3_preexisting_upstream_id_different_body_is_visible_conflict(self):
        existing = self.vault / '10-Transcripts' / 'existing.md'
        existing.parent.mkdir()
        existing.write_text('---\nsource: granola\ngranola_id: synthetic-g-1\n---\nOlder distinct body')
        self.source('granola/new.md', '---\ngranola_id: synthetic-g-1\n---\nNew distinct body')
        before_vault, before_source = self.files(self.vault), self.files(self.inbox)
        result = self.run_import()
        self.assertEqual(result['imported'], 0)
        self.assertEqual(result['conflicts'], 1)
        self.assertEqual(self.files(self.vault), before_vault)
        self.assertEqual(self.files(self.inbox), before_source)

    def test_ac3_changed_export_same_upstream_id_keeps_existing_note(self):
        src = self.source('krisp/a.md', '---\nmeeting_id: synthetic-k-2\n---\n' + TEXT)
        self.run_import()
        before = self.files(self.vault)
        src.write_text('---\nmeeting_id: synthetic-k-2\n---\nChanged upstream version')
        result = self.run_import()
        self.assertEqual(result['imported'], 0)
        self.assertEqual(result['conflicts'], 1)
        self.assertEqual(self.files(self.vault), before)

    def test_ec1_unknown_extensions_large_invalid_utf8_and_symlinks_reported(self):
        self.source('krisp/ok.txt')
        self.source('krisp/not-supported.pdf', 'Synthetic non-PDF')
        self.source('granola/oversized.txt', 'L' * (2 * 1024 * 1024 + 1))
        self.source('granola/broken.txt').write_bytes(b'\xff\xfe')
        outside = self.base / 'outside.txt'
        outside.write_text('NEVER_READ_OUTSIDE')
        (self.inbox / 'krisp' / 'linked.txt').symlink_to(outside)
        (self.inbox / 'granola' / 'linked-directory').symlink_to(self.base, target_is_directory=True)
        result = self.run_import()
        self.assertEqual(result['imported'], 1)
        self.assertGreaterEqual(result['unsupported'] + result['conflicts'], 5)
        self.assertNotIn('NEVER_READ_OUTSIDE', ''.join(p.read_text() for p in self.notes()))

    def test_ec1_unrelated_source_and_vault_folders_are_never_read(self):
        self.source()
        excluded = self.source('other/secret.md', 'UNRELATED_SECRET')
        private = self.vault / 'Personal/secret.md'
        private.parent.mkdir()
        private.write_text('UNRELATED_SECRET')
        original_open = Path.open
        def safe_open(path, *args, **kwargs):
            if path in (excluded, private):
                raise AssertionError('Unrelated personal file was opened')
            return original_open(path, *args, **kwargs)
        with patch.object(Path, 'open', safe_open):
            result = self.run_import()
        self.assertEqual(result['imported'], 1)
        self.assertEqual(private.read_text(), 'UNRELATED_SECRET')

    def canonical_existing_fixture(self):
        text = '---\nsource: krisp\nmeeting_id: canonical-fixture-1\n---\n' + TEXT
        self.source('krisp/export.md', text)
        existing = self.vault / '10-Transcripts' / 'already-there.md'
        existing.parent.mkdir()
        existing.write_text(text)
        self.state.write_text(json.dumps({'schema': 1, 'records': {}}))
        return existing

    def test_ec1_unreadable_canonical_note_stops_import_before_duplicate_or_state_write(self):
        existing = self.canonical_existing_fixture()
        source_before, vault_before = self.files(self.inbox), self.files(self.vault)
        state_before = self.state.read_bytes()
        original_read = INTAKE.read
        def unreadable(path):
            if Path(path) == existing:
                raise OSError('Synthetic canonical source read denied')
            return original_read(path)
        with patch.object(INTAKE, 'read', side_effect=unreadable):
            result = self.refused()
        if result is not None:
            self.assertEqual(result['imported'], 0, 'Incomplete identity index cannot authorize new notes')
        self.assertEqual(self.files(self.vault), vault_before)
        self.assertEqual(self.files(self.inbox), source_before)
        self.assertEqual(self.state.read_bytes(), state_before)

    def test_ec1_canonical_directory_enumeration_error_stops_import_before_writes(self):
        existing = self.canonical_existing_fixture()
        source_before, vault_before = self.files(self.inbox), self.files(self.vault)
        state_before = self.state.read_bytes()
        original_scandir = os.scandir
        def unreadable_directory(path):
            if Path(path) == existing.parent:
                raise PermissionError('Synthetic canonical enumeration denied')
            return original_scandir(path)
        with patch('os.scandir', side_effect=unreadable_directory):
            result = self.refused()
        if result is not None:
            self.assertEqual(result['imported'], 0, 'Missing identity coverage cannot authorize duplicate imports')
        self.assertEqual(self.files(self.vault), vault_before)
        self.assertEqual(self.files(self.inbox), source_before)
        self.assertEqual(self.state.read_bytes(), state_before)

    def test_ec1_missing_input_and_vault_fail_closed_without_creating_them(self):
        self.inbox.rmdir()
        self.refused()
        self.assertFalse(self.inbox.exists())
        self.assertFalse(self.state.exists())
        self.assertEqual(self.notes(), [])
        self.inbox.mkdir()
        self.source()
        self.vault.rmdir()
        self.refused()
        self.assertFalse(self.vault.exists())
        self.assertFalse(self.state.exists())

    def test_ec1_malformed_state_container_fails_closed_without_changes(self):
        self.source()
        for invalid in ([], None, {'schema': 1, 'records': []}):
            with self.subTest(invalid=invalid):
                self.state.write_text(json.dumps(invalid))
                state_before = self.state.read_bytes()
                vault_before, source_before = self.files(self.vault), self.files(self.inbox)
                try:
                    result = self.refused()
                    if result is not None:
                        self.assertEqual(result['imported'], 0)
                except (AttributeError, TypeError) as exc:
                    self.fail('Malformed state must fail closed with a bounded error: ' + type(exc).__name__)
                finally:
                    self.assertEqual(self.state.read_bytes(), state_before)
                    self.assertEqual(self.files(self.vault), vault_before)
                    self.assertEqual(self.files(self.inbox), source_before)

    def test_ec2_state_inside_vault_or_intake_is_rejected(self):
        self.source()
        for forbidden in (self.vault / 'state.json', self.inbox / 'state.json'):
            self.state = forbidden
            self.refused()
            self.assertFalse(forbidden.exists())
            self.assertEqual(self.notes(), [])

    def test_ec2_symlink_destination_cannot_write_outside_vault(self):
        self.source()
        outside = self.base / 'outside'
        outside.mkdir()
        (outside / 'sentinel').write_text('preserve')
        (self.vault / '00-Inbox').symlink_to(outside, target_is_directory=True)
        before = self.files(outside)
        self.refused()
        self.assertEqual(self.files(outside), before)
        self.assertFalse(self.state.exists())

    def test_ec2_modified_managed_note_is_preserved_and_conflict_reported(self):
        self.source()
        self.run_import()
        target = self.notes()[0]
        target.write_text('Owner replaced this note; preserve it.')
        before = self.files(self.vault)
        result = self.run_import()
        self.assertEqual(result['imported'], 0)
        self.assertGreaterEqual(result['conflicts'], 1)
        self.assertEqual(self.files(self.vault), before)

    def test_ec2_stored_parent_traversal_refused_before_outside_read(self):
        self.source()
        self.run_import()
        outside = self.base / 'outside.md'
        outside.write_text('OUTSIDE PRIVATE CONTENT')
        data = json.loads(self.state.read_text())
        key = next(iter(data['records']))
        data['records'][key]['path'] = '../outside.md'
        self.state.write_text(json.dumps(data))
        state_before = self.state.read_bytes()
        vault_before = self.files(self.vault)
        original_read = INTAKE.read
        def guarded_read(path):
            if Path(path).resolve() == outside.resolve():
                raise AssertionError('Traversal record caused outside read')
            return original_read(path)
        with patch.object(INTAKE, 'read', side_effect=guarded_read):
            result = self.refused()
        if result is not None:
            self.assertGreaterEqual(result['conflicts'], 1)
        self.assertEqual(self.state.read_bytes(), state_before)
        self.assertEqual(self.files(self.vault), vault_before)
        self.assertEqual(outside.read_text(), 'OUTSIDE PRIVATE CONTENT')

    def test_ec2_source_and_destination_ancestor_symlinks_refused(self):
        self.source()
        alias = self.base / 'ancestor-alias'
        alias.symlink_to(self.base, target_is_directory=True)
        original_vault, original_inbox = self.vault, self.inbox
        original_read = INTAKE.read
        for mode in ('source', 'destination'):
            with self.subTest(mode=mode):
                self.vault = alias / original_vault.name if mode == 'destination' else original_vault
                self.inbox = alias / original_inbox.name if mode == 'source' else original_inbox
                before = self.files()
                def guarded_read(path):
                    if str(path).startswith(str(alias) + os.sep):
                        raise AssertionError('Ancestor symlink was traversed for a read')
                    return original_read(path)
                with patch.object(INTAKE, 'read', side_effect=guarded_read):
                    result = self.refused()
                if result is not None:
                    self.assertEqual(result['imported'], 0)
                    self.assertGreaterEqual(result['conflicts'] + result['unsupported'], 1)
                self.assertEqual(self.files(), before, 'Unsafe root must fail before outside writes')
                self.assertFalse(self.state.exists())
        self.vault, self.inbox = original_vault, original_inbox

    def test_ec1_fifo_source_rejected_without_opening_or_blocking(self):
        folder = self.inbox / 'krisp'
        folder.mkdir()
        fifo = folder / 'untrusted.txt'
        os.mkfifo(fifo)
        original_read = INTAKE.read
        def guarded_read(path):
            if Path(path) == fifo:
                raise AssertionError('Nonregular file must be rejected before a potentially blocking read')
            return original_read(path)
        with patch.object(INTAKE, 'read', side_effect=guarded_read):
            result = self.run_import()
        self.assertEqual(result['imported'], 0)
        self.assertGreaterEqual(result['unsupported'], 1)
        self.assertEqual(self.notes(), [])

    def test_dry1_dry_run_creates_no_note_state_directory_or_lock(self):
        self.source()
        self.state.parent.rmdir()
        before = self.files()
        dirs_before = {str(p.relative_to(self.base)) for p in self.base.rglob('*')}
        result = self.run_import(dry_run=True)
        self.assertIsInstance(result, dict)
        self.assertEqual(self.files(), before)
        self.assertEqual({str(p.relative_to(self.base)) for p in self.base.rglob('*')}, dirs_before)
        self.assertFalse(self.state.exists())

    def test_err1_lock_contention_performs_no_import_or_state_write(self):
        self.source()
        with patch('fcntl.flock', side_effect=BlockingIOError('Synthetic lock contention')) as lock:
            self.refused()
        self.assertTrue(lock.called)
        self.assertEqual(self.notes(), [])
        self.assertFalse(self.state.exists())

    def test_err1_failed_state_replace_preserves_previous_valid_state_and_recovers(self):
        self.source('krisp/first.txt')
        self.run_import()
        state_before = self.state.read_bytes()
        notes_before = self.files(self.vault)
        self.source('granola/second.txt', 'Second synthetic meeting')
        original_replace = os.replace
        def fail_state_replace(src, dst, *args, **kwargs):
            if Path(dst) == self.state:
                raise OSError('Synthetic interruption writing state')
            return original_replace(src, dst, *args, **kwargs)
        with patch('os.replace', side_effect=fail_state_replace):
            self.refused()
        self.assertEqual(self.state.read_bytes(), state_before)
        for relative, pair in notes_before.items():
            self.assertEqual((self.vault / relative).read_bytes(), pair[0])
        self.run_import()
        self.assertEqual(len(self.notes()), 2)
        self.assertEqual(self.run_import()['imported'], 0)


if __name__ == '__main__':
    unittest.main()
