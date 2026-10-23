"""Independent RED contract tests for unified DOCXX; synthetic data only.

INT-05 / AC-06: private bounded operation projection.
AC-07: isolated missing-message warning versus genuine source failure.
INT-05 / AC-05 / EC-01: owner-only, literal, bounded read-only local search.
"""
from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import quote

from dashboard_builder.docxx import docxx_projection, state_path
from dashboard_builder.docxx_search import docxx_search


NOW = 1792764000
HASH = 'a' * 64
FILE_ID = 'synthetic_document_1234'
BUILDER = Path(__file__).resolve().parents[1]


class PrivateFixture(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.status = {
            'checked_at': NOW - 5, 'phase': 'ready', 'model_calls': 0,
            'catalog': {'status': 'ready', 'documents': 42}, 'results': [],
            'drive_ingress': {'enabled': True, 'status': 'idle', 'pending': 0, 'results': []},
            'review_pending': [],
        }
        for name in ('journal.json', 'drive-ingress-journal.json', 'config.json'):
            self.write(name, {})
        (self.directory / 'runner.lock').touch()

    def write(self, name, data):
        (self.directory / name).write_text(json.dumps(data), encoding='utf-8')

    def projection(self):
        self.write('status.json', self.status)
        return docxx_projection(self.directory, owner=True, now=NOW)


class UnifiedProjectionTests(PrivateFixture):
    def operation(self, **changes):
        return {
            'id': 'synthetic_operation_1', 'state': 'verified', 'sha256': HASH, 'size': 30,
            'source_names': ['original.pdf'], 'source_kinds': ['gmail', 'icloud', 'manual', 'drive'],
            'destination': 'France/Identite/document.pdf', 'cloud_file_id': FILE_ID,
            **changes,
        }

    def snapshot(self, **changes):
        value = {'schema_version': 1, 'producer': 'docxx-operations', 'checked_at': NOW - 5,
                 'counts': {'verified': 1, 'queued': 0}, 'records': [self.operation()],
                 'model_calls': 0, **changes}
        self.write('operations-status.json', value)
        return value

    def test_int05_fresh_operations_are_projected_with_independent_full_counts(self):
        self.snapshot(counts={'verified': 250, 'queued': 7})
        result = self.projection()
        operations = result.get('operations', {})
        self.assertEqual(operations.get('state'), 'ready')
        self.assertEqual(operations.get('counts'), {'verified': 250, 'queued': 7})
        self.assertIsNotNone(operations.get('checked_at'))
        self.assertEqual(len(operations.get('records', [])), 1)
        self.assertEqual(operations['records'][0]['id'], 'synthetic_operation_1')
        self.assertEqual(set(operations['records'][0]['source_kinds']), {'gmail', 'icloud', 'drive', 'manual'})

    def test_ac06_rows_are_bounded_but_counts_cover_the_whole_snapshot(self):
        self.snapshot(counts={'verified': 120}, records=[self.operation(id='synthetic_operation_' + str(i)) for i in range(120)])
        operations = self.projection().get('operations', {})
        self.assertEqual(operations.get('counts', {}).get('verified'), 120)
        self.assertEqual(len(operations.get('records', [])), 100)

    def test_ac06_snapshot_does_not_publish_arbitrary_private_fields(self):
        self.snapshot(records=[self.operation(
            source_names=['/Users/private/original.pdf'], source_key='PRIVATE_SOURCE_KEY',
            destination='/Users/private/state/document.pdf', cloud_file_id='../../PRIVATE_ID',
            details={'token': 'PRIVATE_TOKEN'}, text='PRIVATE_EXTRACTED_TEXT',
            path='/Users/private/state', source_account='PRIVATE_ACCOUNT',
            url='https://evil.invalid/PRIVATE_LINK',
        )], details={'secret': 'PRIVATE_TOPLEVEL'})
        operations = self.projection().get('operations', {})
        self.assertEqual(operations.get('state'), 'ready')
        encoded = json.dumps(operations)
        for marker in ('PRIVATE_', '/Users/private', 'evil.invalid'):
            self.assertNotIn(marker, encoded)
        self.assertNotIn('details', operations)
        for row in operations.get('records', []):
            self.assertTrue(set(row) <= {'id', 'state', 'sha256', 'size', 'source_names', 'source_kinds',
                                        'destination', 'cloud_file_id', 'url', 'checked_at', 'at', 'label'})

    def test_int05_missing_operation_status_is_explicitly_unavailable(self):
        result = self.projection()
        self.assertEqual(result.get('operations', {}).get('state'), 'unavailable')
        self.assertEqual(result.get('state'), 'ready')  # Existing intake remains independently healthy.

    def test_int05_stale_future_and_invalid_timestamps_never_claim_live_operations(self):
        for stamp in (NOW - 901, NOW + 1, None, 'invalid', float('nan'), True):
            with self.subTest(stamp=stamp):
                self.snapshot(checked_at=stamp)
                self.assertIn(self.projection().get('operations', {}).get('state'), {'stale', 'unavailable'})

    def test_int05_snapshot_accepts_the_900_second_freshness_boundary(self):
        self.snapshot(checked_at=NOW - 900)
        self.assertEqual(self.projection().get('operations', {}).get('state'), 'ready')

    def test_ac06_foreign_schema_and_malformed_counts_fail_closed(self):
        for changes in ({'schema_version': 2}, {'schema_version': True}, {'producer': 'foreign'},
                        {'counts': {'verified': -1}}, {'counts': {'verified': True}},
                        {'counts': []}, {'records': {}}, {'records': 'PRIVATE_ROWS'}):
            with self.subTest(changes=changes):
                self.snapshot(**changes)
                result = self.projection().get('operations', {})
                self.assertIn(result.get('state'), {'unavailable', 'stale'})
                self.assertNotIn('PRIVATE_', json.dumps(result))

    def test_ec01_symlink_snapshot_fails_closed(self):
        self.snapshot()
        path = self.directory / 'operations-status.json'
        path.rename(self.directory / 'other.json')
        path.symlink_to(self.directory / 'other.json')
        self.assertEqual(self.projection().get('operations', {}).get('state'), 'unavailable')

    def test_int05_anonymous_projection_never_reads_operation_storage(self):
        with patch('pathlib.Path.open', side_effect=AssertionError('Private file opened')):
            self.assertEqual(docxx_projection(self.directory, owner=False), {'state': 'owner_required'})


class UnifiedHealthTests(PrivateFixture):
    def gmail(self, **changes):
        value = {'schema_version': 1, 'producer': 'docxx-gmail-intake',
                 'state': 'error', 'monitoring_enabled': True, 'checked_at': NOW - 5,
                 'pending': 0, 'known_pending': 0, 'discovery_pending': False,
                 'unavailable_messages': 1, 'error_code': 'message_not_found', **changes}
        self.write('gmail-status.json', value)
        self.status['gmail_ingress'] = value

    def test_ac07_one_missing_gmail_message_is_a_warning_not_global_failure(self):
        self.gmail()
        self.status['phase'] = 'needs_review'  # Legacy aggregation of this item warning.
        result = self.projection()
        self.assertEqual(result['state'], 'ready')
        self.assertEqual(result['gmail']['state'], 'warning')
        self.assertTrue(result['gmail'].get('error') or result['gmail'].get('warning'))
        self.assertTrue(result['warnings'])

    def test_ac07_auth_rate_and_catalog_errors_do_not_become_ready(self):
        for code in ('auth_required', 'rate_limited', 'catalog_unavailable'):
            with self.subTest(code=code):
                self.gmail(error_code=code)
                result = self.projection()
                self.assertNotEqual(result['state'], 'ready')
                self.assertEqual(result['gmail']['state'], 'error')

    def test_ac07_unknown_or_undiscovered_gmail_backlog_is_not_zero(self):
        for changes in ({'pending': None}, {'pending': 2}, {'discovery_pending': True},
                        {'known_pending': 1}):
            with self.subTest(changes=changes):
                self.gmail(**changes)
                self.assertNotEqual(self.projection()['state'], 'ready')

    def test_ac07_missing_message_does_not_override_real_catalog_failure(self):
        self.gmail()
        self.status['catalog'] = {'status': 'error', 'reason': 'PRIVATE_CATALOG_EXCEPTION'}
        result = self.projection()
        self.assertNotEqual(result['state'], 'ready')
        self.assertNotIn('PRIVATE_CATALOG_EXCEPTION', json.dumps(result))

    def test_ac07_stale_gmail_error_does_not_become_a_fresh_warning(self):
        self.gmail(checked_at=NOW - 901)
        result = self.projection()
        self.assertNotEqual(result['state'], 'ready')
        self.assertEqual(result['gmail']['state'], 'stale')


class UnifiedSearchTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.database = self.directory / 'operations.sqlite3'

    def seed(self, rows=None):
        if rows is None:
            rows = [('document_1', FILE_ID, HASH, 'ÉTAT CIVIL — Свидетельство о рождении. ' + 'x' * 1000, 'ocr-v1')]
        with sqlite3.connect(self.database) as conn:
            conn.execute('CREATE TABLE indexed (document_id TEXT, file_id TEXT, sha256 TEXT, text TEXT, extractor_id TEXT)')
            conn.executemany('INSERT INTO indexed VALUES (?, ?, ?, ?, ?)', rows)
            conn.execute('CREATE VIEW search_documents AS SELECT document_id,file_id,sha256,text,extractor_id FROM indexed')
        self.database.chmod(0o600)

    def search(self, query, **kwargs):
        try:
            return docxx_search(self.directory, query, owner=True, **kwargs)
        except NotImplementedError:
            self.fail('The owner-only document search behavior is not implemented')

    def test_int05_anonymous_search_does_not_stat_open_or_connect(self):
        with patch('pathlib.Path.stat', side_effect=AssertionError('Private stat')), \
             patch('pathlib.Path.open', side_effect=AssertionError('Private open')), \
             patch('sqlite3.connect', side_effect=AssertionError('Private connection')):
            try:
                result = docxx_search(self.directory, 'secret', owner=False)
            except NotImplementedError:
                self.fail('Anonymous search must return owner_required before storage access')
        self.assertEqual(result.get('state'), 'owner_required')
        self.assertFalse(result.get('results'))

    def test_ac05_unicode_case_insensitive_search_returns_bounded_references(self):
        self.seed()
        for term in ('état civil', 'свидетельство О РОЖДЕНИИ'):
            with self.subTest(term=term):
                result = self.search(term)
                self.assertEqual(result['state'], 'ready')
                self.assertEqual(len(result['results']), 1)
                row = result['results'][0]
                self.assertEqual(row['document_id'], 'document_1')
                self.assertEqual(row['file_id'], FILE_ID)
                self.assertEqual(row['sha256'], HASH)
                self.assertLessEqual(len(row['snippet']), 300)
                self.assertNotIn('x' * 400, json.dumps(result))
                self.assertNotIn('text', row)
                self.assertIsNot(row.get('verified'), True)
                self.assertNotEqual(row.get('state'), 'verified')
                self.assertNotIn(str(self.directory), json.dumps(result))
                if row.get('url'):
                    self.assertEqual(row['url'], 'https://drive.google.com/file/d/' + FILE_ID + '/view')

    def test_ac05_sql_wildcards_and_fts_operators_are_literal(self):
        self.seed([
            ('literal', FILE_ID, HASH, 'Texte 100%_exact OR * [x] "mot"', 'ocr-v1'),
            ('other', 'synthetic_document_5678', 'b' * 64, 'Un document sans ces caractères', 'ocr-v1'),
        ])
        for term in ('100%_exact', 'OR *', '[x]', '"mot"'):
            with self.subTest(term=term):
                self.assertEqual([row['document_id'] for row in self.search(term)['results']], ['literal'])
        self.assertEqual(self.search("' OR 1=1 --")['results'], [])

    def test_ec01_query_validation_and_blank_search(self):
        self.seed()
        self.assertEqual(self.search('   ')['results'], [])
        for query in (None, 12, [], 'x' * 501, 'bad\x00query'):
            with self.subTest(query=type(query).__name__):
                result = self.search(query)
                self.assertEqual(result['state'], 'invalid_query')
                self.assertFalse(result.get('results'))

    def test_ec01_result_limit_cannot_exceed_100(self):
        self.seed([('document_' + str(i), 'synthetic_document_' + str(i), HASH, 'needle', 'ocr-v1') for i in range(125)])
        self.assertEqual(len(self.search('needle', limit=3)['results']), 3)
        self.assertEqual(len(self.search('needle', limit=100)['results']), 100)
        for limit in (0, -1, True, '5', 101, 100000):
            with self.subTest(limit=limit):
                result = self.search('needle', limit=limit)
                self.assertIn(result['state'], {'invalid_query', 'ready'})
                self.assertLessEqual(len(result.get('results', [])), 100)

    def test_ec01_missing_corrupt_and_foreign_stores_fail_without_creation(self):
        self.assertEqual(self.search('needle')['state'], 'unavailable')
        self.assertFalse(self.database.exists())
        for data in (b'not sqlite PRIVATE_EXCEPTION', b''):
            self.database.write_bytes(data)
            before = self.database.read_bytes()
            result = self.search('needle')
            self.assertEqual(result['state'], 'unavailable')
            self.assertEqual(self.database.read_bytes(), before)
            self.assertNotIn('PRIVATE_EXCEPTION', json.dumps(result))

    def test_ec01_symlink_and_nonregular_database_never_connect(self):
        target = self.directory / 'private-target'
        target.write_bytes(b'PRIVATE_TARGET')
        for kind in ('symlink', 'directory', 'fifo'):
            with self.subTest(kind=kind):
                if kind == 'symlink': self.database.symlink_to(target)
                elif kind == 'directory': self.database.mkdir()
                else: os.mkfifo(self.database)
                try:
                    with patch('sqlite3.connect', side_effect=AssertionError('Unsafe database connected')):
                        self.assertEqual(self.search('needle')['state'], 'unavailable')
                finally:
                    if kind == 'directory': self.database.rmdir()
                    else: self.database.unlink()

    def test_ec01_symlink_state_directory_is_rejected(self):
        self.seed()
        alias = self.directory / 'alias'
        alias.symlink_to(self.directory, target_is_directory=True)
        with patch('sqlite3.connect', side_effect=AssertionError('Symlink state connected')):
            try:
                result = docxx_search(alias, 'needle', owner=True)
            except NotImplementedError:
                self.fail('Symlink state must fail closed')
        self.assertEqual(result['state'], 'unavailable')

    def test_ec01_oversize_sparse_database_is_rejected_before_connection(self):
        with self.database.open('wb') as stream:
            stream.truncate(1 << 40)
        with patch('sqlite3.connect', side_effect=AssertionError('Oversize database connected')):
            self.assertEqual(self.search('needle')['state'], 'unavailable')

    def test_int05_search_connection_is_read_only_and_store_is_unchanged(self):
        self.seed()
        before = hashlib.sha256(self.database.read_bytes()).hexdigest()
        names_before = {p.name for p in self.directory.iterdir()}
        real_connect = sqlite3.connect
        connected = []

        def checked_connect(*args, **kwargs):
            connection = real_connect(*args, **kwargs)
            try:
                with self.assertRaises(sqlite3.OperationalError):
                    connection.execute('CREATE TABLE forbidden_write (value TEXT)')
            except BaseException:
                connection.close()
                raise
            connected.append(True)
            return connection

        with patch('sqlite3.connect', side_effect=checked_connect):
            self.assertEqual(self.search('état')['state'], 'ready')
        self.assertTrue(connected)
        self.assertEqual(hashlib.sha256(self.database.read_bytes()).hexdigest(), before)
        self.assertEqual({p.name for p in self.directory.iterdir()}, names_before)

    def test_ac05_unsafe_drive_identifiers_cannot_become_links_or_file_ids(self):
        self.seed([('bad_' + str(i), value, HASH, 'needle', 'ocr-v1') for i, value in enumerate(
            ('../../PRIVATE_FILE', 'https://evil.invalid/file', 'id?token=PRIVATE_TOKEN', '<script>'))])
        result = self.search('needle')
        self.assertEqual(result['state'], 'ready')
        for row in result['results']:
            self.assertFalse(row.get('url'))
            self.assertFalse(row.get('file_id'))
        for marker in ('PRIVATE_', 'evil.invalid', '<script>'):
            self.assertNotIn(marker, json.dumps(result))


class UnifiedSearchRouteTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        spec = importlib.util.spec_from_file_location('unified_docxx_test_server', BUILDER / 'dashboard-server-m4.py')
        self.server = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.server)

    def request(self, query, *, owner=False):
        handler = self.server.Handler.__new__(self.server.Handler)
        handler.path = '/api/docxx/search?' + query
        handler.command = 'GET'
        handler.headers = {'Host': 'localhost:7777'}
        handler.wfile = io.BytesIO()
        result = {'headers': {}}
        handler.send_response = lambda code, *args: result.update(code=code)
        handler.send_error = lambda code, *args: result.update(code=code)
        handler.send_header = lambda name, value: result['headers'].update({name: value})
        handler.end_headers = lambda: None
        handler.send_head = lambda: self.fail('Search API fell through to filesystem serving')
        with patch.object(self.server, 'HOME', self.home), patch.object(
                self.server.Handler, '_decision_owner_authorized', return_value=owner) as gate:
            handler.do_GET()
        result['gate_called'] = gate.called
        result['body'] = handler.wfile.getvalue().decode()
        return result

    def test_int05_anonymous_search_endpoint_uses_existing_gate_and_no_store(self):
        with patch('sqlite3.connect', side_effect=AssertionError('Anonymous database read')):
            result = self.request('q=secret', owner=False)
        self.assertTrue(result['gate_called'])
        self.assertEqual(json.loads(result['body'])['state'], 'owner_required')
        self.assertIn('no-store', result['headers']['Cache-Control'])

    def test_int05_owner_route_uses_fixed_store_and_ignores_path_parameter(self):
        directory = state_path(self.home)
        directory.mkdir(parents=True)
        with sqlite3.connect(directory / 'operations.sqlite3') as conn:
            conn.execute('CREATE TABLE indexed(document_id,file_id,sha256,text,extractor_id)')
            conn.execute('INSERT INTO indexed VALUES (?,?,?,?,?)', ('doc', FILE_ID, HASH, 'Свидетельство', 'ocr-v1'))
            conn.execute('CREATE VIEW search_documents AS SELECT * FROM indexed')
        result = self.request('q=' + quote('свидетельство') + '&path=/tmp/PRIVATE_EXTERNAL.sqlite3', owner=True)
        self.assertTrue(result['gate_called'])
        body = json.loads(result['body'])
        self.assertEqual(body['state'], 'ready')
        self.assertEqual(len(body['results']), 1)
        self.assertEqual(body['results'][0]['document_id'], 'doc')
        self.assertNotIn('PRIVATE_EXTERNAL', result['body'])
        self.assertIn('no-store', result['headers']['Cache-Control'])


if __name__ == '__main__':
    unittest.main()
