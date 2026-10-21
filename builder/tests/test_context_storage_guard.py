"""Private context storage cannot be downloaded through static serving.

All roots, notes, manifests and aliases here are synthetic temporary fixtures.
The owner API remains the only supported route to the private projection.
"""
from __future__ import annotations

import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

BUILDER = Path(__file__).resolve().parents[1]
PRIVATE = 'SYNTHETIC_CONTEXT_PRIVATE_MARKER'


class ContextStorageGuardTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location('context_storage_server', BUILDER / 'dashboard-server-m4.py')
        self.server = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.server)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.default = self.home / '.agent-bridge/context-library/catalog.json'
        self.default.parent.mkdir(parents=True)
        self.default.write_text(PRIVATE)
        self.override = self.home / 'Library/Application Support/Fixture Context/catalog.json'
        self.override.parent.mkdir(parents=True)
        self.override.write_text(PRIVATE)
        (self.override.parent / 'manifest.json').write_text(PRIVATE)
        (self.override.parent / 'subdir').mkdir()
        (self.override.parent / 'subdir/pending.json').write_text(PRIVATE)
        (self.home / 'catalog-alias.json').symlink_to(self.override)
        (self.home / 'private-directory-alias').symlink_to(self.override.parent, target_is_directory=True)
        implicit = self.home / 'implicit-index-alias'
        implicit.mkdir()
        (implicit / 'index.html').symlink_to(self.override)

    def request(self, path='/api/context-library', method='GET', configured=None, owner=False):
        handler = self.server.Handler.__new__(self.server.Handler)
        handler.path, handler.command = path, method
        handler.headers = {'Host': 'localhost:7777'}
        handler.wfile = io.BytesIO()
        response = {'headers': {}}
        handler.send_response = lambda status, *args: response.update(status=status)
        handler.send_header = lambda key, value: response['headers'].update({key.lower(): str(value)})
        handler.end_headers = lambda: None
        handler.send_error = lambda status, *args: response.update(status=status)
        environment = {key: value for key, value in os.environ.items() if key != 'COMMAND_CENTER_CONTEXT_CATALOG'}
        if configured is not None:
            environment['COMMAND_CENTER_CONTEXT_CATALOG'] = str(configured)
        with patch.dict(os.environ, environment, clear=True), \
             patch.object(self.server, 'HOME', self.home), \
             patch.object(self.server.Handler, '_decision_owner_authorized', return_value=owner), \
             patch.object(self.server, 'context_library_projection', return_value={'state': 'ready', 'records': []}) as projection:
            getattr(handler, 'do_' + method)()
        response['body'] = handler.wfile.getvalue().decode()
        response['projection'] = projection.call_args
        return response

    def test_default_api_reads_only_hidden_private_context_directory(self):
        result = self.request(owner=True)
        self.assertEqual(result['status'], 200)
        self.assertIsNotNone(result['projection'])
        self.assertEqual(result['projection'].args[0], self.default)
        self.assertEqual(result['projection'].kwargs['owner'], True)
        self.assertIn('no-store', result['headers'].get('cache-control', ''))

    def test_configured_catalog_api_keeps_strict_owner_projection(self):
        for owner in (False, True):
            with self.subTest(owner=owner):
                result = self.request(configured=self.override, owner=owner)
                self.assertEqual(result['projection'].args[0], self.override)
                self.assertEqual(result['projection'].kwargs['owner'], owner)

    def test_static_get_and_head_cannot_read_default_catalog(self):
        for method in ('GET', 'HEAD'):
            with self.subTest(method=method):
                result = self.request('/.agent-bridge/context-library/catalog.json', method=method)
                self.assertEqual(result['status'], 403)
                self.assertEqual(result['body'], '')

    def test_static_override_parent_files_directories_and_aliases_are_denied(self):
        prefix = '/' + self.override.parent.relative_to(self.home).as_posix()
        paths = (prefix + '/catalog.json', prefix + '/manifest.json', prefix + '/',
                 prefix + '/subdir/', prefix + '/subdir/pending.json',
                 '/catalog-alias.json', '/private-directory-alias/',
                 '/private-directory-alias/manifest.json', '/implicit-index-alias/')
        for method in ('GET', 'HEAD'):
            for path in paths:
                for owner in (False, True):
                    with self.subTest(method=method, path=path, owner=owner):
                        result = self.request(path, method=method, configured=self.override, owner=owner)
                        self.assertEqual(result['status'], 403,
                                         'Private catalog storage must never be served statically, even to owner')
                        self.assertEqual(result['body'], '')
                        self.assertNotIn(PRIVATE, result['body'])


if __name__ == '__main__':
    unittest.main()
