"""Layout variants and invalid metadata must not expose private ticket text."""
import json
import unittest

import test_docxx_readable_records as fixture
from dashboard_builder.docxx import _gmail_source_link, _ticket_metadata

LAYOUT_TICKET = '''    Nom              SYNTHETIC_PRIVATE_NAME
    Profil           Public-Mediatheque-Ormesson
    Dates de validité    Valide à partir du   24/10/2026   à   11:54   jusqu’au   24/10/2027   à   11:54
    Identifiant       SYNTHETIC_PRIVATE_LOGIN
    Mot de passe      SYNTHETIC_PRIVATE_PASSWORD
'''


class ReadableLayoutTests(unittest.TestCase):
    setUp = fixture.ReadableGmailRecordsTests.setUp
    write = fixture.ReadableGmailRecordsTests.write
    read = fixture.ReadableGmailRecordsTests.read
    seed = fixture.ReadableGmailRecordsTests.seed
    record = fixture.ReadableGmailRecordsTests.record

    def test_layout_without_invented_title_header_has_safe_metadata(self):
        self.seed(LAYOUT_TICKET)
        row = self.record()
        self.assertEqual(row['name'], 'Ticket d’accès aux ordinateurs — Médiathèque Ormesson')
        self.assertEqual(row['valid_from'], '2026-10-24')
        self.assertEqual(row['valid_until'], '2027-10-24')
        self.assertEqual(row['status'], 'needs_review')
        self.assertNotIn('SYNTHETIC_PRIVATE_', json.dumps(row))

    def test_invalid_or_reversed_dates_do_not_create_ticket_metadata(self):
        for value in (LAYOUT_TICKET.replace('24/10/2026', '31/02/2026'),
                      LAYOUT_TICKET.replace('24/10/2027', '24/10/2025'),
                      LAYOUT_TICKET.replace('11:54', '25:54')):
            with self.subTest(value=value):
                self.assertEqual(_ticket_metadata(value), {})

    def test_unknown_profile_and_ambiguous_intervals_are_not_recognized(self):
        self.assertEqual(_ticket_metadata(LAYOUT_TICKET.replace('Ormesson', 'Unverified')), {})
        self.assertEqual(_ticket_metadata(LAYOUT_TICKET + LAYOUT_TICKET), {})

    def test_hex_ids_are_normalized_and_match_ui_length_boundaries(self):
        self.assertEqual(_gmail_source_link({'thread_id': fixture.THREAD.upper()}),
                         'https://mail.google.com/mail/#all/' + fixture.THREAD)
        self.assertIsNone(_gmail_source_link({'thread_id': 'a' * 15}))
        self.assertIsNone(_gmail_source_link({'thread_id': 'a' * 33}))
        self.assertEqual(_gmail_source_link({'thread_id': 'invalid', 'message_id': 'B' * 32}),
                         'https://mail.google.com/mail/#all/' + 'b' * 32)


if __name__ == '__main__':
    unittest.main()
