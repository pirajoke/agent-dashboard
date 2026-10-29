import unittest
from unittest.mock import patch
from dashboard_builder.media import media_projection, build_media_html
from dashboard_builder.command_center import build_command_center_html


class MediaTests(unittest.TestCase):
    def test_static_shell_has_no_data(self):
        html = build_media_html()
        self.assertIn('hidden', html)
        self.assertIn('Требуется вход владельца', html)
        self.assertNotIn('urn:li:', html)
        self.assertIn('media-department', build_command_center_html())

    def test_unconfigured_does_not_fetch(self):
        with patch('urllib.request.build_opener') as fetch:
            self.assertEqual(media_projection({}), {'state': 'not_configured'})
            fetch.assert_not_called()

    def test_credentials_never_transmitted_to_insecure_remote(self):
        with patch('urllib.request.build_opener') as fetch:
            result = media_projection({'MEDIA_SOURCE_URL': 'http://remote.test',
                                       'MEDIA_EXPORT_TOKEN': 'x'*32})
            self.assertEqual(result['state'], 'invalid_configuration')
            fetch.assert_not_called()

    def test_upstream_failures_redacted(self):
        with patch('urllib.request.build_opener', side_effect=RuntimeError('secret-token')):
            result = media_projection({'MEDIA_SOURCE_URL': 'http://127.0.0.1:8000',
                                       'MEDIA_EXPORT_TOKEN': 'x'*32})
            self.assertEqual(result, {'state': 'unavailable'})
