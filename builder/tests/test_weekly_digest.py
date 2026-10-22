"""Monday digest in Telegram (Mark 2026-10-22)."""
from __future__ import annotations

import importlib.util
import io
import json
from datetime import date, datetime, timezone
from pathlib import Path
import plistlib
import tempfile
import unittest

BUILDER = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("weekly_digest_test", BUILDER / "weekly_digest.py")
DIGEST = importlib.util.module_from_spec(spec)
spec.loader.exec_module(DIGEST)
TOKEN = "123456789:" + "A" * 35


def project(name, claude, codex, merged=0, main=True, bullet=None, day="2026-10-20"):
    pad = [0] * 7
    return {"id": name.lower(), "name": name, "main": main,
            "daily_claude_minutes": pad + [claude, 0, 0, 0, 0, 0, 0, 999],
            "daily_codex_minutes": pad + [codex, 0, 0, 0, 0, 0, 0, 999],
            "daily_prs_merged": pad + [merged, 0, 0, 0, 0, 0, 0, 5],
            "last_summary": {"date": day, "bullets": [bullet]} if bullet else None}


class ComposeTests(unittest.TestCase):
    def test_numbers_projects_and_waiting(self):
        projection = {"traction": {"last_7": {"total_minutes": 600, "claude_minutes": 420, "codex_minutes": 180, "prs_merged": 7},
                                   "previous_7": {"total_minutes": 300}},
                      "projects": [project("Lexi", 0, 60), project("Command Center", 300, 120, 4, bullet="Сайт сам предлагает обновиться"),
                                   project("tmp-folder", 30, 0, main=False), project("Idle", 0, 0)]}
        text = DIGEST.compose(projection, [{"text": "Поставить ИБП"}], date(2026, 10, 26))
        self.assertTrue(text.startswith("Итоги недели · 19 окт – 25 окт"))
        self.assertIn("Работа агентов: 10 ч (неделей раньше 5 ч)", text)
        self.assertIn("Claude Code 7 ч · Codex 3 ч", text)
        self.assertIn("Слито PR: 7", text)
        lines = text.splitlines()
        moved = lines[lines.index("Что сдвинулось:") + 1:]
        self.assertEqual(moved[0], "• Command Center — 7 ч (Claude Code 5 ч / Codex 2 ч), PR: 4")
        self.assertEqual(moved[1], "  Сайт сам предлагает обновиться")
        self.assertEqual(moved[2], "• Lexi — 1 ч (Codex 1 ч)")
        self.assertEqual(moved[3], "• tmp-folder — 30 мин (Claude Code 30 мин)")
        self.assertNotIn("Idle", text)
        today_summary = DIGEST.compose({"traction": {}, "projects": [project("Lexi", 60, 0, bullet="Сегодняшняя строка", day="2026-10-26")]},
                                       [], date(2026, 10, 26))
        self.assertNotIn("Сегодняшняя строка", today_summary)
        self.assertIn("Ждёт тебя (1):\n• Поставить ИБП", text)
        self.assertNotIn("999", text)  # today's unfinished day is not counted

    def test_an_empty_week_says_so(self):
        text = DIGEST.compose({"traction": {}, "projects": []}, [], date(2026, 10, 26))
        self.assertIn("За неделю работы агентов в данных нет.", text)
        self.assertNotIn("0 мин", text)


class RunTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.sent = []

    def opener(self, request, timeout=None):
        self.sent.append((request.full_url, json.loads(request.data)))
        return io.BytesIO(json.dumps({"ok": True}).encode())

    def run_digest(self, **kwargs):
        return DIGEST.run(now=datetime(2026, 10, 26, 7, tzinfo=timezone.utc), root=self.root / "daily-work",
                          todo_file=self.root / "owner-todo.json", out=self.root / "out",
                          config_file=self.root / "telegram_digest.json", opener=self.opener, **kwargs)

    def test_two_complete_weeks_are_compared(self):
        from unittest.mock import patch
        with patch.object(DIGEST, "work_projection", return_value={"traction": {}, "projects": []}) as projection:
            self.run_digest(dry_run=True)
        self.assertEqual(projection.call_args.kwargs["days"], 15)

    def test_without_config_it_saves_the_text_and_sends_nothing(self):
        result = self.run_digest()
        self.assertEqual((result["sent"], result["reason"]), (False, "telegram_not_configured"))
        self.assertTrue((self.root / "out" / "2026-10-19.md").read_text().startswith("Итоги недели"))
        self.assertEqual(self.sent, [])

    def test_sends_once_a_week_unless_forced(self):
        (self.root / "telegram_digest.json").write_text(json.dumps({"bot_token": TOKEN, "chat_id": "161537"}))
        (self.root / "owner-todo.json").write_text(json.dumps({"items": [{"text": "Решить по #61"}, {"text": "Сделано", "done": True}]}))
        self.assertTrue(self.run_digest()["sent"])
        url, body = self.sent[0]
        self.assertEqual(url, f"https://api.telegram.org/bot{TOKEN}/sendMessage")
        self.assertEqual(body["chat_id"], "161537")
        self.assertIn("• Решить по #61", body["text"])
        self.assertNotIn("Сделано", body["text"])
        self.assertEqual(self.run_digest()["reason"], "already_sent")
        self.assertTrue(self.run_digest(force=True)["sent"])
        self.assertEqual(len(self.sent), 2)

    def test_a_refusal_never_leaks_the_token(self):
        (self.root / "telegram_digest.json").write_text(json.dumps({"bot_token": TOKEN, "chat_id": "161537"}))

        def failing(request, timeout=None):
            raise OSError(f"cannot reach {request.full_url}")
        result = DIGEST.run(now=datetime(2026, 10, 26, 7, tzinfo=timezone.utc), root=self.root / "dw",
                            todo_file=self.root / "none.json", out=self.root / "out",
                            config_file=self.root / "telegram_digest.json", opener=failing)
        self.assertFalse(result["sent"])
        self.assertNotIn(TOKEN, json.dumps(result))
        self.assertNotIn(TOKEN, (self.root / "out" / "status.json").read_text())

    def test_bad_config_is_not_used(self):
        for config in ({"bot_token": "nope", "chat_id": "1"}, {"bot_token": TOKEN, "chat_id": "x;rm"}, []):
            (self.root / "telegram_digest.json").write_text(json.dumps(config))
            self.assertIsNone(DIGEST.load_config(self.root / "telegram_digest.json"))


class InstallTests(unittest.TestCase):
    def test_plist_runs_on_monday_morning_and_deploy_installs_it(self):
        plist = plistlib.loads((BUILDER / "launchd" / "com.pirajoke.weekly-digest.plist.template").read_bytes())
        self.assertEqual(plist["StartCalendarInterval"], {"Weekday": 1, "Hour": 9, "Minute": 0})
        deploy = (BUILDER / "deploy_to_scripts.sh").read_text()
        self.assertIn('cp "$SRC_DIR/weekly_digest.py"', deploy)
        self.assertIn("com.pirajoke.weekly-digest", deploy)


if __name__ == "__main__":
    unittest.main()
