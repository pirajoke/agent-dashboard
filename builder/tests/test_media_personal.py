"""«Медиа» → «Личное» (Mark 2026-11-24): owner-only list of his published generations."""
from __future__ import annotations

import importlib.util
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dashboard_builder import media_personal

BUILDER = Path(__file__).resolve().parents[1]
PAGE = (BUILDER / "mac-mini-dashboard" / "index.html").read_text()
spec = importlib.util.spec_from_file_location("dashboard_media_personal_test", BUILDER / "dashboard-server-m4.py")
SERVER = importlib.util.module_from_spec(spec)
spec.loader.exec_module(SERVER)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.base = Path(tempfile.mkdtemp())
        self.video = self.base / "src.mp4"
        self.video.write_bytes(b"0123456789")

    def test_add_copies_file_and_lists_newest_first(self):
        old = media_personal.add(file=str(self.video), url=None, title="Старое", where=["X"], published="2026-11-01", base=self.base)
        new = media_personal.add(file=None, url="https://t.me/x/1", title="Интро", where=["Кружок Риса"], published="2026-11-17", base=self.base)
        data = media_personal.overview(self.base)
        self.assertEqual(data["state"], "ready")
        self.assertEqual([i["id"] for i in data["items"]], [new["id"], old["id"]])
        self.assertEqual(data["items"][1]["kind"], "video")
        self.assertEqual(data["items"][1]["src"], f"/api/media/personal/file?id={old['id']}")
        self.assertEqual(data["items"][0]["kind"], "link")
        path, mime = media_personal.file_for(old["id"], self.base)
        self.assertEqual((path.read_bytes(), mime), (b"0123456789", "video/mp4"))

    def test_rejects_bad_input(self):
        with self.assertRaises(ValueError):
            media_personal.add(file=None, url=None, title="x", where=[], published="", base=self.base)
        with self.assertRaises(ValueError):
            media_personal.add(file=None, url="http://insecure", title="x", where=[], published="", base=self.base)
        with self.assertRaises(ValueError):
            media_personal.file_for("../etc", self.base)

    def test_traversal_symlink_and_unknown_type_are_not_served(self):
        (self.base / "files").mkdir()
        os.symlink(self.video, self.base / "files" / "link.mp4")
        (self.base / "files" / "a.txt").write_text("x")
        items = [
            {"id": "bad-trav", "title": "t", "file": "../src.mp4"},
            {"id": "bad-link", "title": "t", "file": "link.mp4"},
            {"id": "bad-type", "title": "t", "file": "a.txt"},
        ]
        (self.base / "items.json").write_text(json.dumps({"items": items}))
        for item in items:
            self.assertIsNone(media_personal.file_for(item["id"], self.base))
        self.assertEqual(media_personal.overview(self.base)["items"], [])

    def test_broken_store_is_unavailable_not_crash(self):
        (self.base / "items.json").write_text("{")
        self.assertEqual(media_personal.overview(self.base)["state"], "unavailable")
        self.assertEqual(media_personal.overview(self.base / "missing")["items"], [])


class FakeHandler:
    def __init__(self, range_header=""):
        self.headers = {"Range": range_header} if range_header else {}
        self.command = "GET"
        self.status = None
        self.sent = {}
        self.wfile = io.BytesIO()
        self.json = None

    def send_response(self, status):
        self.status = status

    def send_header(self, key, value):
        self.sent[key] = str(value)

    def end_headers(self):
        pass

    def _json_response(self, status, payload):
        self.status, self.json = status, payload


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.base = Path(tempfile.mkdtemp())
        src = self.base / "v.mp4"
        src.write_bytes(b"abcdefghij")
        self.item = media_personal.add(file=str(src), url=None, title="v", where=[], published="2026-11-17", base=self.base)
        patcher = patch.dict(os.environ, {"MEDIA_PERSONAL_DIR": str(self.base)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def serve(self, range_header=""):
        handler = FakeHandler(range_header)
        SERVER.Handler._handle_media_personal_file(handler, self.item["id"])
        return handler

    def test_full_and_ranged_reads(self):
        full = self.serve()
        self.assertEqual((full.status, full.wfile.getvalue()), (200, b"abcdefghij"))
        self.assertEqual(full.sent["Accept-Ranges"], "bytes")
        part = self.serve("bytes=2-4")
        self.assertEqual((part.status, part.wfile.getvalue(), part.sent["Content-Range"]), (206, b"cde", "bytes 2-4/10"))
        tail = self.serve("bytes=-3")
        self.assertEqual(tail.wfile.getvalue(), b"hij")
        self.assertEqual(self.serve("bytes=20-").status, 416)

    def test_routes_are_owner_only(self):
        source = (BUILDER / "dashboard-server-m4.py").read_text()
        for route in ("'/api/media/personal'", "'/api/media/personal/file'"):
            block = source.split(f"if parsed.path == {route}:", 1)[1][:200]
            self.assertIn("_decision_owner_authorized", block)


class PageTests(unittest.TestCase):
    def test_personal_tab_and_view(self):
        self.assertIn('id="media-tab-personal" data-channel="personal"', PAGE)
        self.assertIn('id="media-view-personal"', PAGE)
        self.assertIn("'linkedin', 'telegram', 'x', 'personal'", PAGE)
        self.assertIn("/api/media/personal", PAGE)


if __name__ == "__main__":
    unittest.main()
