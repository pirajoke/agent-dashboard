import tempfile
import unittest
from pathlib import Path
from dashboard_builder.personal_kanban import Board, Conflict, RequestRejected


class Issues:
    def __init__(self):
        self.rows = {}
        self.private = True
        self.lose_response = False

    def __call__(self, method, path, data=None):
        if path in ('repos/owner/tasks', 'repos/owner/other'):
            return {'private': self.private}
        if method == 'GET' and '?' in path:
            return [i.copy() for i in self.rows.values() if 'state=all' in path or i['state'] == 'open']
        if method == 'POST':
            n = len(self.rows) + 1
            self.rows[n] = dict(data, number=n, state='open')
            if self.lose_response:
                raise TimeoutError()
            return self.rows[n].copy()
        n = int(path.rsplit('/', 1)[1])
        if method == 'PATCH':
            self.rows[n].update(data)
        return self.rows[n].copy()


class BoardTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.issues = Issues()
        self.board = Board(api=self.issues, repo='owner/tasks', ledger=Path(temp.name)/'requests.db')
        self.draft = dict(title='Test card', project='Studio', plan='2026-11-20', source_key='voice:1')

    def test_single_card_across_status_plan_close_and_reopen(self):
        card = self.board.apply('create_task', self.draft)
        self.assertEqual(card['due'], '')
        again = self.board.apply('create_task', self.draft)
        self.assertEqual(again, card)
        def change(status):
            return self.board.apply('update_task', dict(id=card['id'], revision=card['revision'], status=status))
        old = card.copy()
        card = change('doing')
        with self.assertRaises(Conflict):
            self.board.apply('update_task', dict(id=old['id'], revision=old['revision'], status='done'))
        card = change('done')
        self.assertFalse(self.board.list())
        self.assertEqual(self.board.list(True), [card])
        card = change('todo')
        self.assertEqual(self.board.list(), [card])

    def test_unknown_create_reconciles_closed_issue(self):
        self.issues.lose_response = True
        with self.assertRaises(TimeoutError):
            self.board.apply('create_task', self.draft)
        self.issues.rows[1]['state'] = 'closed'
        self.assertEqual(self.board.apply('create_task', self.draft)['status'], 'done')
        self.assertEqual(len(self.issues.rows), 1)
        with self.assertRaises(Conflict):
            self.board.apply('create_task', dict(self.draft, title='Different card'))

    def test_confirmed_rejection_retries_original_key(self):
        def rejected(method, path, data=None):
            if method == 'POST':
                raise RequestRejected('HTTP 422')
            return self.issues(method, path, data)
        self.board.api = rejected
        with self.assertRaises(RequestRejected):
            self.board.apply('create_task', self.draft)
        self.board.api = self.issues
        self.assertEqual(self.board.apply('create_task', self.draft)['id'], 1)
        self.assertEqual(len(self.issues.rows), 1)

    def test_request_ledger_scoped_to_repo(self):
        self.board.apply('create_task', self.draft)
        other_api = Issues()
        other = Board(api=other_api, repo='owner/other', ledger=self.board.ledger)
        other_api.rows[1] = {'body': 'unrelated', 'number': 1, 'state': 'open'}
        card = other.apply('create_task', self.draft)
        self.assertEqual(card['id'], 2)
        self.assertIn('/owner/other/', card['url'])
        self.assertEqual(len(other_api.rows), 2)

    def test_private_only_and_nonboard_issue(self):
        self.issues.rows[99] = dict(body='ordinary issue', state='open')
        self.assertFalse(self.board.list())
        with self.assertRaises(Conflict):
            self.board.apply('update_task', dict(id=99, revision='x', status='done'))
        self.issues.private = False
        with self.assertRaises(RuntimeError):
            Board(api=self.issues, repo='owner/tasks')
