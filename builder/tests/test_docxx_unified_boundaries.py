"""Synthetic regressions: isolated Gmail item warnings cannot hide unknown work."""
import copy
import unittest

from test_docxx_unified import PrivateFixture, NOW


class UnifiedQueueBoundaryTests(PrivateFixture):
    def setUp(self):
        super().setUp()
        gmail = {
            'schema_version': 1, 'producer': 'docxx-gmail-intake',
            'state': 'error', 'monitoring_enabled': True, 'checked_at': NOW - 5,
            'pending': 0, 'known_pending': 0, 'discovery_pending': False,
            'unavailable_messages': 1, 'error_code': 'message_not_found',
        }
        self.write('gmail-status.json', gmail)
        self.status['gmail_ingress'] = gmail
        self.status['phase'] = 'needs_review'
        self.baseline = copy.deepcopy(self.status)

    def assert_unknown_queue(self, projection):
        self.assertTrue(
            projection['state'] != 'ready' and projection['pending'] is None,
            'Unknown queue cannot be normalized to ready/zero: %r' % {
                'state': projection['state'], 'pending': projection['pending'],
                'warnings': projection['warnings'],
            },
        )

    def test_valid_empty_queues_with_isolated_gmail_404_still_are_ready(self):
        result = self.projection()
        self.assertEqual(result['state'], 'ready')
        self.assertEqual(result['pending'], 0)
        self.assertEqual(result['gmail']['state'], 'warning')

    def test_malformed_review_collection_remains_unknown_despite_gmail_404(self):
        for value in (None, {}, {'status': 'needs_review'}, 'not-a-list'):
            with self.subTest(review_pending=value):
                self.status = copy.deepcopy(self.baseline)
                self.status['review_pending'] = value
                self.assert_unknown_queue(self.projection())

    def test_malformed_review_rows_remain_unknown_despite_gmail_404(self):
        for value in ([None], ['invalid-row'], [7], [{}]):
            with self.subTest(review_pending=value):
                self.status = copy.deepcopy(self.baseline)
                self.status['review_pending'] = value
                self.assert_unknown_queue(self.projection())

    def test_unknown_drive_pending_remains_unknown_despite_gmail_404(self):
        for value in (None, {}, '0', True, -1):
            with self.subTest(drive_pending=value):
                self.status = copy.deepcopy(self.baseline)
                self.status['drive_ingress']['pending'] = value
                self.assert_unknown_queue(self.projection())
        self.status = copy.deepcopy(self.baseline)
        del self.status['drive_ingress']['pending']
        self.assert_unknown_queue(self.projection())

    def test_real_catalog_drive_or_icloud_failures_are_not_masked(self):
        for source in ('catalog', 'drive', 'icloud'):
            with self.subTest(source=source):
                self.status = copy.deepcopy(self.baseline)
                if source == 'catalog':
                    self.status['catalog']['status'] = 'error'
                elif source == 'drive':
                    self.status['drive_ingress']['status'] = 'error'
                else:
                    self.status['results'] = [{'source': 'synthetic.pdf', 'status': 'error'}]
                self.assertNotEqual(self.projection()['state'], 'ready')


if __name__ == '__main__':
    unittest.main()
