"""Locked context-library contract, synthetic fixtures only.

AC1: scope/source dates/declared projects; AC2: identity and conflicts;
AC3: idempotent managed export; AC4: private projection and owner HTTP gate;
EC1: unavailable/oversized/symlink bounds; EC2: collision/path/URL rejection;
ERR1: atomic failure, exclusive lock, missing roots. No live services or notes.
"""
from __future__ import annotations

import hashlib
import importlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

try:
    LIB = importlib.import_module('dashboard_builder.context_library')
except ModuleNotFoundError as exc:
    if exc.name != 'dashboard_builder.context_library':
        raise
    LIB = None

NOW = '2026-10-21T08:00:00Z'
BODY = '# Synthetic meeting\nDecision: synthetic lighthouse launch.\n'
RID = 'a' * 32


def record(**changes):
    item = dict(id=RID, kind='transcript', source='plaud', source_id='fixture-1',
                title='Synthetic planning', date='2026-10-12', modified_at=NOW,
                project='Synthetic project', relative_path='10-Transcripts/meeting.md',
                obsidian_url='obsidian://open?vault=Fixture&file=10-Transcripts%2Fmeeting',
                sha256=hashlib.sha256(BODY.encode()).hexdigest(), body=BODY)
    item.update(changes)
    return item


def catalog(*items, **changes):
    data = dict(schema=1, generated_at=NOW, state='ready', records=list(items),
                sources=[dict(source='plaud', state='observed'),
                         dict(source='granola', state='not_observed')], issues=[])
    data.update(changes)
    return data


class FixtureCase(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(LIB, 'RED: dashboard_builder.context_library is not implemented')
        for name in ('build_catalog', 'export_catalog', 'context_library_projection'):
            self.assertTrue(callable(getattr(LIB, name, None)), 'RED: missing ' + name)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.vault = self.base / 'Fixture'
        self.vault.mkdir()
        self.output = self.base / 'Drive'
        self.output.mkdir()
        self.state = self.base / 'private' / 'manifest.json'
        self.state.parent.mkdir()
        self.snapshot = self.base / 'catalog.json'

    def note(self, relative, content=BODY):
        path = self.vault / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')
        return path

    def build(self, previous=None):
        return LIB.build_catalog(self.vault, previous=previous, now=NOW)

    def export(self, data):
        return LIB.export_catalog(data, self.output, self.state)

    def project(self, data=None, **options):
        if data is not None:
            self.snapshot.write_text(json.dumps(data), encoding='utf-8')
        return LIB.context_library_projection(self.snapshot, owner=True, now=NOW, **options)

    def payload_files(self):
        return sorted(p for p in self.output.rglob('*.txt') if p.name.endswith(RID[:8] + '.txt'))

    def contents(self):
        return {str(p.relative_to(self.output)): p.read_bytes()
                for p in self.output.rglob('*') if p.is_file()}

    def refused_export(self, data):
        # Error-result and explicit bounded exception are both valid fail-closed APIs.
        try:
            self.export(data)
        except (ValueError, OSError, RuntimeError):
            pass


class CollectorTests(FixtureCase):
    def test_ac1_only_allowlisted_markdown_and_declared_metadata(self):
        text = '---\nsource: plaud\nplaud_id: fixture-101\ntitle: "Fixture call"\ndate: 2026-09-03\nproject: "Declared project"\n---\n' + BODY
        self.note('00-Inbox/plaud/call.md', text)
        self.note('90-Operations/project-update-webhook/logs/event.md', '---\nwriteback_id: fixture-update\n---\nSynthetic update')
        self.note('10-Transcripts/Project X name.md')
        self.note('Personal/secret.md', 'NEVER_SCAN_THIS')
        self.note('00-Inbox/other/secret.md', 'NEVER_SCAN_THIS')
        self.note('10-Transcripts/.hidden/secret.md', 'NEVER_SCAN_THIS')
        self.note('10-Transcripts/raw.txt', 'NEVER_SCAN_THIS')
        out = self.build()
        self.assertEqual(out['schema'], 1)
        self.assertEqual(len(out['records']), 3)
        self.assertNotIn('NEVER_SCAN_THIS', json.dumps(out))
        meeting = next(r for r in out['records'] if r['source_id'] == 'fixture-101')
        self.assertEqual((meeting['source'], meeting['title'], meeting['date'], meeting['project']),
                         ('plaud', 'Fixture call', '2026-09-03', 'Declared project'))
        self.assertEqual(meeting['body'], text)
        self.assertNotEqual(meeting['modified_at'][:10], meeting['date'])
        self.assertEqual(next(r for r in out['records'] if r['relative_path'].endswith('Project X name.md'))['project'], '')
        self.assertEqual(next(r for r in out['records'] if r['source_id'] == 'fixture-update')['kind'], 'update')
        for item in out['records']:
            self.assertRegex(item['id'], r'^[a-f0-9]{32}$')
        granola = next(s for s in out['sources'] if s.get('source', s.get('id')) == 'granola')
        self.assertIn('not_observed', granola.values())

    def test_ac2_upstream_id_survives_move_and_content_edit(self):
        path = self.note('00-Inbox/krisp/old.md', '---\nmeeting_id: fixture-krisp\n---\nOld body')
        before = self.build()
        path.unlink()
        self.note('00-Inbox/krisp/new.md', '---\nmeeting_id: fixture-krisp\n---\nEdited body')
        after = self.build(before)
        self.assertEqual(after['records'][0]['id'], before['records'][0]['id'])
        self.assertIn('Edited body', after['records'][0]['body'])

    def test_ac2_placeholder_writeback_id_is_not_shared_identity_and_prior_ids_survive(self):
        first_path = '90-Operations/project-update-webhook/logs/first.md'
        second_path = '90-Operations/project-update-webhook/logs/second.md'
        self.note(first_path, '---\nwriteback_id: manual-fallback\n---\nFirst distinct synthetic update')
        self.note(second_path, '---\nwriteback_id: manual-fallback\n---\nSecond distinct synthetic update')
        # Earlier catalogs treated this importer placeholder as a genuine upstream
        # ID. Their persisted export identities must remain stable during repair.
        prior = catalog(record(id='c' * 32, kind='update', source='project-update',
                               source_id='manual-fallback', relative_path=first_path),
                        record(id='d' * 32, kind='update', source='project-update',
                               source_id='manual-fallback', relative_path=second_path))
        for previous in (None, prior):
            with self.subTest(has_previous=previous is not None):
                result = self.build(previous)
                self.assertEqual(len(result['records']), 2)
                self.assertEqual(len({r['id'] for r in result['records']}), 2)
                self.assertNotIn('upstream_content_conflict', result['issues'])
                self.assertEqual(result['state'], 'ready')
                self.assertEqual({r['source_id'] for r in result['records']}, {''})
                if previous is not None:
                    self.assertEqual({r['relative_path']: r['id'] for r in result['records']},
                                     {first_path: 'c' * 32, second_path: 'd' * 32})

    def test_ac2_fallback_identity_survives_edit_and_unique_body_move(self):
        path = self.note('10-Transcripts/a.md')
        first = self.build()
        path.write_text(BODY + 'edited')
        edited = self.build(first)
        self.assertEqual(edited['records'][0]['id'], first['records'][0]['id'])
        path.rename(path.with_name('renamed.md'))
        moved = self.build(edited)
        self.assertEqual(moved['records'][0]['id'], edited['records'][0]['id'])

    def test_ac2_upstream_duplicate_collapses_but_conflict_keeps_both(self):
        body = '---\nplaud_id: shared-fixture-id\n---\nSame body'
        self.note('00-Inbox/plaud/a.md', body)
        other = self.note('00-Inbox/plaud/b.md', body)
        self.assertEqual(len(self.build()['records']), 1)
        other.write_text(body + '\nDifferent version')
        out = self.build()
        self.assertEqual(len(out['records']), 2)
        self.assertEqual(len({r['id'] for r in out['records']}), 2)
        self.assertEqual(out['state'], 'partial')
        self.assertTrue(out['issues'])

    def test_ec1_symlink_dotfolder_and_oversized_sources_not_read(self):
        outside = self.base / 'outside.md'
        outside.write_text('OUTSIDE_PRIVATE_MARKER')
        self.note('10-Transcripts/good.md')
        (self.vault / '10-Transcripts/link.md').symlink_to(outside)
        (self.vault / '00-Inbox').mkdir()
        (self.vault / '00-Inbox/granola').symlink_to(self.base, target_is_directory=True)
        self.note('10-Transcripts/large.md', 'L' * (2 * 1024 * 1024 + 1))
        self.note('10-Transcripts/bad.md').write_bytes(b'\xff\xfe')
        out = self.build()
        self.assertEqual([r['relative_path'] for r in out['records']], ['10-Transcripts/good.md'])
        self.assertIn(out['state'], ('partial', 'unavailable'))
        self.assertNotIn('OUTSIDE_PRIVATE_MARKER', json.dumps(out))

    def test_ec1_previously_populated_vault_with_missing_roots_is_unavailable(self):
        path = self.note('10-Transcripts/previous.md')
        previous = self.build()
        self.assertTrue(previous['records'])
        path.unlink()
        path.parent.rmdir()
        result = self.build(previous)
        self.assertEqual(result['state'], 'unavailable',
                         'Missing previously available roots cannot look like a healthy empty vault')
        self.assertTrue(result['issues'])

    def test_ac1_update_history_window_keeps_newest_200_honestly(self):
        for i in range(205):
            note = self.note('90-Operations/project-update-webhook/logs/event-%04d.md' % i,
                             '---\nwriteback_id: update-%04d\n---\nSynthetic update %d' % (i, i))
            os.utime(note, (1700000000 + i, 1700000000 + i))
        out = self.build()
        updates = [r for r in out['records'] if r['kind'] == 'update']
        self.assertEqual(len(updates), 200)
        self.assertEqual({r['source_id'] for r in updates},
                         {'update-%04d' % i for i in range(5, 205)})
        self.assertEqual(out['state'], 'ready', 'Intentional history window is not an error')
        self.assertIn('history_scope', out, 'A bounded update view must declare its scope')

    def test_ec1_missing_vault_and_record_cap_are_honest(self):
        absent = LIB.build_catalog(self.base / 'missing', now=NOW)
        self.assertEqual(absent['state'], 'unavailable')
        for i in range(2001):
            self.note('10-Transcripts/n%04d.md' % i, 'Synthetic %d' % i)
        bounded = self.build()
        self.assertLessEqual(len(bounded['records']), 2000)
        self.assertEqual(bounded['state'], 'partial')
        self.assertTrue(bounded['issues'])


class ExportTests(FixtureCase):
    def test_ac3_repeat_export_keeps_bytes_mtimes_and_source_untouched(self):
        source = self.note('10-Transcripts/source.md')
        data = catalog(record())
        self.export(data)
        target = self.output / 'Транскрипты' / '2026' / ('2026-10-12 — Synthetic planning — plaud — ' + RID[:8] + '.txt')
        self.assertTrue(target.is_file())
        text = target.read_text()
        for value in (BODY, '2026-10-12', NOW, record()['obsidian_url']):
            self.assertIn(value, text)
        self.assertTrue((self.output / '00 — Каталог.csv').is_file())
        self.assertTrue((self.output / '00 — Последние обновления.txt').is_file())
        before = self.contents()
        mtimes = {p: (self.output / p).stat().st_mtime_ns for p in before}
        self.export(data)
        self.assertEqual(self.contents(), before)
        self.assertEqual({p: (self.output / p).stat().st_mtime_ns for p in before}, mtimes)
        self.assertEqual(source.read_text(), BODY)
        self.assertTrue(self.state.is_file())

    def test_ac3_edit_date_title_and_path_updates_same_export_no_pruning(self):
        self.export(catalog(record()))
        initial = self.payload_files()
        self.assertEqual(len(initial), 1)
        changed = record(title='Renamed', date='2025-01-01', relative_path='10-Transcripts/new.md',
                         body=BODY + 'Change', sha256=hashlib.sha256((BODY + 'Change').encode()).hexdigest())
        self.export(catalog(changed))
        self.assertEqual(self.payload_files(), initial)
        self.assertIn('Change', initial[0].read_text())
        self.export(catalog())
        self.assertTrue(initial[0].exists(), 'Missing source must never prune a prior export')

    def test_ac3_update_unknown_date_uses_separate_undated_directory(self):
        self.export(catalog(record(kind='update', source='project-update', date='')))
        files = list((self.output / 'Обновления' / 'Без даты').glob('*.txt'))
        self.assertEqual(len(files), 1)
        self.assertIn('Synthetic planning', files[0].name)
        self.assertTrue(files[0].name.endswith(RID[:8] + '.txt'))

    def test_ec2_unknown_existing_and_user_edited_destination_preserved(self):
        destination = self.output / 'Транскрипты/2026' / ('2026-10-12 — Synthetic planning — plaud — ' + RID[:8] + '.txt')
        destination.parent.mkdir(parents=True)
        destination.write_text('User existing file')
        self.refused_export(catalog(record()))
        self.assertEqual(destination.read_text(), 'User existing file')
        destination.unlink()
        self.export(catalog(record()))
        destination.write_text('Owner edit must survive')
        self.refused_export(catalog(record(body=BODY + 'new')))
        self.assertEqual(destination.read_text(), 'Owner edit must survive')

    def test_ec2_manifest_cannot_map_multiple_ids_or_reserved_catalog_to_record(self):
        for case in ('same-destination', 'reserved-catalog'):
            with self.subTest(case=case):
                self.output = self.base / case
                self.output.mkdir()
                self.state = self.base / 'private' / (case + '.json')
                self.export(catalog(record()))
                altered = json.loads(self.state.read_text())
                first_path = altered['records'][RID]
                altered['records'] = ({RID: first_path, 'b' * 32: first_path}
                                      if case == 'same-destination'
                                      else {RID: '00 — Каталог.csv'})
                self.state.write_text(json.dumps(altered))
                before = self.contents()
                state_before = self.state.read_bytes()
                incoming = catalog(record(), record(id='b' * 32, body='Another synthetic record'))
                try:
                    result = self.export(incoming)
                except (ValueError, OSError, RuntimeError):
                    pass
                else:
                    self.assertIn(result.get('state'), ('conflict', 'unavailable', 'blocked'),
                                  'Unsafe manifest must be rejected before export')
                self.assertEqual(self.contents(), before)
                self.assertEqual(self.state.read_bytes(), state_before)

    def test_ec2_readable_title_is_bounded_and_cannot_escape_export_directory(self):
        title = '../../outside/secret\\name ' + 'L' * 150
        self.export(catalog(record(title=title)))
        files = self.payload_files()
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0].parent, self.output / 'Транскрипты' / '2026')
        self.assertLessEqual(len(files[0].name), 140, 'Sanitized title must be bounded to80 characters')
        self.assertNotIn('\\', files[0].name)
        self.assertEqual(len(files[0].relative_to(self.output).parts), 3)

    def test_ec1_partial_export_summary_declares_scope_and_reason_codes(self):
        data = catalog(record(), state='partial', issues=['source_unreadable'],
                       history_scope={'updates_limit': 200, 'transcripts_limit': 2000})
        self.export(data)
        summary = (self.output / '00 — Последние обновления.txt').read_text()
        self.assertIn('partial', summary.lower())
        self.assertIn('source_unreadable', summary)
        self.assertIn('200', summary, 'Readers need the bounded update history scope')

    def test_ec2_export_rejects_malicious_identity_and_symlink_output(self):
        outside = self.base / 'outside'
        outside.mkdir()
        (outside / 'sentinel').write_text('untouched')
        (self.output / 'Транскрипты').symlink_to(outside, target_is_directory=True)
        self.refused_export(catalog(record()))
        self.assertEqual(sorted(p.name for p in outside.iterdir()), ['sentinel'])
        (self.output / 'Транскрипты').unlink()
        self.refused_export(catalog(record(id='../../escaped')))
        self.assertFalse((self.base / 'escaped.txt').exists())
        self.assertFalse(list(self.output.rglob('escaped*')))

    def test_err1_missing_roots_and_unavailable_catalog_write_nothing(self):
        self.output.rmdir()
        self.refused_export(catalog(record()))
        self.assertFalse(self.output.exists())
        self.assertFalse(self.state.exists())
        self.output.mkdir()
        self.state.parent.rmdir()
        self.refused_export(catalog(record()))
        self.assertEqual(self.contents(), {})
        self.assertFalse(self.state.parent.exists())
        self.state.parent.mkdir()
        self.export(catalog(record(), state='unavailable'))
        self.assertEqual(self.contents(), {})
        self.assertFalse(self.state.exists())

    def test_err1_interrupted_atomic_replace_preserves_previous_export(self):
        self.export(catalog(record()))
        before = self.contents()
        state_before = self.state.read_bytes()
        with patch('os.replace', side_effect=OSError('Synthetic interrupted replacement')):
            self.refused_export(catalog(record(body=BODY + 'new')))
        for path, content in before.items():
            self.assertEqual((self.output / path).read_bytes(), content)
        self.assertEqual(self.state.read_bytes(), state_before)

    def interrupt_manifest(self, data):
        original_replace = os.replace
        def interrupted(src, dst, *args, **kwargs):
            if Path(dst).resolve() == self.state.resolve():
                raise OSError('Synthetic crash after export publication, before manifest')
            return original_replace(src, dst, *args, **kwargs)
        with patch('os.replace', side_effect=interrupted):
            self.refused_export(data)

    def test_err1_new_export_published_before_manifest_recovers_without_duplicate(self):
        data = catalog(record())
        self.interrupt_manifest(data)
        paths = self.payload_files()
        self.assertEqual(len(paths), 1, 'Fault must occur after the note export was published')
        self.assertFalse(self.state.exists())
        self.export(data)
        self.assertEqual(self.payload_files(), paths)
        self.assertTrue(self.state.is_file())
        before = self.contents()
        self.export(data)
        self.assertEqual(self.contents(), before)

    def test_err1_changed_export_published_before_manifest_recovers(self):
        self.export(catalog(record()))
        state_before = self.state.read_bytes()
        changed = catalog(record(body=BODY + 'Recovered change'))
        self.interrupt_manifest(changed)
        self.assertIn('Recovered change', self.payload_files()[0].read_text())
        self.assertEqual(self.state.read_bytes(), state_before)
        self.export(changed)
        self.assertNotEqual(self.state.read_bytes(), state_before)
        self.assertEqual(len(self.payload_files()), 1)

    def test_err1_recovery_does_not_adopt_user_edit_after_interrupted_export(self):
        data = catalog(record())
        self.interrupt_manifest(data)
        target = self.payload_files()[0]
        target.write_text('Owner edited while exporter was interrupted')
        self.refused_export(data)
        self.assertEqual(target.read_text(), 'Owner edited while exporter was interrupted')
        self.assertFalse(self.state.exists(), 'A conflicting recovery cannot mark the export as managed')

    def test_err1_exclusive_lock_contention_writes_nothing(self):
        with patch('fcntl.flock', side_effect=BlockingIOError('Synthetic concurrent writer')) as lock:
            self.refused_export(catalog(record()))
        self.assertTrue(lock.called, 'Exporter must acquire an exclusive POSIX file lock')
        self.assertEqual(self.contents(), {})
        self.assertFalse(self.state.exists())


class ProjectionTests(FixtureCase):
    def test_ac4_anonymous_does_not_stat_open_or_read(self):
        with patch.object(Path, 'stat', side_effect=AssertionError('private stat')), \
             patch.object(Path, 'open', side_effect=AssertionError('private open')), \
             patch('builtins.open', side_effect=AssertionError('private open')):
            self.assertEqual(LIB.context_library_projection(self.snapshot),
                             {'state': 'owner_required', 'records': []})

    def test_ac4_search_filter_index_and_exact_plain_text_detail(self):
        secret_body = '<script>alert("synthetic")</script>\nLighthouse decision'
        first = record(body=secret_body)
        second = record(id='b' * 32, source='krisp', title='Other meeting', body='Different body', project='Other')
        data = catalog(first, second)
        out = self.project(data, query='LIGHTHOUSE', source='plaud', kind='transcript')
        self.assertEqual(out['total'], 1)
        self.assertEqual([r['id'] for r in out['records']], [RID])
        for key in ('body', 'relative_path', 'source_id'):
            self.assertNotIn(key, out['records'][0])
        detail = self.project(record_id=RID)
        item = detail.get('record')
        self.assertIsInstance(item, dict, 'Detail response supplies record')
        self.assertEqual(item['body'], secret_body, 'Body is plain original text, not executed/rendered HTML')
        self.assertEqual(item['id'], RID)
        self.assertEqual(self.project(query='declared-nonexistent')['total'], 0)
        self.assertEqual(self.project(query='Synthetic project')['total'], 1)

    def test_ac4_index_cap_staleness_and_source_date_separation(self):
        items = [record(id='%032x' % i, title='Fixture %d' % i) for i in range(105)]
        out = self.project(catalog(*items, generated_at='2026-10-21T06:00:00Z'))
        self.assertEqual(out['state'], 'stale')
        self.assertEqual(out['total'], 105)
        self.assertLessEqual(len(out['records']), 100)
        self.assertEqual(out['records'][0]['date'], '2026-10-12')
        self.assertEqual(out['records'][0]['modified_at'], NOW)

    def test_ec1_bad_missing_oversized_or_symlink_catalog_is_unavailable(self):
        self.assertEqual(self.project()['state'], 'unavailable')
        for data in ([], {'schema': 99}, catalog(records='invalid')):
            out = self.project(data)
            self.assertEqual(out['state'], 'unavailable')
            self.assertEqual(out['records'], [])
        self.snapshot.write_bytes(b'\xff\xfe')
        self.assertEqual(self.project()['state'], 'unavailable')
        self.snapshot.write_bytes(b' ' * (32 * 1024 * 1024 + 1))
        self.assertEqual(self.project()['state'], 'unavailable')
        other = self.base / 'private-real.json'
        other.write_text(json.dumps(catalog(record())))
        self.snapshot.unlink()
        self.snapshot.symlink_to(other)
        self.assertEqual(self.project()['state'], 'unavailable')

    def test_ec2_invalid_detail_ids_and_unsafe_obsidian_urls_do_not_leak(self):
        self.project(catalog(record()))
        for identifier in ('../private', 'A' * 32, 'z' * 32, 'b' * 32, '', '/etc/passwd'):
            out = self.project(record_id=identifier)
            self.assertEqual(out['state'], 'not_found')
            self.assertNotIn(BODY, json.dumps(out))
        for url in ('javascript:alert(1)', 'file:///private/fixture',
                    'obsidian://open?path=/private/fixture',
                    'obsidian://open?vault=Fixture&file=../../private',
                    'obsidian://open?vault=Fixture&file=%2E%2E%2Fprivate'):
            out = self.project(catalog(record(obsidian_url=url)))
            self.assertNotIn(url, json.dumps(out), 'Unsafe URI must not be projected')


class EndpointTests(unittest.TestCase):
    def setUp(self):
        builder = Path(__file__).resolve().parents[1]
        spec = importlib.util.spec_from_file_location('context_endpoint_fixture', builder / 'dashboard-server-m4.py')
        self.server = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.server)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.catalog_path = self.home / '.agent-bridge/context-library/catalog.json'
        self.catalog_path.parent.mkdir(parents=True)
        self.catalog_path.write_text(json.dumps(catalog(record())))

    def call(self, host='localhost:7777', owner=False):
        handler = self.server.Handler.__new__(self.server.Handler)
        handler.path, handler.command = '/api/context-library', 'GET'
        handler.headers = {'Host': host}
        handler.wfile = io.BytesIO()
        response = {'headers': {}}
        handler.send_response = lambda status, *args: response.update(status=status)
        handler.send_header = lambda key, value: response['headers'].update({key.lower(): str(value)})
        handler.end_headers = lambda: None
        handler.send_error = lambda status, *args: response.update(status=status)
        with patch.object(self.server, 'HOME', self.home), \
             patch.object(self.server.Handler, '_decision_owner_authorized', return_value=owner) as strict, \
             patch.object(self.server.subprocess, 'Popen') as process:
            handler.do_GET()
            process.assert_not_called()
        response['body'] = handler.wfile.getvalue().decode()
        response['strict_called'] = strict.called
        return response

    def test_ac4_http_every_host_requires_strict_owner_no_store(self):
        for host in ('localhost:7777', '127.0.0.1:7777', 'command.example.invalid'):
            with self.subTest(host=host):
                result = self.call(host=host)
                self.assertTrue(result['strict_called'], 'RED: /api/context-library must call strict owner authorization')
                self.assertEqual(json.loads(result['body']), {'state': 'owner_required', 'records': []})
                self.assertIn('no-store', result['headers'].get('cache-control', ''))

    def test_ac4_http_owner_can_get_synthetic_catalog_without_source_body(self):
        result = self.call(owner=True)
        self.assertTrue(result['strict_called'], 'RED: /api/context-library route is missing')
        self.assertEqual(result['status'], 200)
        out = json.loads(result['body'])
        self.assertEqual([r['id'] for r in out['records']], [RID])
        self.assertNotIn(BODY, result['body'])
        self.assertIn('no-store', result['headers'].get('cache-control', ''))


if __name__ == '__main__':
    unittest.main()
