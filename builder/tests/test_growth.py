from __future__ import annotations

from datetime import date, datetime, timezone
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

BUILDER_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BUILDER_DIR))

from dashboard_builder.growth import PICTURES, growth_projection, parse_note  # noqa: E402
import re  # noqa: E402

NOTE = """# Мои точки роста
> intro

## Private Equity
- Картинка: pe
- Зачем: Понять сделки ([[Some Note|заметка]]).
- [x] Разобрать модели сделок
- [ ] Заполнить тезис

## Digital-монетизация
- Картинка: digital
- Проекты: shopify, TikTok Shop
- [X] Посчитать юнит-экономику
- [ ] Первая продажа
- [ ] Эксперимент

## Без шагов
- Картинка: unknown-picture
"""


def _day(root: Path, machine: str, day: str, sessions: list[dict]) -> None:
    path = root / "sessions" / machine / f"{day}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"sessions": sessions}), encoding="utf-8")


class GrowthTest(unittest.TestCase):
    def test_note_becomes_areas_with_steps_and_pictures(self):
        areas = parse_note(NOTE)
        self.assertEqual([a["title"] for a in areas], ["Private Equity", "Digital-монетизация", "Без шагов"])
        self.assertEqual(areas[0]["why"], "Понять сделки (заметка).")
        self.assertEqual([s["done"] for s in areas[1]["steps"]], [True, False, False])
        self.assertEqual(areas[1]["projects"], ["shopify", "tiktokshop"])
        self.assertEqual(areas[2]["picture"], "growth")

    def test_title_picks_a_picture_when_the_note_names_none(self):
        areas = parse_note("""## Трейдинг и инвестиции
## Сертификат PMP
## Электроника и роботы
## AI-агенты
- Картинка: chart
## Дизайн-агентство
## Личный бренд
## Свой подход к агентам
- Картинка: podcast
""")
        self.assertEqual([a["picture"] for a in areas],
                         ["trading", "pmp", "robots", "agents", "design", "podcast", "podcast"])

    def test_every_picture_has_a_drawing_on_the_page(self):
        html = (BUILDER_DIR / "mac-mini-dashboard" / "index.html").read_text(encoding="utf-8")
        drawn = set(re.findall(r'<symbol id="cc-growth-([a-z]+)"', html))
        listed = set(re.findall(r"'([a-z]+)'", re.search(r"const GROWTH_PICTURES = \[(.*?)\];", html).group(1)))
        self.assertEqual(PICTURES, drawn)
        self.assertEqual(PICTURES, listed)

    def test_owner_sees_progress_and_real_time_only_for_linked_projects(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            note = root / "note.md"
            note.write_text(NOTE, encoding="utf-8")
            _day(root, "macbook-pro", "2026-10-10", [
                {"project": "SHOPIFY", "active_minutes": 90},
                {"project": "TIKTOK SHOP", "active_minutes": 30},
                {"project": "financial-os", "active_minutes": 500},
            ])
            _day(root, "macbook-pro", "2026-08-01", [{"project": "SHOPIFY", "active_minutes": 999}])  # too old
            data = growth_projection(note, root, owner=True, today=date(2026, 10, 14))
        pe, digital, empty = data["areas"]
        self.assertEqual(pe["progress"], {"done": 1, "total": 2})
        self.assertIsNone(pe["minutes_30d"])  # no linked project: unknown, not zero
        self.assertEqual(digital["progress"], {"done": 1, "total": 3})
        self.assertEqual(digital["minutes_30d"], 120)
        self.assertEqual(empty["progress"], {"done": 0, "total": 0})
        self.assertTrue(data["time_available"])
        self.assertFalse(pe["linked"])
        self.assertNotIn("projects", digital)

    def test_broken_session_files_and_records_are_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            note = root / "note.md"
            note.write_text(NOTE, encoding="utf-8")
            _day(root, "macbook-pro", "2026-10-10", [None, "x", {"project": "SHOPIFY", "active_minutes": 45}])
            for day, body in (("2026-10-11", '{"sessions": {"project": "SHOPIFY"}}'), ("2026-10-12", "[1, 2]"),
                              ("2026-10-13", "{not json")):
                (root / "sessions" / "macbook-pro" / f"{day}.json").write_text(body, encoding="utf-8")
            data = growth_projection(note, root, owner=True, today=date(2026, 10, 14))
        self.assertTrue(data["time_available"])
        self.assertEqual(data["areas"][1]["minutes_30d"], 45)

    def test_missing_work_log_is_unknown_time_not_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            note = root / "note.md"
            note.write_text(NOTE, encoding="utf-8")
            data = growth_projection(note, root / "no-daily-work", owner=True, today=date(2026, 10, 14))
        self.assertFalse(data["time_available"])
        digital = data["areas"][1]
        self.assertTrue(digital["linked"])
        self.assertIsNone(digital["minutes_30d"])

    def test_note_untouched_for_a_month_is_stale(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            note = root / "note.md"
            note.write_text(NOTE, encoding="utf-8")
            changed = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc).timestamp()
            os.utime(note, (changed, changed))
            stale = growth_projection(note, root, owner=True, today=date(2026, 10, 14))
            fresh = growth_projection(note, root, owner=True, today=date(2026, 9, 20))
        self.assertEqual(stale["state"], "stale")
        self.assertEqual(stale["note_age_days"], 43)
        self.assertTrue(stale["note_updated_at"].startswith("2026-09-01"))
        self.assertIn("observed_at", stale)
        self.assertEqual(fresh["state"], "live")

    def test_public_view_is_a_count_and_missing_note_is_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            note = root / "note.md"
            self.assertEqual(growth_projection(note, root, owner=True)["state"], "empty")
            note.write_text(NOTE, encoding="utf-8")
            public = growth_projection(note, root, owner=False)
        self.assertEqual(public["count"], 3)
        self.assertEqual(public["areas"], [])
        self.assertNotIn("Private Equity", json.dumps(public, ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()


class GrowthEditTests(unittest.TestCase):
    """Mark 2026-10-22: «Точки роста» are edited on the site; the Obsidian note stays the one list."""

    NOTE = ("# Точки роста\n\nСвободный текст.\n\n## Private Equity и покупка бизнеса\n- Картинка: pe\n"
            "- Зачем: Купить бизнес.\n- [x] Разобрать модели сделок\n- [ ] Заполнить тезис [[Тезис|покупки]]\n\n"
            "Заметка между разделами.\n\n## Дизайн\n- [ ] Курс\n")

    def setUp(self):
        import uuid
        from dashboard_builder.growth import change_note
        self.change = lambda path, payload: change_note(
            path, {**payload, "request_id": str(uuid.uuid4())} if isinstance(payload, dict) else payload)
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "ТОЧКИ-РОСТА.md"
        self.path.write_text(self.NOTE, encoding="utf-8")

    def areas(self):
        from dashboard_builder.growth import parse_note
        return parse_note(self.path.read_text(encoding="utf-8"))

    def test_toggle_changes_only_that_line(self):
        area = self.areas()[0]
        self.change(self.path, {"action": "toggle", "area": area["id"], "step": 1, "text": "Заполнить тезис покупки", "done": True})
        self.assertEqual(self.path.read_text(), self.NOTE.replace("- [ ] Заполнить", "- [x] Заполнить"))
        self.change(self.path, {"action": "toggle", "area": area["id"], "step": 0, "text": "Разобрать модели сделок", "done": False})
        self.assertFalse(self.areas()[0]["steps"][0]["done"])

    def test_add_and_delete_step_and_add_area(self):
        self.change(self.path, {"action": "add_step", "area": "дизайн", "text": "  Собрать   портфолио "})
        self.change(self.path, {"action": "add_step", "area": self.areas()[0]["id"], "text": "Найти брокера"})
        text = self.path.read_text()
        self.assertIn("- [ ] Заполнить тезис [[Тезис|покупки]]\n- [ ] Найти брокера\n\nЗаметка между разделами.", text)
        self.assertTrue(text.endswith("- [ ] Курс\n- [ ] Собрать портфолио\n"))
        self.change(self.path, {"action": "delete_step", "area": "дизайн", "step": 0, "text": "Курс"})
        self.change(self.path, {"action": "add_area", "title": "Робототехника", "why": "Собрать робота"})
        areas = self.areas()
        self.assertEqual([area["title"] for area in areas], ["Private Equity и покупка бизнеса", "Дизайн", "Робототехника"])
        self.assertEqual([step["text"] for step in areas[1]["steps"]], ["Собрать портфолио"])
        self.assertEqual(areas[2]["why"], "Собрать робота")
        self.assertTrue(self.path.read_text().startswith("# Точки роста\n\nСвободный текст.\n"))

    def test_a_note_changed_in_obsidian_gives_a_conflict_not_a_wrong_tick(self):
        from dashboard_builder.growth import NoteConflict
        area = self.areas()[0]["id"]
        for payload in ({"action": "toggle", "area": area, "step": 0, "text": "Старый текст", "done": True},
                        {"action": "toggle", "area": area, "step": 9, "text": "x", "done": True},
                        {"action": "add_step", "area": "нет-такой", "text": "x"}):
            with self.assertRaises(NoteConflict):
                self.change(self.path, payload)
        self.assertEqual(self.path.read_text(), self.NOTE)

    def test_bad_input_is_refused(self):
        area = self.areas()[0]["id"]
        for payload in ({"action": "add_step", "area": area, "text": ""}, {"action": "add_step", "area": area, "text": "a\nb\x07"},
                        {"action": "add_area", "title": "x" * 81}, {"action": "toggle", "area": area, "step": 0,
                        "text": "Разобрать модели сделок", "done": "yes"}, {"action": "drop"}, []):
            with self.assertRaises(ValueError):
                self.change(self.path, payload)
        self.assertEqual(self.path.read_text(), self.NOTE)

    def test_a_repeated_request_applies_once_and_is_journaled(self):
        from dashboard_builder.growth import change_note
        journal = self.path.parent / "journal.jsonl"
        payload = {"action": "add_step", "area": "дизайн", "text": "Один раз", "request_id": "req-00000001"}
        self.assertTrue(change_note(self.path, payload, journal=journal))
        self.assertFalse(change_note(self.path, payload, journal=journal))
        self.assertEqual(self.path.read_text().count("Один раз"), 1)
        self.assertEqual(json.loads(journal.read_text())["request_id"], "req-00000001")
        with self.assertRaises(ValueError):
            change_note(self.path, {"action": "add_step", "area": "дизайн", "text": "x"})

    def test_a_save_in_obsidian_during_the_edit_is_never_overwritten(self):
        from unittest.mock import patch
        from dashboard_builder import growth
        # Obsidian saves the note right after the edit wrote its temporary file.
        with patch.object(growth.Path, "write_bytes", autospec=True, side_effect=lambda path, data: (
                Path.write_text(path, data.decode()), self.path.write_text(self.NOTE + "- [ ] Шаг из Obsidian\n", encoding="utf-8"))[0]):
            with self.assertRaises(growth.NoteConflict):
                self.change(self.path, {"action": "add_step", "area": "дизайн", "text": "С сайта"})
        self.assertIn("Шаг из Obsidian", self.path.read_text())
        self.assertNotIn("С сайта", self.path.read_text())

    def test_crlf_notes_keep_crlf(self):
        self.path.write_bytes(self.NOTE.replace("\n", "\r\n").encode())
        self.change(self.path, {"action": "add_step", "area": "дизайн", "text": "Шаг"})
        self.assertTrue(self.path.read_bytes().endswith(b"- [ ] \xd0\xa8\xd0\xb0\xd0\xb3\r\n"))


class GrowthEditEndpointTests(unittest.TestCase):
    def setUp(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("dashboard_growth_edit_test", Path(__file__).resolve().parents[1] / "dashboard-server-m4.py")
        self.server = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.server)
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "ТОЧКИ-РОСТА.md"
        self.path.write_text("## Дизайн\n- [ ] Курс\n", encoding="utf-8")

    def post(self, body, *, token="fixture-owner", host="command.meshly.fr", origin=None):
        import io
        from unittest.mock import patch
        handler = self.server.Handler.__new__(self.server.Handler)
        handler.path, handler.command = "/api/growth", "POST"
        import uuid
        data = json.dumps({**body, "request_id": str(uuid.uuid4())}).encode()
        handler.headers = {"Host": host, "Content-Length": str(len(data)), "Content-Type": "application/json"}
        if token:
            handler.headers["X-Dashboard-Run-Token"] = token
        if origin:
            handler.headers["Origin"] = origin
        handler.rfile = io.BytesIO(data)
        output = {}
        handler._json_response = lambda status, payload: output.update(status=status, payload=payload)
        with (patch.object(self.server, "GROWTH_NOTE_FILE", self.path),
              patch.object(self.server, "GROWTH_EDITS_JOURNAL", self.path.parent / "growth-edits.jsonl"),
              patch.object(self.server, "DAILY_WORK_DIR", self.path.parent / "none"),
              patch.object(self.server, "_dashboard_run_token", return_value="fixture-owner"),
              patch.object(self.server.Handler, "_cloudflare_access_owner", return_value=False)):
            handler.do_POST()
        return output

    def test_owner_edits_and_gets_the_new_list(self):
        result = self.post({"action": "toggle", "area": "дизайн", "step": 0, "text": "Курс", "done": True},
                           origin="https://command.meshly.fr")
        self.assertEqual(result["status"], 200)
        self.assertEqual(result["payload"]["areas"][0]["progress"], {"done": 1, "total": 1})
        self.assertEqual(self.post({"action": "toggle", "area": "дизайн", "step": 0, "text": "Другое", "done": True})["status"], 409)
        self.assertEqual(self.post({"action": "add_step", "area": "дизайн", "text": ""})["status"], 400)

    def test_anyone_else_cannot_write(self):
        for kwargs in ({"token": None}, {"token": "wrong"}, {"token": None, "host": "localhost:7777"}):
            self.assertEqual(self.post({"action": "add_area", "title": "x"}, **kwargs)["status"], 401)
        self.assertEqual(self.post({"action": "add_area", "title": "x"}, origin="https://evil.example")["status"], 403)
        self.assertEqual(self.path.read_text(encoding="utf-8"), "## Дизайн\n- [ ] Курс\n")
