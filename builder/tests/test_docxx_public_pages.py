from __future__ import annotations

import base64
import hashlib
from html.parser import HTMLParser
import importlib.util
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import patch


BUILDER_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BUILDER_DIR))
from dashboard_builder.docxx_public_pages import PAGES, CONTENT_SECURITY_POLICY  # noqa: E402

SPEC = importlib.util.spec_from_file_location('docxx_info_server', BUILDER_DIR / 'dashboard-server-m4.py')
SERVER = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(SERVER)


class PageReader(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags, self.links, self.languages, self.current = [], [], [], []
        self.in_style = False
        self.styles = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        self.tags.append(tag)
        if tag == 'html':
            self.languages.append(values.get('lang'))
        if 'aria-current' in values:
            self.current.append(values.get('href'))
        for key in ('src', 'href', 'action'):
            if key in values:
                self.links.append(values[key])
        self.in_style = self.in_style or tag == 'style'

    def handle_endtag(self, tag):
        if tag == 'style':
            self.in_style = False

    def handle_data(self, data):
        if self.in_style:
            self.styles.append(data)


class DocxxPublicPagesTest(unittest.TestCase):
    def request(self, path, *, method='GET', host='command.meshly.fr'):
        response = {'headers': {}}
        handler = SERVER.Handler.__new__(SERVER.Handler)
        handler.path, handler.command = path, method
        handler.headers = {'Host': host}
        handler.wfile = io.BytesIO()
        handler.send_response = lambda status: response.update(status=status)
        handler.send_error = lambda status, *args: response.update(status=status)
        handler.send_header = lambda key, value: response['headers'].update({key: value})
        handler.end_headers = lambda: None
        handler._decision_owner_authorized = lambda: self.fail('Information page invoked owner authorization')
        handler.translate_path = lambda _: self.fail('Information route fell through to filesystem')
        with patch.object(SERVER, 'docxx_projection', side_effect=AssertionError('Private projection called')):
            getattr(handler, 'do_' + method)()
        response['body'] = handler.wfile.getvalue()
        return response

    def test_three_exact_anonymous_pages_and_matching_head(self):
        self.assertEqual(set(PAGES), {'/jarvis-docxx/', '/jarvis-docxx/privacy/', '/jarvis-docxx/terms/'})
        for path in PAGES:
            with self.subTest(path=path):
                get = self.request(path)
                head = self.request(path, method='HEAD')
                self.assertEqual(get['status'], 200)
                self.assertEqual(head['status'], 200)
                self.assertEqual(get['body'], PAGES[path])
                self.assertEqual(head['body'], b'')
                self.assertEqual(head['headers'], get['headers'])
                self.assertEqual(int(get['headers']['Content-Length']), len(get['body']))
                self.assertEqual(get['headers']['Content-Type'], 'text/html; charset=utf-8')

    def test_unknown_paths_and_traversal_never_reach_static_serving(self):
        for path in ('/jarvis-docxx', '/jarvis-docxx/private.json', '/jarvis-docxx/privacy/index.html',
                     '/jarvis-docxx/../.agent-bridge/token', '/jarvis-docxx/%2e%2e/private',
                     '/jarvis-docxx/privacy//', '/jarvis-docxx/api/docxx'):
            for method in ('GET', 'HEAD'):
                for host in ('command.meshly.fr', '127.0.0.1'):
                    with self.subTest(path=path, method=method, host=host):
                        self.assertEqual(self.request(path, method=method, host=host)['status'], 404)

    def test_query_does_not_change_or_inject_page(self):
        self.assertEqual(self.request('/jarvis-docxx/?private=synthetic-secret')['body'], PAGES['/jarvis-docxx/'])

    def test_pages_are_french_accessible_static_and_link_only_to_known_pages(self):
        for path, body in PAGES.items():
            with self.subTest(path=path):
                page = PageReader()
                page.feed(body.decode())
                self.assertEqual(page.languages, ['fr'])
                self.assertEqual(page.tags.count('h1'), 1)
                self.assertEqual(page.current, [path])
                self.assertIn('main', page.tags)
                self.assertIn('#contenu', page.links)
                self.assertTrue(all(link == '#contenu' or link in PAGES for link in page.links))
                for active in ('script', 'iframe', 'form', 'input', 'object', 'embed', 'img', 'link'):
                    self.assertNotIn(active, page.tags)
                style_hash = base64.b64encode(hashlib.sha256(''.join(page.styles).encode()).digest()).decode()
                self.assertIn("style-src 'sha256-" + style_hash + "'", CONTENT_SECURITY_POLICY)
                self.assertIn("default-src 'none'", CONTENT_SECURITY_POLICY)
                self.assertIn("frame-ancestors 'none'", CONTENT_SECURITY_POLICY)


if __name__ == '__main__':
    unittest.main()
