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
from dashboard_builder.docxx_actions import _rename_noreplace, apply, folders_view, load_decisions, load_suggestions

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
        self.decisions.parent.mkdir()
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
        for body in ({'action': 'delete', 'keys': [key]}, {'action': 'erase', 'keys': [key]}, {'action': 'keep', 'keys': []},
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

    def test_trash_makes_a_basket_in_the_review_folder_and_undo_brings_it_back(self):
        key = self.keys()['scan.pdf']
        self.assertTrue(folders_view(self.state, self.decisions)['can_trash'])
        result = apply(self.state, self.decisions, {'action': 'trash', 'keys': [key]})
        self.assertEqual(result['results'][0]['destination'], '10 — 📥 To review/Корзина/scan.pdf')
        self.assertFalse((self.library / 'Корзина').exists())  # Never at the library root.
        self.assertNotIn(key, [r['key'] for r in self.view()['records']])  # Gone from the page.
        view = folders_view(self.state, self.decisions)
        self.assertEqual(view['trash'], '10 — 📥 To review/Корзина')
        self.assertNotIn(view['trash'], view['folders'])
        self.assertTrue(apply(self.state, self.decisions, {'action': 'undo', 'keys': [key]})['results'][0]['ok'])
        self.assertTrue((self.library / REVIEW / 'scan.pdf').exists())
        self.assertEqual(list((self.library / '10 — 📥 To review/Корзина').iterdir()), [])

    def test_existing_trash_folder_is_used(self):
        (self.library / '99 — Trash').mkdir()
        key = self.keys()['ticket.pdf']
        result = apply(self.state, self.decisions, {'action': 'trash', 'keys': [key]})
        self.assertEqual(result['results'][0]['destination'], '99 — Trash/ticket.pdf')
        self.assertFalse((self.library / '10 — 📥 To review/Корзина').exists())

    def test_auto_moves_only_documents_whose_suggestion_fits(self):
        keys = self.keys()
        suggestions = self.decisions.parent / 'docxx-suggestions.json'
        items = {keys['ticket.pdf']: {'name': 'ticket.pdf', 'folder': 'France/Médiathèque', 'junk': False, 'why': 'Билет'},
                 keys['scan.pdf']: {'name': 'scan.pdf', 'folder': 'Nope/Invented', 'junk': False, 'why': '?'}}
        suggestions.write_text(json.dumps({'schema_version': 1, 'items': items}), encoding='utf-8')
        self.assertEqual(set(load_suggestions(suggestions)), set(items))
        result = apply(self.state, self.decisions, {'action': 'auto', 'keys': list(keys.values())}, suggestions)
        by_key = {r['key']: r for r in result['results']}
        self.assertEqual(by_key[keys['ticket.pdf']]['destination'], 'France/Médiathèque/ticket.pdf')
        self.assertEqual(by_key[keys['scan.pdf']], {'key': keys['scan.pdf'], 'ok': False, 'error': 'no_suggestion'})
        self.assertTrue((self.library / REVIEW / 'scan.pdf').exists())
        view = docxx_projection(self.state, owner=True, decisions=load_decisions(self.decisions),
                                suggestions=load_suggestions(suggestions))
        scan = next(r for r in view['records'] if r['key'] == keys['scan.pdf'])
        self.assertEqual(scan['suggest']['folder'], 'Nope/Invented')

    def test_auto_never_trashes_junk(self):
        key = self.keys()['scan.pdf']
        suggestions = self.decisions.parent / 'docxx-suggestions.json'
        suggestions.write_text(json.dumps({'schema_version': 1, 'items': {
            key: {'name': 'scan.pdf', 'folder': 'France/Impôts', 'junk': True, 'why': 'Мусор'}}}), encoding='utf-8')
        result = apply(self.state, self.decisions, {'action': 'auto', 'keys': [key]}, suggestions)
        self.assertEqual(result['results'][0]['error'], 'no_suggestion')
        self.assertTrue((self.library / REVIEW / 'scan.pdf').exists())
        row = next(r for r in docxx_projection(self.state, owner=True, suggestions=load_suggestions(suggestions))['records']
                   if r['key'] == key)
        self.assertEqual(row['suggest'], {'junk': True, 'why': 'Мусор'})
    def test_drive_document_without_a_path_is_found_by_name_in_the_review_folder(self):
        status = json.loads((self.state / 'status.json').read_text())
        status['drive_ingress']['results'] = [{'status': 'needs_review', 'id': 'drive-doc-1'},
                                              {'status': 'needs_review', 'id': 'drive-doc-2', 'target_name': 'Lost.pdf'}]
        self.write('status.json', status)
        (self.library / REVIEW / 'Документ без названия.gdoc').write_text('{"doc_id": "drive-doc-1"}')
        rows = {r['name']: r['key'] for r in self.view()['records'] if r['source'] == 'drive'}
        folders = folders_view(self.state, self.decisions)
        self.assertIn(rows['Документ без названия'], folders['movable'])
        self.assertNotIn(rows['Lost.pdf'], folders['movable'])
        result = apply(self.state, self.decisions, {'action': 'trash', 'keys': [rows['Документ без названия']]})
        self.assertEqual(result['results'][0]['destination'], '10 — 📥 To review/Корзина/Документ без названия.gdoc')
        lost = apply(self.state, self.decisions, {'action': 'trash', 'keys': [rows['Lost.pdf']]})
        self.assertEqual(lost['results'][0]['error'], 'not_found')
    def test_two_rows_on_one_file_or_a_wrong_doc_id_move_nothing(self):
        status = json.loads((self.state / 'status.json').read_text())
        status['drive_ingress']['results'] = [{'status': 'needs_review', 'id': 'drive-doc-aa'},
                                              {'status': 'needs_review', 'id': 'drive-doc-bb'},
                                              {'status': 'needs_review', 'id': 'drive-doc-cc', 'target_name': 'Plan'}]
        self.write('status.json', status)
        (self.library / REVIEW / 'Документ без названия.gdoc').write_text('{"doc_id": "drive-doc-aa"}')
        (self.library / REVIEW / 'Plan.gdoc').write_text('{"doc_id": "someOtherDoc"}')
        drive = [r for r in self.view()['records'] if r['source'] == 'drive']
        movable = folders_view(self.state, self.decisions)['movable']
        self.assertFalse(any(r['key'] in movable for r in drive))
        for row in drive:
            self.assertEqual(apply(self.state, self.decisions, {'action': 'trash', 'keys': [row['key']]})['results'][0]['error'], 'not_found')
        self.assertTrue((self.library / REVIEW / 'Документ без названия.gdoc').exists())
    def test_remove_trashes_any_document_and_hides_what_it_cannot_reach(self):
        keys = self.keys()
        moved = apply(self.state, self.decisions, {'action': 'move', 'keys': [keys['ticket.pdf']], 'folder': 'France/Médiathèque'})
        self.assertTrue(moved['results'][0]['ok'])
        (self.library / REVIEW / 'scan.pdf').unlink()  # Gone from disk: only the entry can go.
        result = apply(self.state, self.decisions, {'action': 'remove', 'keys': list(keys.values())})
        by_key = {r['key']: r for r in result['results']}
        self.assertEqual(by_key[keys['ticket.pdf']]['destination'], '10 — 📥 To review/Корзина/ticket.pdf')
        self.assertTrue(by_key[keys['scan.pdf']]['hidden'])
        self.assertEqual(self.view()['records'], [])
        apply(self.state, self.decisions, {'action': 'undo', 'keys': list(keys.values())})
        self.assertTrue((self.library / 'France/Médiathèque/ticket.pdf').exists())  # Back where Mark had put it.
        rows = {r['original_name']: r for r in self.view()['records']}
        self.assertEqual(rows['ticket.pdf']['label'], 'Разобрано')
        self.assertEqual(rows['scan.pdf']['status'], 'needs_review')


    def test_deleted_rows_do_not_push_later_documents_out_of_reach(self):
        attachments = {}
        for i in range(105):
            name = f'doc{i:03}.pdf'
            path = self.library / REVIEW / name
            path.write_bytes(b'%PDF synthetic')
            attachments[name] = {'state': 'delivered', 'needs_review': True, 'name': name,
                                 'destination': str(path), 'delivered_at': time.time() - 1000 + i}
        self.write('gmail-journal.json', {'schema_version': 1, 'attachments': attachments})
        first = [row['key'] for row in self.view()['records'][:50]]
        self.assertTrue(all(r['ok'] for r in apply(self.state, self.decisions, {'action': 'remove', 'keys': first})['results']))
        view = self.view()
        self.assertEqual((len(view['records']), view['records_total']), (55, 55))
        last = view['records'][-1]['key']
        self.assertTrue(apply(self.state, self.decisions, {'action': 'remove', 'keys': [last]})['results'][0]['ok'])
        self.assertTrue(apply(self.state, self.decisions, {'action': 'undo', 'keys': first[:1]})['results'][0]['ok'])

if __name__ == '__main__':
    unittest.main()
