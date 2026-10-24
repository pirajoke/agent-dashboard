"""Synthetic owner-only regressions for readable Gmail attachment cards."""
import json
import sqlite3
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import test_docxx as fixture
from dashboard_builder.docxx import docxx_projection

HASH = 'a' * 64
THREAD = '0123456789abcdef'
SIZE = 1234
ADDED = 1792835656
NAME = 'ticket_fixture.pdf'
TICKET = '''Ticket d'accès aux ordinateurs
Profil Public-Mediatheque-Ormesson
Dates de validité
Valide à partir du 24/10/2026 à 11:54
jusqu'au 24/10/2027 à 11:54
Identifiant : SYNTHETIC_PRIVATE_LOGIN
Mot de passe : SYNTHETIC_PRIVATE_PASSWORD
'''


class ReadableGmailRecordsTests(unittest.TestCase):
    setUp = fixture.ProjectionTests.setUp
    write = fixture.ProjectionTests.write
    read = fixture.ProjectionTests.read

    def seed(self, text=TICKET, **changes):
        entry = {'state': 'review', 'needs_review': True, 'name': NAME,
                 'thread_id': THREAD, 'sha256': HASH, 'size': SIZE,
                 'message_id': 'SYNTHETIC_PRIVATE_MESSAGE',
                 'attachment_id': 'SYNTHETIC_PRIVATE_ATTACHMENT'}
        entry.update(changes)
        self.write('gmail-journal.json', {'schema_version': 1, 'attachments': {'entry': entry}})
        database = self.root / 'operations.sqlite3'
        with sqlite3.connect(database) as connection:
            connection.execute('CREATE TABLE operations (id TEXT PRIMARY KEY, action TEXT NOT NULL, sha256 TEXT NOT NULL, size INTEGER NOT NULL, state TEXT NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL, details TEXT, proof TEXT, UNIQUE(action,sha256,size))')
            connection.execute('CREATE TABLE extractions (sha256 TEXT NOT NULL, extractor_id TEXT NOT NULL, text TEXT NOT NULL, created_at REAL NOT NULL, PRIMARY KEY(sha256,extractor_id))')
            connection.execute('INSERT INTO operations VALUES (?,?,?,?,?,?,?,?,?)',
                               ('synthetic_op', 'import', HASH, SIZE, 'needs_review', ADDED, ADDED + 200, None, None))
            connection.execute('INSERT INTO extractions VALUES (?,?,?,?)', (HASH, 'synthetic-ocr-v1', text, ADDED))
        database.chmod(0o600)
        return database

    def record(self):
        rows = [row for row in self.read()['records'] if row['source'] == 'gmail']
        self.assertEqual(len(rows), 1)
        return rows[0]

    def test_pending_attachment_has_source_link_without_claiming_cloud_delivery(self):
        self.seed()
        row = self.record()
        self.assertEqual(row.get('source_url'), 'https://mail.google.com/mail/#all/' + THREAD)
        self.assertIsNone(row['url'])
        self.assertEqual(row['status'], 'needs_review')

    def test_pending_attachment_uses_matching_operation_creation_date(self):
        self.seed()
        row = self.record()
        self.assertEqual(row['at'], datetime.fromtimestamp(ADDED, timezone.utc).isoformat())
        self.assertEqual(row.get('date_kind'), 'added')

    def test_recognized_ticket_has_safe_readable_metadata(self):
        self.seed()
        row = self.record()
        self.assertNotEqual(row['name'], NAME)
        self.assertIn('ticket', row['name'].lower())
        self.assertIn('ormesson', row['name'].lower())
        self.assertTrue(row.get('description'))
        self.assertLessEqual(len(row['description']), 300)
        self.assertEqual(row.get('valid_from'), '2026-10-24')
        self.assertEqual(row.get('valid_until'), '2027-10-24')
        self.assertEqual(row['original_name'], NAME)
        self.assertEqual(row['status'], 'needs_review')
        self.assertNotIn('SYNTHETIC_PRIVATE_', json.dumps(row))

    def test_unknown_text_remains_review_without_raw_text_or_credentials(self):
        self.seed('Unrecognized personal document SYNTHETIC_PRIVATE_TEXT\nPassword: SYNTHETIC_PRIVATE_PASSWORD')
        row = self.record()
        self.assertEqual(row['name'], NAME)
        self.assertEqual(row['status'], 'needs_review')
        self.assertFalse(row.get('valid_from'))
        self.assertFalse(row.get('valid_until'))
        self.assertNotIn('SYNTHETIC_PRIVATE_', json.dumps(row))

    def test_invalid_thread_ids_never_create_links(self):
        self.seed()
        for thread_id in ('../../secret', 'javascript:alert(1)', '0123456789abcdef?token=x', '', {}, None):
            with self.subTest(thread_id=thread_id):
                self.write('gmail-journal.json', {'schema_version': 1, 'attachments': {'entry': {
                    'state': 'review', 'name': NAME, 'thread_id': thread_id}}})
                self.assertFalse(self.record().get('source_url'))

    def test_invalid_sha_or_wrong_size_cannot_borrow_operation_date(self):
        self.seed()
        for sha, size in ((HASH[:-1], SIZE), (HASH + "' OR 1=1 --", SIZE), ({}, SIZE), (HASH, SIZE + 1)):
            with self.subTest(sha=sha, size=size):
                self.write('gmail-journal.json', {'schema_version': 1, 'attachments': {'entry': {
                    'state': 'review', 'name': NAME, 'thread_id': THREAD, 'sha256': sha, 'size': size}}})
                self.assertIsNone(self.record()['at'])

    def test_database_errors_leave_existing_record_safe(self):
        database = self.seed()
        database.write_bytes(b'broken SYNTHETIC_PRIVATE_DB')
        row = self.record()
        self.assertEqual(row['name'], NAME)
        self.assertIsNone(row['at'])
        self.assertNotIn('SYNTHETIC_PRIVATE_', json.dumps(row))

    def test_symlink_database_is_not_read(self):
        database = self.seed()
        actual = self.root / 'other.sqlite3'
        database.rename(actual)
        database.symlink_to(actual)
        with patch('sqlite3.connect', side_effect=AssertionError('Unsafe symlink connection')):
            row = self.record()
        self.assertEqual(row['name'], NAME)
        self.assertIsNone(row['at'])

    def test_unauthenticated_projection_does_not_read_private_state(self):
        self.seed()
        with patch('dashboard_builder.docxx._read', side_effect=AssertionError('Private read')), \
             patch('pathlib.Path.stat', side_effect=AssertionError('Private stat')), \
             patch('sqlite3.connect', side_effect=AssertionError('Private connection')):
            self.assertEqual(docxx_projection(self.root, owner=False), {'state': 'owner_required'})


if __name__ == '__main__':
    unittest.main()
