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
            if path.endswith("today"):
                return today_reply
            if path.endswith("comments"):
                return comments_reply
            return 200, {"slots": ["09:00"]} if path.endswith("schedule") else {"items": [{"id": "x"}]}

        today_reply = (200, {"drafts": [{"id": "d"}], "queued": []})
        comments_reply = (200, {"send_enabled": False, "items": []})
        with patch.object(media_linkedin, "call", side_effect=fake):
            result = media_linkedin.overview()
        self.assertEqual(result, {"state": "ready", "schedule": {"slots": ["09:00"]}, "news": [{"id": "x"}],
                                  "today": {"drafts": [{"id": "d"}], "queued": []},
                                  "comments": {"send_enabled": False, "items": []}})
        self.assertEqual(calls, [("GET", "/media-control/schedule"), ("GET", "/media-control/news"),
                                 ("GET", "/media-control/today"), ("GET", "/media-control/comments")])
        # An older news service without /today or /comments still gives the rest of the tab.
        today_reply = (404, {})
        comments_reply = (404, {})
        with patch.object(media_linkedin, "call", side_effect=fake):
            result = media_linkedin.overview()
        self.assertIsNone(result["today"])
        self.assertIsNone(result["comments"])

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

    def test_comment_actions_validate_before_forwarding(self):
        cid = "55555555-5555-4555-8555-555555555555"
        post = "https://www.linkedin.com/feed/update/urn:li:share:7391234567890123456/"
        with patch.object(media_linkedin, "call", return_value=(200, {})) as call:
            for fn, bad in (
                (media_linkedin.comment_create, {"url": "https://evil.example/x"}),
                (media_linkedin.comment_create, {"url": "http://www.linkedin.com/feed/"}),
                (media_linkedin.comment_create, {"url": post, "post_text": "x" * 8001}),
                (media_linkedin.comment_text, {"comment_id": cid, "text": "x" * 1251}),
                (media_linkedin.comment_text, {"comment_id": "../x", "text": "ok"}),
                (media_linkedin.comment_rewrite, {"comment_id": cid, "instruction": "  "}),
                (media_linkedin.comment_send, {"comment_id": cid, "text_sha256": "abc"}),
                (media_linkedin.comment_close, {"comment_id": cid, "action": "send"}),
            ):
                with self.assertRaises(ValueError):
                    fn(bad)
            call.assert_not_called()
            media_linkedin.comment_create({"url": " " + post, "post_text": " Text "})
            self.assertEqual(call.call_args.args,
                             ("POST", "/media-control/comments", {"url": post, "post_text": "Text"}))
            media_linkedin.comment_send({"comment_id": cid, "text_sha256": "a" * 64})
            self.assertEqual(call.call_args.args,
                             ("POST", f"/media-control/comments/{cid}/send", {"text_sha256": "a" * 64}))
            media_linkedin.comment_close({"comment_id": cid, "action": "manual"})
            self.assertEqual(call.call_args.args[1], f"/media-control/comments/{cid}/manual")
            media_linkedin.comment_rewrite({"comment_id": cid, "instruction": " Короче  "})
            self.assertEqual(call.call_args.args[2], {"instruction": "Короче"})

    def test_page_has_comment_panel_and_routes(self):
        self.assertIn('id="media-comments"', PAGE)
        self.assertIn("mediaPost('comment-send'", PAGE)
        for path in ("comment", "comment-text", "comment-rewrite", "comment-send", "comment-close"):
            self.assertIn(f"/api/media/linkedin/{path}", SERVER.MEDIA_LINKEDIN_ACTIONS)

    def test_edit_forwards_the_owner_text_within_limits(self):
        cid = "44444444-4444-4444-8444-444444444444"
        with patch.object(media_linkedin, "call", return_value=(200, {})) as call:
            for bad in ({"candidate_id": "../x", "text": "t"},
                        {"candidate_id": cid, "text": "  \n "},
                        {"candidate_id": cid, "text": "x" * 3001},
                        {"candidate_id": cid, "text": None}):
                with self.assertRaises(ValueError):
                    media_linkedin.edit(bad)
            call.assert_not_called()
            media_linkedin.edit({"candidate_id": cid, "text": "  🤖 Title\n\n• Fact  "})
            self.assertEqual(call.call_args.args,
                             ("POST", f"/media-control/candidates/{cid}/text", {"text": "🤖 Title\n\n• Fact"}))

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
        handler, response = self.handler(owner=False, method="POST", path="/api/media/linkedin/edit",
                                         body={"candidate_id": "33333333-3333-4333-8333-333333333333", "text": "t"})
        with patch.object(media_linkedin, "call") as call:
            handler.do_POST()
            call.assert_not_called()
        self.assertEqual(response["status"], 401)
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


class SettingsTests(unittest.TestCase):
    """«Настройки Медиа» (Mark 2026-11-02): posts per day, 1–10, owner only."""

    def test_posts_per_day_is_validated_before_forwarding(self):
        with patch.object(media_linkedin, "call", return_value=(200, {})) as call:
            for bad in ({}, {"posts_per_day": 0}, {"posts_per_day": 11}, {"posts_per_day": "5"},
                        {"posts_per_day": 2.5}, {"posts_per_day": True}):
                with self.assertRaises(ValueError):
                    media_linkedin.save_settings(bad)
            call.assert_not_called()
            media_linkedin.save_settings({"posts_per_day": 3})
            call.assert_called_with("PUT", "/media-control/settings", {"posts_per_day": 3}, home=None)

    def test_settings_route_requires_owner(self):
        make = ServerTests.handler.__get__(ServerTests())
        handler, response = make(owner=False, method="POST", path="/api/media/linkedin/settings",
                                 body={"posts_per_day": 5})
        with patch.object(media_linkedin, "call") as call:
            handler.do_POST()
            call.assert_not_called()
        self.assertEqual(response["status"], 401)
        handler, response = make(owner=True, method="POST", path="/api/media/linkedin/settings",
                                 body={"posts_per_day": 5})
        reply = {"settings": {"posts_per_day": 5}, "budget": {}}
        with patch.object(media_linkedin, "call", return_value=(200, reply)) as call:
            handler.do_POST()
        call.assert_called_with("PUT", "/media-control/settings", {"posts_per_day": 5}, home=None)
        self.assertEqual(response, {"status": 200, "payload": reply})
        handler, response = make(owner=True, method="POST", path="/api/media/linkedin/settings",
                                 body={"posts_per_day": 50})
        handler.do_POST()
        self.assertEqual(response["status"], 400)

    def test_page_has_settings_window(self):
        for element in ("media-settings-open", "media-settings-dialog", "media-per-day", "media-settings-save"):
            self.assertIn(f'id="{element}"', PAGE)
        self.assertIn("mediaPost('settings'", PAGE)


class _FakeImageReply:
    def __init__(self, data, mime):
        self.data, self.headers = data, {"Content-Type": mime}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, limit=-1):
        return self.data[:limit] if limit >= 0 else self.data


class ImageTests(unittest.TestCase):
    """Mark 2026-11-02: the «Медиа» post card shows the post's picture too."""
    ID = "33333333-3333-4333-8333-333333333333"

    def setUp(self):
        patcher = patch.dict(os.environ, {"JARVIS_NEWS_URL": "http://127.0.0.1:8790",
                                          "JARVIS_NEWS_CONTROL_TOKEN": TOKEN})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_image_is_fetched_with_the_service_token_and_checked(self):
        with patch.object(media_linkedin._OPENER, "open",
                          return_value=_FakeImageReply(b"\x89PNG", "image/png")) as opener:
            self.assertEqual(media_linkedin.image(self.ID), (b"\x89PNG", "image/png"))
        request = opener.call_args.args[0]
        self.assertEqual(request.full_url, f"http://127.0.0.1:8790/media-control/candidates/{self.ID}/image")
        self.assertEqual(request.get_header("Authorization"), "Bearer " + TOKEN)
        # Anything that is not a plain picture never reaches the page.
        with patch.object(media_linkedin._OPENER, "open", return_value=_FakeImageReply(b"<svg/>", "image/svg+xml")):
            self.assertIsNone(media_linkedin.image(self.ID))
        with patch.object(media_linkedin._OPENER, "open", return_value=_FakeImageReply(b"{}", "application/json")):
            self.assertIsNone(media_linkedin.image(self.ID))
        with self.assertRaises(ValueError):
            media_linkedin.image("../schedule")

    def test_older_news_service_without_the_route_means_no_picture(self):
        error = media_linkedin.urllib.error.HTTPError("u", 404, "nf", {}, io.BytesIO(b""))
        with patch.object(media_linkedin._OPENER, "open", side_effect=error):
            self.assertIsNone(media_linkedin.image(self.ID))

    def test_server_route_is_owner_only(self):
        server = ServerTests()
        handler, response = server.handler(owner=False, path=f"/api/media/linkedin/image?id={self.ID}")
        with patch.object(media_linkedin, "image") as image:
            handler.do_GET()
            image.assert_not_called()
        self.assertEqual(response["status"], 401)
        handler, response = server.handler(owner=True, path=f"/api/media/linkedin/image?id={self.ID}")
        sent = []
        handler.send_response = lambda code: sent.append(code)
        handler.send_header = lambda name, value: sent.append((name, value))
        handler.end_headers = lambda: None
        handler.wfile = io.BytesIO()
        with patch.object(media_linkedin, "image", return_value=(b"\xff\xd8\xff", "image/jpeg")):
            handler.do_GET()
        self.assertEqual(sent[0], 200)
        self.assertIn(("Content-Type", "image/jpeg"), sent)
        self.assertIn(("Cache-Control", "private, no-store"), sent)
        self.assertEqual(handler.wfile.getvalue(), b"\xff\xd8\xff")
        handler, response = server.handler(owner=True, path=f"/api/media/linkedin/image?id={self.ID}")
        with patch.object(media_linkedin, "image", return_value=None):
            handler.do_GET()
        self.assertEqual(response["status"], 404)


class PageTests(unittest.TestCase):
    def test_media_tab_is_a_stable_route_with_owner_controls(self):
        self.assertIn("aria-controls=\"section-media\"", PAGE)
        self.assertIn("onclick=\"showSection('media')\"", PAGE)
        self.assertIn("if (name === 'media') setTimeout(mediaLoad, 0);", PAGE)
        for element in ("media-train", "media-train-stats", "media-post-dialog", "media-post-dialog-list", "media-slots",
                        "media-add-form", "media-save-slots", "media-news", "media-prepare", "media-review", "media-send"):
            self.assertIn(f'id="{element}"', PAGE)
        self.assertIn("/api/media/linkedin", PAGE)
        # Titles from the news service are escaped before they reach innerHTML.
        self.assertIn("mediaEsc(item.title)", PAGE)
        self.assertIn("mediaEsc(car.title)", PAGE)


if __name__ == "__main__":
    unittest.main()
