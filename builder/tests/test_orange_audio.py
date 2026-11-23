"""Orange Audio meetings projection: owner only, schema-checked, synthetic fixtures only."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dashboard_builder.orange_audio import orange_audio_projection

NOW = datetime(2026, 11, 23, 18, 0, tzinfo=timezone.utc)


def catalog(**over):
    meeting = {"id": "a" * 32, "title": "Synthetic call", "start": "2026-11-23T16:00:00Z", "end": "2026-11-23T16:30:00Z",
               "duration_min": 30, "primary": "granola", "sources": ["granola", "orange"], "app": "Telegram",
               "people": ["Person"], "summary": "## Итог\n- Synthetic outcome\n",
               "transcripts": {"granola": [{"t": "00:00:01", "who": "Person", "text": "unique phrase here"}],
                               "orange": [{"t": "00:00:02", "who": "Макс", "text": "hello"}], "evil": [{"text": "x"}]}}
    data = {"schema": 1, "generated_at": NOW.isoformat(), "state": "ready", "issues": [],
            "sources": [{"source": "orange", "state": "observed"}, {"source": "bogus", "state": "observed"}],
            "meetings": [meeting, {"id": "not-an-id", "start": "2026-11-23T10:00:00Z"}]}
    data.update(over)
    return data


class OrangeAudio(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "catalog.json"

    def tearDown(self):
        self.dir.cleanup()

    def write(self, data):
        self.path.write_text(json.dumps(data))

    def test_owner_required_returns_nothing(self):
        self.write(catalog())
        self.assertEqual(orange_audio_projection(self.path, owner=False, now=NOW), {"state": "owner_required", "meetings": []})

    def test_list_has_no_bodies(self):
        self.write(catalog())
        out = orange_audio_projection(self.path, owner=True, now=NOW)
        self.assertEqual(out["state"], "ready")
        self.assertEqual(len(out["meetings"]), 1)
        item = out["meetings"][0]
        self.assertNotIn("transcripts", item)
        self.assertNotIn("summary", item)
        self.assertEqual(item["preview"], "Synthetic outcome")
        self.assertTrue(item["has_summary"])
        self.assertEqual(out["sources"], [{"source": "orange", "state": "observed"}])

    def test_detail_and_unknown_sources_dropped(self):
        self.write(catalog())
        out = orange_audio_projection(self.path, owner=True, meeting_id="a" * 32, now=NOW)
        self.assertEqual(set(out["meeting"]["transcripts"]), {"granola", "orange"})
        self.assertEqual(orange_audio_projection(self.path, owner=True, meeting_id="b" * 32, now=NOW)["state"], "not_found")
        self.assertEqual(orange_audio_projection(self.path, owner=True, meeting_id="../x", now=NOW)["state"], "not_found")

    def test_search_reaches_transcript(self):
        self.write(catalog())
        self.assertEqual(orange_audio_projection(self.path, owner=True, query="UNIQUE phrase", now=NOW)["total"], 1)
        self.assertEqual(orange_audio_projection(self.path, owner=True, query="absent", now=NOW)["total"], 0)

    def test_stale_missing_invalid(self):
        self.write(catalog(generated_at=(NOW - timedelta(hours=2)).isoformat()))
        self.assertEqual(orange_audio_projection(self.path, owner=True, now=NOW)["state"], "stale")
        self.write({"schema": 2})
        self.assertEqual(orange_audio_projection(self.path, owner=True, now=NOW)["state"], "unavailable")
        os.unlink(self.path)
        self.assertEqual(orange_audio_projection(self.path, owner=True, now=NOW)["state"], "not_installed")

    def test_symlink_refused(self):
        real = Path(self.dir.name) / "real.json"
        real.write_text(json.dumps(catalog()))
        self.path.symlink_to(real)
        self.assertEqual(orange_audio_projection(self.path, owner=True, now=NOW)["state"], "unavailable")


if __name__ == "__main__":
    unittest.main()


class Endpoint(unittest.TestCase):
    def setUp(self):
        import importlib.util
        builder = Path(__file__).resolve().parents[1]
        spec = importlib.util.spec_from_file_location('orange_endpoint_fixture', builder / 'dashboard-server-m4.py')
        self.server = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.server)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        path = self.home / '.agent-bridge/orange-audio/catalog.json'
        path.parent.mkdir(parents=True)
        data = catalog(generated_at=datetime.now(timezone.utc).isoformat())
        path.write_text(json.dumps(data))

    def call(self, path='/api/orange-audio', owner=False):
        import io
        from unittest.mock import patch
        handler = self.server.Handler.__new__(self.server.Handler)
        handler.path, handler.command = path, 'GET'
        handler.headers = {'Host': 'localhost:7777'}
        handler.wfile = io.BytesIO()
        response = {'headers': {}}
        handler.send_response = lambda status, *args: response.update(status=status)
        handler.send_header = lambda key, value: response['headers'].update({key.lower(): str(value)})
        handler.end_headers = lambda: None
        handler.send_error = lambda status, *args: response.update(status=status)
        with patch.object(self.server, 'HOME', self.home), \
             patch.object(self.server.Handler, '_decision_owner_authorized', return_value=owner) as strict:
            handler.do_GET()
        response['body'] = handler.wfile.getvalue().decode()
        response['strict_called'] = strict.called
        return response

    def test_anonymous_gets_nothing(self):
        out = self.call()
        self.assertTrue(out['strict_called'])
        self.assertEqual(json.loads(out['body']), {'state': 'owner_required', 'meetings': []})
        self.assertIn('no-store', out['headers'].get('cache-control', ''))
        self.assertNotIn('unique phrase', out['body'])

    def test_owner_gets_meeting(self):
        out = self.call('/api/orange-audio?id=' + 'a' * 32, owner=True)
        body = json.loads(out['body'])
        self.assertEqual(body['meeting']['title'], 'Synthetic call')
        self.assertIn('no-store', out['headers'].get('cache-control', ''))
