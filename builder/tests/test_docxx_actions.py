"""Mark sorts «Нужен разбор» documents from the site: move, archive, keep, undo."""
from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from dashboard_builder.docxx import docxx_projection
from dashboard_builder import docxx_actions
from dashboard_builder.docxx_actions import _rename_noreplace, apply, folders_view, load_decisions

REVIEW = '10 — 📥 To review/Documents to review'


class SortingTests(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        base = Path(t.name)
        self.state = base / 'state'
        self.state.mkdir()
        self.library = base / 'Drive' / 'DOCXXx'
        for folder in (REVIEW, 'France/Médiathèque', 'France/Impôts', '90 — Archive', '.hidden'):
            (self.library / folder).mkdir(parents=True)
        self.decisions = base / 'agent-bridge' / 'docxx-decisions.json'
        status = {'checked_at': time.time() - 5, 'phase': 'needs_review', 'model_calls': 0,
                  'catalog': {'status': 'ready', 'documents': 3}, 'results': [],
                  'drive_ingress': {'status': 'idle', 'pending': 0, 'results': []}, 'review_pending': []}
        self.write('status.json', status)
        for name in ('journal.json', 'drive-ingress-journal.json', 'config.json'):
            self.write(name, {})
        (self.state / 'runner.lock').touch()
        attachments = {}
        for name in ('ticket.pdf', 'scan.pdf'):
            path = self.library / REVIEW / name
            path.write_bytes(b'%PDF synthetic')
            attachments[name] = {'state': 'delivered', 'needs_review': True, 'name': name,
                                 'destination': str(path), 'delivered_at': time.time() - 60}
        self.write('gmail-journal.json', {'schema_version': 1, 'attachments': attachments})

    def write(self, name, data):
        (self.state / name).write_text(json.dumps(data), encoding='utf-8')

    def view(self):
        return docxx_projection(self.state, owner=True, decisions=load_decisions(self.decisions))

    def keys(self):
        return {row['original_name']: row['key'] for row in self.view()['records']}

    def test_folders_skip_hidden_and_review_and_find_archive(self):
        folders = folders_view(self.state, self.decisions)
        self.assertEqual(folders['state'], 'ready')
        self.assertIn('France/Médiathèque', folders['folders'])
        self.assertNotIn('.hidden', folders['folders'])
        self.assertFalse(any(f.startswith('10 —') for f in folders['folders']))
        self.assertEqual(folders['archive'], '90 — Archive')

    def test_paths_never_leave_the_projection(self):
        self.assertNotIn(str(self.library.parent), json.dumps(self.view()))
        self.assertNotIn(str(self.library.parent), json.dumps(folders_view(self.state, self.decisions)))

    def test_move_settles_the_row_and_undo_puts_it_back(self):
        key = self.keys()['ticket.pdf']
        result = apply(self.state, self.decisions, {'action': 'move', 'keys': [key], 'folder': 'France/Médiathèque'})
        self.assertEqual(result['results'], [{'key': key, 'ok': True, 'destination': 'France/Médiathèque/ticket.pdf'}])
        self.assertTrue((self.library / 'France/Médiathèque/ticket.pdf').exists())
        self.assertFalse((self.library / REVIEW / 'ticket.pdf').exists())
        view = self.view()
        row = next(r for r in view['records'] if r['key'] == key)
        self.assertEqual((row['status'], row['label'], row['destination']), ('sorted', 'Разобрано', 'France/Médiathèque/ticket.pdf'))
        self.assertEqual(view['review_count'], 1)
        self.assertEqual(folders_view(self.state, self.decisions)['recent'], ['France/Médiathèque'])
        undo = apply(self.state, self.decisions, {'action': 'undo', 'keys': [key]})
        self.assertTrue(undo['results'][0]['ok'])
        self.assertTrue((self.library / REVIEW / 'ticket.pdf').exists())
        self.assertEqual(self.view()['review_count'], 2)

    def test_bulk_keep_clears_attention(self):
        keys = list(self.keys().values())
        result = apply(self.state, self.decisions, {'action': 'keep', 'keys': keys})
        self.assertTrue(all(r['ok'] for r in result['results']))
        self.assertTrue((self.library / REVIEW / 'scan.pdf').exists())
        view = self.view()
        self.assertEqual(view['review_count'], 0)
        self.assertNotEqual(view['state'], 'attention')

    def test_archive_never_overwrites(self):
        (self.library / '90 — Archive/scan.pdf').write_bytes(b'older')
        key = self.keys()['scan.pdf']
        result = apply(self.state, self.decisions, {'action': 'archive', 'keys': [key]})
        self.assertEqual(result['results'][0]['destination'], '90 — Archive/scan (2).pdf')
        self.assertEqual((self.library / '90 — Archive/scan.pdf').read_bytes(), b'older')

    def test_bad_folder_and_keys_are_refused(self):
        key = self.keys()['scan.pdf']
        for folder in ('../outside', '/tmp', '.hidden', REVIEW, 'Nope'):
            with self.assertRaises(ValueError):
                apply(self.state, self.decisions, {'action': 'move', 'keys': [key], 'folder': folder})
        for body in ({'action': 'delete', 'keys': [key]}, {'action': 'keep', 'keys': []},
                     {'action': 'keep', 'keys': ['../x']}, {'action': 'keep', 'keys': [key] * 51}):
            with self.assertRaises(ValueError):
                apply(self.state, self.decisions, body)
        self.assertTrue((self.library / REVIEW / 'scan.pdf').exists())

    def test_vanished_file_is_reported_not_raised(self):
        key = self.keys()['scan.pdf']
        (self.library / REVIEW / 'scan.pdf').unlink()
        result = apply(self.state, self.decisions, {'action': 'move', 'keys': [key], 'folder': 'France/Impôts'})
        self.assertEqual(result['results'][0], {'key': key, 'ok': False, 'error': 'not_found'})

    def test_second_decision_on_sorted_row_is_refused(self):
        key = self.keys()['scan.pdf']
        apply(self.state, self.decisions, {'action': 'keep', 'keys': [key]})
        again = apply(self.state, self.decisions, {'action': 'move', 'keys': [key], 'folder': 'France/Impôts'})
        self.assertEqual(again['results'][0]['error'], 'already_sorted')

    def test_exclusive_rename_never_replaces(self):
        a, b = self.library / 'France/a.pdf', self.library / 'France/b.pdf'
        a.write_bytes(b'a')
        b.write_bytes(b'b')
        with self.assertRaises(FileExistsError):
            _rename_noreplace(a, b)
        self.assertEqual((a.read_bytes(), b.read_bytes()), (b'a', b'b'))

    def test_name_taken_during_move_gets_the_next_free_name(self):
        key = self.keys()['scan.pdf']
        folder = self.library / 'France/Impôts'
        real = docxx_actions._free_name
        calls = []

        def racing(target_folder, name):
            calls.append(name)
            if len(calls) == 1:  # Drive syncs a same-named file in right after the name was chosen.
                (target_folder / name).write_bytes(b'synced')
            return real(target_folder, name) if len(calls) > 1 else target_folder / name
        with patch.object(docxx_actions, '_free_name', racing):
            result = apply(self.state, self.decisions, {'action': 'move', 'keys': [key], 'folder': 'France/Impôts'})
        self.assertEqual(result['results'][0]['destination'], 'France/Impôts/scan (2).pdf')
        self.assertEqual((folder / 'scan.pdf').read_bytes(), b'synced')
        self.assertEqual(load_decisions(self.decisions)[key]['to'], 'France/Impôts/scan (2).pdf')

    def test_unsaved_decision_moves_nothing(self):
        key = self.keys()['scan.pdf']
        with patch.object(docxx_actions, '_save_decisions', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                apply(self.state, self.decisions, {'action': 'move', 'keys': [key], 'folder': 'France/Impôts'})
        self.assertTrue((self.library / REVIEW / 'scan.pdf').exists())
        self.assertFalse((self.library / 'France/Impôts/scan.pdf').exists())


if __name__ == '__main__':
    unittest.main()
