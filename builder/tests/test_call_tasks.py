import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from dashboard_builder.call_tasks import call_tasks_projection, record_mark

DATA = {"schema": 1, "generated_at": "2026-11-25T14:00:00Z", "calls": [{
    "card": "2026-11-25-offrys.md", "title": "Offrys", "date": "2026-11-25", "project": "offrys",
    "people": ["Влад"], "meeting_id": "a" * 32, "start": "2026-11-25T13:49:00Z", "duration_min": 17,
    "steps": [{"id": "1" * 12, "text": "Отправить ссылку", "done": False, "done_at": ""}],
    "others": [{"who": "Влад", "text": "Вкладка", "due": "сегодня"}]}]}
NOW = datetime(2026, 11, 25, 14, 30, tzinfo=timezone.utc)


class CallTasksTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        (self.dir / 'tasks.json').write_text(json.dumps(DATA))

    def tearDown(self):
        self.tmp.cleanup()

    def test_owner_only(self):
        self.assertEqual(call_tasks_projection(self.dir, owner=False), {'state': 'owner_required', 'calls': []})

    def test_projection_and_missing(self):
        out = call_tasks_projection(self.dir, owner=True, now=NOW)
        self.assertEqual(out['state'], 'ready')
        call = out['calls'][0]
        self.assertEqual((call['call'], call['meeting_id'], call['steps'][0]['done']), ('2026-11-25-offrys', 'a' * 32, False))
        self.assertEqual(call_tasks_projection(self.dir / 'nope', owner=True)['state'], 'not_installed')

    def test_tick_shows_at_once_until_rebuilt(self):
        mark = record_mark(self.dir, {'id': '1' * 12, 'card': '2026-11-25-offrys.md', 'done': True}, now=NOW)
        self.assertTrue(mark['done'])
        step = call_tasks_projection(self.dir, owner=True, now=NOW)['calls'][0]['steps'][0]
        self.assertEqual((step['done'], step['pending']), (True, True))
        # call_tasks.py rebuilt later and the card still says open (ticked back by hand): the card wins
        newer = dict(DATA, generated_at='2026-11-25T15:00:00Z')
        (self.dir / 'tasks.json').write_text(json.dumps(newer))
        step = call_tasks_projection(self.dir, owner=True, now=NOW)['calls'][0]['steps'][0]
        self.assertEqual((step['done'], step['pending']), (False, False))

    def test_rejects_unknown_or_bad(self):
        with self.assertRaises(LookupError):
            record_mark(self.dir, {'id': '2' * 12, 'card': '2026-11-25-offrys.md', 'done': True})
        for bad in ({'id': '../x', 'card': 'a.md', 'done': True}, {'id': '1' * 12, 'card': '../a.md', 'done': True},
                    {'id': '1' * 12, 'card': '2026-11-25-offrys.md', 'done': 'yes'}):
            with self.assertRaises(ValueError):
                record_mark(self.dir, bad)
        self.assertFalse((self.dir / 'marks.jsonl').exists())


if __name__ == '__main__':
    unittest.main()
