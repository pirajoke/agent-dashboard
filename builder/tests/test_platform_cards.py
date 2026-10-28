"""Owner-made Platforms cards (Mark 2026-10-21: «создавать проекты, вставлять ссылки, описывать, вставлять фотки»)."""
from __future__ import annotations

import base64
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from dashboard_builder.platform_cards import IMAGE_MAX_BYTES, MAX_CARDS, StoreUnavailable, change_cards, load_cards, validate_card

BUILDER = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("dashboard_platform_cards_test", BUILDER / "dashboard-server-m4.py")
SERVER = importlib.util.module_from_spec(spec)
spec.loader.exec_module(SERVER)

PNG = "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\0" * 32).decode()
WEBP = "data:image/webp;base64," + base64.b64encode(b"RIFF\0\0\0\0WEBPVP8 " + b"\0" * 16).decode()


def ids(*values):
    return iter(values).__next__


class PlatformCardsStoreTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "nested" / "platform-cards.json"

    def test_create_edit_and_delete_round_trip(self):
        record = change_cards(self.path, {"action": "save", "card": {
            "name": "  Новый   проект ", "description": "Лендинг\nдля клиента", "status": "Делаем",
            "priority": "main", "image": PNG,
            "links": [{"kind": "site", "url": "https://example.com/a?b=1"}, {"kind": "telegram", "url": "https://t.me/x"}],
        }}, new_id=ids("c-0000000a", "c-0000000b"))
        self.assertEqual(record["id"], "c-0000000a")
        card = load_cards(self.path)["cards"][0]
        self.assertEqual(card["name"], "Новый проект")
        self.assertEqual(card["description"], "Лендинг для клиента")
        self.assertEqual(card["image"], PNG)
        self.assertEqual([link["kind"] for link in card["links"]], ["site", "telegram"])
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

        change_cards(self.path, {"action": "save", "card": {"name": "Второй", "image": WEBP}}, new_id=ids("c-0000000b"))
        change_cards(self.path, {"action": "save", "card": {"id": "c-0000000a", "name": "Переименован"}})
        cards = load_cards(self.path)["cards"]
        self.assertEqual([c["name"] for c in cards], ["Переименован", "Второй"])
        self.assertNotIn("image", cards[0])  # A save replaces the whole card.
        self.assertEqual(cards[0]["priority"], "normal")
        self.assertNotIn("group", cards[0])  # Saved without a group: the page shows it under «Личные».
        change_cards(self.path, {"action": "save", "card": {"id": "c-0000000b", "name": "Второй", "group": "product"}})
        self.assertEqual(load_cards(self.path)["cards"][1]["group"], "product")

        change_cards(self.path, {"action": "delete", "id": "c-0000000a"})
        self.assertEqual([c["id"] for c in load_cards(self.path)["cards"]], ["c-0000000b"])
        with self.assertRaises(LookupError):
            change_cards(self.path, {"action": "delete", "id": "c-0000000a"})
        with self.assertRaises(LookupError):
            change_cards(self.path, {"action": "save", "card": {"id": "c-0000000f", "name": "x"}})

    def test_rejects_unsafe_or_malformed_cards(self):
        bad_cards = (
            {}, {"name": ""}, {"name": "x" * 61}, {"name": "a", "status": "s" * 41},
            {"name": "a", "description": "d" * 201}, {"name": "a", "priority": "top"},
            {"name": "a", "group": "work"},
            {"name": "a", "html": "<b>"},
            {"name": "a", "links": [{"url": "javascript:alert(1)"}]},
            {"name": "a", "links": [{"url": "data:text/html,x"}]},
            {"name": "a", "links": [{"url": "https://"}]},
            {"name": "a", "links": [{"kind": "ftp", "url": "https://x.y"}]},
            {"name": "a", "links": [{"url": "https://x.y", "onclick": "x"}]},
            {"name": "a", "links": [{"url": "https://x.y"}] * 5},
            {"name": "a", "image": "https://example.com/a.png"},
            {"name": "a", "image": "data:image/svg+xml;base64,PHN2Zz4="},
            {"name": "a", "image": "data:image/png;base64," + base64.b64encode(b"GIF89a....").decode()},
            {"name": "a", "image": "data:image/png;base64,@@@"},
            {"name": "a", "image": "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\0" * IMAGE_MAX_BYTES).decode()},
        )
        for card in bad_cards:
            with self.subTest(card=str(card)[:80]), self.assertRaises(ValueError):
                validate_card(card, "c-00000001")
        for payload in ([], {"action": "drop"}, {"action": "delete", "id": "../x"},
                        {"action": "save", "card": {"id": "health", "name": "a"}},
                        {"action": "save", "card": {"name": "a"}, "extra": 1}):
            with self.subTest(payload=str(payload)), self.assertRaises(ValueError):
                change_cards(self.path, payload)
        self.assertFalse(self.path.exists())

    def test_limit_and_broken_store(self):
        self.assertEqual(load_cards(self.path)["cards"], [])
        self.path.parent.mkdir(parents=True)
        # A damaged store is not "no cards": saving on top of it would wipe them all.
        self.path.write_text("{not json")
        with self.assertRaises(StoreUnavailable):
            load_cards(self.path)
        with self.assertRaises(StoreUnavailable):
            change_cards(self.path, {"action": "save", "card": {"name": "new"}})
        self.assertEqual(self.path.read_text(), "{not json")
        good = [{"id": f"c-{i:08x}", "name": f"P{i}", "priority": "normal", "links": []} for i in range(MAX_CARDS)]
        self.path.write_text(json.dumps({"cards": [{"id": "x", "name": "bad"}, {"id": "c-ffffffff"}] + good}))
        self.assertEqual(len(load_cards(self.path)["cards"]), MAX_CARDS - 2)
        self.path.write_text(json.dumps({"cards": good}))
        with self.assertRaises(ValueError):
            change_cards(self.path, {"action": "save", "card": {"name": "one more"}})


class PlatformCardsEndpointTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "platform-cards.json"

    def call(self, method, body=None, *, token="fixture-owner", origin=None, content_type="application/json", raw=None):
        handler = SERVER.Handler.__new__(SERVER.Handler)
        handler.path, handler.command = "/api/platform-cards", method
        data = raw if raw is not None else json.dumps(body or {}).encode()
        handler.headers = {"Host": "localhost:9999", "Content-Length": str(len(data)), "Content-Type": content_type}
        if token is not None:
            handler.headers["X-Dashboard-Run-Token"] = token
        if origin is not None:
            handler.headers["Origin"] = origin
        handler.rfile = io.BytesIO(data)
        output = {}
        handler._json_response = lambda status, payload: output.update(status=status, payload=payload)
        with (patch.object(SERVER, "PLATFORM_CARDS_FILE", self.path),
              patch.object(SERVER, "_dashboard_run_token", return_value="fixture-owner")):
            getattr(handler, f"do_{method}")()
        return output

    def test_owner_creates_edits_deletes_and_reads_from_any_device(self):
        saved = self.call("POST", {"action": "save", "card": {"name": "Лендинг", "image": PNG,
                                                              "links": [{"kind": "site", "url": "https://example.com"}]}},
                          origin="http://localhost:9999")
        self.assertEqual(saved["status"], 200)
        card_id = saved["payload"]["id"]
        read = self.call("GET")
        self.assertEqual(read["status"], 200)
        self.assertEqual([c["id"] for c in read["payload"]["cards"]], [card_id])
        self.assertEqual(self.call("POST", {"action": "save", "card": {"id": card_id, "name": "Новое"}})["status"], 200)
        self.assertEqual(self.call("GET")["payload"]["cards"][0]["name"], "Новое")
        bad = self.call("POST", {"action": "save", "card": {"name": "a", "links": [{"url": "javascript:x"}]}})
        self.assertEqual((bad["status"], bad["payload"]["reason"]), (400, "invalid_url"))
        self.assertEqual(self.call("POST", {"action": "delete", "id": card_id})["status"], 200)
        self.assertEqual(self.call("POST", {"action": "delete", "id": card_id})["status"], 404)
        self.assertEqual(self.call("GET")["payload"]["cards"], [])

    def test_anonymous_wrong_token_cross_origin_or_bad_body_cannot_write(self):
        body = {"action": "save", "card": {"name": "x"}}
        for kwargs, status in (
            ({"token": None}, 401), ({"token": "wrong"}, 401),
            ({"origin": "https://foreign.invalid"}, 403), ({"content_type": "text/plain"}, 415),
            ({"raw": b"{oops"}, 400), ({"raw": b""}, 400),
        ):
            with self.subTest(kwargs=str(kwargs)):
                self.assertEqual(self.call("POST", body, **kwargs)["status"], status)
                self.assertFalse(self.path.exists())

    def test_damaged_store_answers_unavailable_and_is_not_overwritten(self):
        self.path.write_text("{not json")
        self.assertEqual(self.call("GET")["status"], 503)
        self.assertEqual(self.call("POST", {"action": "save", "card": {"name": "x"}})["status"], 503)
        self.assertEqual(self.path.read_text(), "{not json")

    def test_anonymous_read_reveals_nothing(self):
        change_cards(self.path, {"action": "save", "card": {"name": "Секретный проект"}})
        result = self.call("GET", token=None)
        self.assertEqual(result["status"], 401)
        self.assertNotIn("Секретный", json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
