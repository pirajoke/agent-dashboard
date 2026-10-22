"""Owner edits to Platforms cards (Mark 2026-10-20: «кнопку Эдит … название, статус, приоритетность»)."""
from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from dashboard_builder.platform_edits import load_edits, save_card_edit, save_edits, validate_edits

BUILDER = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("dashboard_platform_edits_test", BUILDER / "dashboard-server-m4.py")
SERVER = importlib.util.module_from_spec(spec)
spec.loader.exec_module(SERVER)


class PlatformEditsStoreTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "nested" / "platform-edits.json"

    def test_round_trip_keeps_only_real_changes(self):
        record = save_edits(self.path, {"edits": {
            "financial": {"name": "  JobRadar   Pro ", "status": "На паузе", "priority": "normal"},
            "n8n": {"name": "", "status": "   "},
        }})
        self.assertEqual(record["edits"], {"financial": {"name": "JobRadar Pro", "status": "На паузе", "priority": "normal"}})
        self.assertEqual(load_edits(self.path)["edits"], record["edits"])
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_card_edit_keeps_other_cards_and_reset_removes_only_that_card(self):
        # Two devices: the laptop renames A, then a phone with an older page changes B.
        save_card_edit(self.path, {"card": "financial", "edit": {"name": "JobRadar Pro"}})
        save_card_edit(self.path, {"card": "health", "edit": {"status": "На паузе", "description": "Сон  и\nшаги"}})
        self.assertEqual(load_edits(self.path)["edits"], {
            "financial": {"name": "JobRadar Pro"}, "health": {"status": "На паузе", "description": "Сон и шаги"}})
        # A tab opened before descriptions existed (no "v") renames the card: the description stays.
        save_card_edit(self.path, {"card": "health", "edit": {"name": "Здоровье"}})
        self.assertEqual(load_edits(self.path)["edits"]["health"],
                         {"name": "Здоровье", "description": "Сон и шаги"})
        save_card_edit(self.path, {"card": "health", "edit": {"status": "На паузе", "description": "Сон и шаги"}, "v": 2})
        save_card_edit(self.path, {"card": "financial", "edit": None})
        self.assertEqual(load_edits(self.path)["edits"], {"health": {"status": "На паузе", "description": "Сон и шаги"}})
        for bad in ({"card": "../x", "edit": {"name": "a"}}, {"card": 5}, {"edits": {}}, {"card": "a", "edit": {"url": "x"}}):
            with self.subTest(bad=str(bad)), self.assertRaises(ValueError):
                save_card_edit(self.path, bad)

    def test_missing_or_broken_store_means_no_edits(self):
        self.assertEqual(load_edits(self.path)["edits"], {})
        self.path.parent.mkdir(parents=True)
        self.path.write_text("{not json")
        self.assertEqual(load_edits(self.path)["edits"], {})

    def test_rejects_malformed_input(self):
        for payload in (
            [], {"edits": []}, {"edits": {"../x": {"name": "a"}}}, {"edits": {"a": {"name": 5}}},
            {"edits": {"a": {"name": "x" * 61}}}, {"edits": {"a": {"status": "s" * 41}}},
            {"edits": {"a": {"priority": "top"}}}, {"edits": {"a": {"description": "d" * 201}}}, {"edits": {"a": {"name": "a‮b"}}},
            {"edits": {"a": {"url": "https://evil.invalid"}}},
            {"edits": {f"c{i}": {"name": "x"} for i in range(61)}},
        ):
            with self.subTest(payload=str(payload)[:60]):
                with self.assertRaises(ValueError):
                    validate_edits(payload)


class PlatformEditsEndpointTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "platform-edits.json"

    def call(self, method, body=None, *, token="fixture-owner", origin=None, content_type="application/json", raw=None):
        handler = SERVER.Handler.__new__(SERVER.Handler)
        handler.path, handler.command = "/api/platform-edits", method
        data = raw if raw is not None else json.dumps(body or {}).encode()
        handler.headers = {"Host": "localhost:9999", "Content-Length": str(len(data)), "Content-Type": content_type}
        if token is not None:
            handler.headers["X-Dashboard-Run-Token"] = token
        if origin is not None:
            handler.headers["Origin"] = origin
        handler.rfile = io.BytesIO(data)
        output = {}
        handler._json_response = lambda status, payload: output.update(status=status, payload=payload)
        with (patch.object(SERVER, "PLATFORM_EDITS_FILE", self.path),
              patch.object(SERVER, "_dashboard_run_token", return_value="fixture-owner")):
            getattr(handler, f"do_{method}")()
        return output

    def test_owner_saves_and_reads_back_from_any_device(self):
        save_edits(self.path, {"edits": {"jarvis": {"status": "Работает"}}})
        body = {"card": "health", "edit": {"name": "Здоровье", "priority": "main"}}
        saved = self.call("POST", body, origin="http://localhost:9999")
        self.assertEqual(saved["status"], 200)
        read = self.call("GET")
        self.assertEqual(read["status"], 200)
        self.assertEqual(read["payload"]["edits"], {
            "jarvis": {"status": "Работает"}, "health": {"name": "Здоровье", "priority": "main"}})

    def test_anonymous_wrong_token_cross_origin_or_bad_body_cannot_write(self):
        body = {"card": "health", "edit": {"name": "x"}}
        for kwargs, status in (
            ({"token": None}, 401), ({"token": "wrong"}, 401),
            ({"origin": "https://foreign.invalid"}, 403), ({"content_type": "text/plain"}, 415),
            ({"raw": b"{oops"}, 400), ({"raw": b""}, 400),
        ):
            with self.subTest(kwargs=str(kwargs)):
                self.assertEqual(self.call("POST", body, **kwargs)["status"], status)
                self.assertFalse(self.path.exists())

    def test_anonymous_read_reveals_nothing(self):
        save_edits(self.path, {"edits": {"health": {"name": "Секретное имя"}}})
        result = self.call("GET", token=None)
        self.assertEqual(result["status"], 401)
        self.assertNotIn("Секретное", json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
