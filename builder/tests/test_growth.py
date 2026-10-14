from __future__ import annotations

from datetime import date
import json
from pathlib import Path
import sys
import tempfile
import unittest

BUILDER_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BUILDER_DIR))

from dashboard_builder.growth import growth_projection, parse_note  # noqa: E402

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
        self.assertNotIn("projects", digital)

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
