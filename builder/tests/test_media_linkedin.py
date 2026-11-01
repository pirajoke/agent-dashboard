"""«Медиа» tab (Mark 2026-10-31): owner-only LinkedIn schedule, queue and manual news picker."""
from __future__ import annotations

import importlib.util
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dashboard_builder import media_linkedin

BUILDER = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("dashboard_media_test", BUILDER / "dashboard-server-m4.py")
SERVER = importlib.util.module_from_spec(spec)
spec.loader.exec_module(SERVER)
PAGE = (BUILDER / "mac-mini-dashboard" / "index.html").read_text()
TOKEN = "t" * 40


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        self.path = self.home / ".config" / "jarvis" / "news-control.json"
        self.path.parent.mkdir(parents=True)
        patcher = patch.dict(os.environ, {"JARVIS_NEWS_URL": "", "JARVIS_NEWS_CONTROL_TOKEN": ""})
        patcher.start()
        self.addCleanup(patcher.stop)

    def write(self, data, mode=0o600):
        self.path.write_text(json.dumps(data))
        self.path.chmod(mode)

    def test_reads_jarvis_protected_file_only_with_safe_origin_and_mode(self):
        self.write({"origin": "http://127.0.0.1:8790", "token": TOKEN})
        self.assertEqual(media_linkedin.news_config(self.home), ("http://127.0.0.1:8790", TOKEN))
        self.write({"origin": "http://127.0.0.1:8790", "token": TOKEN}, mode=0o644)
        self.assertIsNone(media_linkedin.news_config(self.home))
        self.write({"origin": "https://evil.example", "token": TOKEN})
        self.assertIsNone(media_linkedin.news_config(self.home))
        self.write({"origin": "http://127.0.0.1:8790", "token": "short"})
        self.assertIsNone(media_linkedin.news_config(self.home))

    def test_unconfigured_overview_says_so(self):
        self.assertEqual(media_linkedin.overview(home=self.home), {"state": "not_configured"})


class ForwardingTests(unittest.TestCase):
    def test_overview_combines_schedule_and_news(self):
        calls = []

        def fake(method, path, body=None, **kwargs):
            calls.append((method, path))
            return 200, {"slots": ["09:00"]} if path.endswith("schedule") else {"items": [{"id": "x"}]}

        with patch.object(media_linkedin, "call", side_effect=fake):
            result = media_linkedin.overview()
        self.assertEqual(result, {"state": "ready", "schedule": {"slots": ["09:00"]}, "news": [{"id": "x"}]})
        self.assertEqual(calls, [("GET", "/media-control/schedule"), ("GET", "/media-control/news")])

    def test_inputs_are_validated_before_forwarding(self):
        with patch.object(media_linkedin, "call", return_value=(200, {})) as call:
            for bad in ({"slots": "09:00"}, {"slots": ["9h"]}, {"slots": ["10:00"] * 11}):
                with self.assertRaises(ValueError):
                    media_linkedin.save_schedule(bad)
            with self.assertRaises(ValueError):
                media_linkedin.preview({"article_id": "../../admin"})
            with self.assertRaises(ValueError):
                media_linkedin.send_batch({"items": []})
            call.assert_not_called()
            media_linkedin.save_schedule({"slots": [" 09:00", "18:30"]})
            call.assert_called_with("PUT", "/media-control/schedule", {"slots": ["09:00", "18:30"]}, home=None)
            media_linkedin.preview({"article_id": "11111111-1111-4111-8111-111111111111"})
            self.assertEqual(call.call_args.args[1],
                             "/media-control/news/11111111-1111-4111-8111-111111111111/preview")
            media_linkedin.send_batch({"items": [
                {"candidate_id": "22222222-2222-4222-8222-222222222222", "preview": {"signature": "s"}}]})
            self.assertEqual(call.call_args.args[:2], ("POST", "/media-control/send-batch"))

    def test_rewrite_forwards_a_clean_bounded_instruction(self):
        cid = "33333333-3333-4333-8333-333333333333"
        with patch.object(media_linkedin, "call", return_value=(200, {})) as call:
            for bad in ({"candidate_id": "../x", "instruction": "short"},
                        {"candidate_id": cid, "instruction": "   "},
                        {"candidate_id": cid, "instruction": "x" * 301},
                        {"candidate_id": cid, "instruction": ["short"]}):
                with self.assertRaises(ValueError):
                    media_linkedin.rewrite(bad)
            call.assert_not_called()
            media_linkedin.rewrite({"candidate_id": cid, "instruction": "  сделай\n короче "})
            self.assertEqual(call.call_args.args,
                             ("POST", f"/media-control/candidates/{cid}/rewrite", {"instruction": "сделай короче"}))
            self.assertEqual(call.call_args.kwargs["timeout"], 240)


class ServerTests(unittest.TestCase):
    def handler(self, *, owner, method="GET", path="/api/media/linkedin", body=None):
        handler = SERVER.Handler.__new__(SERVER.Handler)
        handler.command = method
        response = {}
        handler._json_response = lambda status, payload: response.update(status=status, payload=payload)
        handler._decision_owner_authorized = lambda: owner
        raw = json.dumps(body or {}).encode()
        handler.headers = {"Content-Type": "application/json", "Content-Length": str(len(raw)), "Host": "localhost"}
        handler.rfile = io.BytesIO(raw)
        handler.path = path
        return handler, response

    def test_get_requires_owner(self):
        handler, response = self.handler(owner=False)
        with patch.object(media_linkedin, "overview") as overview:
            handler.do_GET()
            overview.assert_not_called()
        self.assertEqual(response["status"], 401)
        handler, response = self.handler(owner=True)
        with patch.object(media_linkedin, "overview", return_value={"state": "ready"}):
            handler.do_GET()
        self.assertEqual(response, {"status": 200, "payload": {"state": "ready"}})

    def test_actions_require_owner_and_forward_status(self):
        handler, response = self.handler(owner=False, method="POST", path="/api/media/linkedin/schedule",
                                         body={"slots": ["09:00"]})
        handler.do_POST()
        self.assertEqual(response["status"], 401)
        handler, response = self.handler(owner=True, method="POST", path="/api/media/linkedin/schedule",
                                         body={"slots": ["09:00"]})
        with patch.object(media_linkedin, "call", return_value=(422, {"detail": "too close"})):
            handler.do_POST()
        self.assertEqual(response, {"status": 422, "payload": {"detail": "too close"}})
        handler, response = self.handler(owner=True, method="POST", path="/api/media/linkedin/preview",
                                         body={"article_id": "nope"})
        handler.do_POST()
        self.assertEqual(response["status"], 400)
        rewrite = {"candidate_id": "33333333-3333-4333-8333-333333333333", "instruction": "короче"}
        handler, response = self.handler(owner=False, method="POST", path="/api/media/linkedin/rewrite",
                                         body=rewrite)
        with patch.object(media_linkedin, "call") as call:
            handler.do_POST()
            call.assert_not_called()
        self.assertEqual(response["status"], 401)
        handler, response = self.handler(owner=True, method="POST", path="/api/media/linkedin/rewrite",
                                         body=rewrite)
        with patch.object(media_linkedin, "call", return_value=(200, {"text": "t", "preview": {}})):
            handler.do_POST()
        self.assertEqual(response, {"status": 200, "payload": {"text": "t", "preview": {}}})


class PageTests(unittest.TestCase):
    def test_media_tab_is_a_stable_route_with_owner_controls(self):
        self.assertIn("aria-controls=\"section-media\"", PAGE)
        self.assertIn("onclick=\"showSection('media')\"", PAGE)
        self.assertIn("if (name === 'media') setTimeout(mediaLoad, 0);", PAGE)
        for element in ("media-slots", "media-add-form", "media-save-slots", "media-upcoming",
                        "media-posts", "media-news", "media-prepare", "media-review", "media-send"):
            self.assertIn(f'id="{element}"', PAGE)
        self.assertIn("/api/media/linkedin", PAGE)
        # Titles from the news service are escaped before they reach innerHTML.
        self.assertIn("mediaEsc(item.title)", PAGE)
        self.assertIn("mediaEsc(post.title)", PAGE)


if __name__ == "__main__":
    unittest.main()
