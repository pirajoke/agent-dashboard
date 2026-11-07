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
import sys
sys.path.insert(0, str(BUILDER))
from dashboard_builder import weekly_reports as REPORTS  # noqa: E402
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
                          config_file=self.root / "telegram_digest.json", opener=self.opener,
                          inboxes=kwargs.pop("inboxes", []), **kwargs)

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


class WeeklyNotesTests(unittest.TestCase):
    setUp = RunTests.setUp
    opener = RunTests.opener

    NOTE = """---
project: HARDWARE
direction: AI-инфраструктура
week: 2026-11-04
---
# Итоги HARDWARE

## ✅ Сделано
- Mac mini на ИБП
- [x] Time Machine на Seagate 4 ТБ

## Ждёт тебя:
1. Выбрать модель ИБП

## Дальше
* Сетевой бэкап MacBook Pro

## Заметки
- это не попадает в сводку
"""

    def inbox(self):
        folder = self.root / "inbox"
        folder.mkdir(exist_ok=True)
        return folder

    def test_note_is_parsed_into_three_lists(self):
        note = REPORTS.parse_note(self.NOTE)
        self.assertEqual(note["meta"]["project"], "HARDWARE")
        self.assertEqual(note["done"], ["Mac mini на ИБП", "Time Machine на Seagate 4 ТБ"])
        self.assertEqual(note["waiting"], ["Выбрать модель ИБП"])
        self.assertEqual(note["next"], ["Сетевой бэкап MacBook Pro"])

    def test_week_comes_from_front_matter_then_file_name(self):
        inbox = self.inbox()
        (inbox / "hardware.md").write_text(self.NOTE)
        (inbox / "2026-11-08-jobradar.md").write_text("---\nproject: Job Radar\n---\n## Сделано\n- Релиз 1.2\n")
        (inbox / "2026-10-30-old.md").write_text("## Сделано\n- Прошлая неделя\n")
        (inbox / "2026-11-05-empty.md").write_text("Просто текст без списков\n")
        notes = REPORTS.collect_notes(date(2026, 11, 2), [inbox, self.root / "missing"])
        self.assertEqual(sorted(n["project"] for n in notes), ["HARDWARE", "Job Radar"])
        self.assertEqual(next(n for n in notes if n["project"] == "Job Radar")["direction"], "Job Radar")

    def test_directions_merge_projects_and_drop_duplicates(self):
        blocks = REPORTS.group_by_direction([
            {"project": "HARDWARE", "direction": "AI-инфраструктура", "done": ["ИБП"], "waiting": [], "next": []},
            {"project": "IT отдел", "direction": "ai-инфраструктура", "done": ["ибп", "Tailscale"], "waiting": ["Да/нет"], "next": []},
        ])
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]["projects"], ["HARDWARE", "IT отдел"])
        self.assertEqual(blocks[0]["done"], ["ИБП", "Tailscale"])

    def test_manual_build_mid_week_saves_but_does_not_mark_sent(self):
        inbox = self.inbox()
        (inbox / "hardware.md").write_text(self.NOTE)
        (self.root / "telegram_digest.json").write_text(json.dumps({"bot_token": TOKEN, "chat_id": "161537"}))
        saturday = datetime(2026, 11, 7, 12, tzinfo=timezone.utc)
        kwargs = dict(now=saturday, root=self.root / "dw", todo_file=self.root / "none.json", out=self.root / "out",
                      config_file=self.root / "telegram_digest.json", opener=self.opener, inboxes=[inbox], manual=True)
        result = DIGEST.run(**kwargs)
        self.assertEqual((result["week"], result["sent"], result["reason"], result["notes"]), ("2026-11-02", False, "built", 1))
        self.assertEqual(self.sent, [])
        saved = json.loads((self.root / "out" / "2026-11-02.json").read_text())
        self.assertEqual(saved["title"], "Итоги недели · 2 ноя – 6 ноя")
        self.assertEqual(saved["directions"][0]["name"], "AI-инфраструктура")
        text = (self.root / "out" / "2026-11-02.md").read_text()
        self.assertIn("По направлениям:\n▸ AI-инфраструктура (HARDWARE)\nСделано:\n• Mac mini на ИБП", text)
        self.assertIn("Ждёт тебя:\n• Выбрать модель ИБП", text)
        self.assertIn("Дальше:\n• Сетевой бэкап MacBook Pro", text)
        self.assertNotIn("не попадает", text)
        self.assertTrue(DIGEST.run(**kwargs, send_now=True)["sent"])
        status = json.loads((self.root / "out" / "status.json").read_text())
        self.assertNotIn("sent_week", status)
        self.assertEqual(status["last_manual"]["sent"], True)

    def test_history_is_newest_first_and_keeps_old_text_weeks(self):
        out = self.root / "out"
        out.mkdir()
        (out / "2026-10-19.md").write_text("Итоги недели · 19 окт – 25 окт\n\nСтарый текст\n")
        (out / "2026-10-26.json").write_text(json.dumps({"title": "Итоги недели · 26 окт – 1 ноя", "directions": [], "text": "x"}))
        (out / "2026-10-26.md").write_text("x\n")
        (out / "status.json").write_text("{}")
        weeks = REPORTS.history(out)
        self.assertEqual([w["week"] for w in weeks], ["2026-10-26", "2026-10-19"])
        self.assertEqual(weeks[1]["title"], "Итоги недели · 19 окт – 25 окт")
        self.assertEqual(REPORTS.history(self.root / "nowhere"), [])

    def test_long_text_is_split_for_telegram(self):
        parts = DIGEST.chunks("\n".join(f"• пункт {i} " + "x" * 90 for i in range(100)))
        self.assertGreater(len(parts), 1)
        self.assertTrue(all(len(part) <= DIGEST.TELEGRAM_LIMIT for part in parts))


class WeeklyEndpointTests(unittest.TestCase):
    """GET /api/weekly and POST /api/weekly/build on the Command Center server."""

    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("dashboard_weekly_test", BUILDER / "dashboard-server-m4.py")
        cls.SERVER = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.SERVER)

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.out = Path(temp.name)
        (self.out / "2026-10-26.md").write_text("Итоги недели · 26 окт – 1 ноя\n\nСекретная строка\n")

    def call(self, method, path, body=None, *, token="fixture-owner", origin=None, host="localhost:9999"):
        from unittest.mock import patch
        server = self.SERVER
        handler = server.Handler.__new__(server.Handler)
        handler.path, handler.command = path, method
        data = json.dumps(body or {}).encode()
        handler.headers = {"Host": host, "Content-Length": str(len(data)), "Content-Type": "application/json"}
        if token is not None:
            handler.headers["X-Dashboard-Run-Token"] = token
        if origin is not None:
            handler.headers["Origin"] = origin
        handler.rfile = io.BytesIO(data)
        output = {}
        handler._json_response = lambda status, payload: output.update(status=status, payload=payload)
        self.runs = []

        class Digest:
            @staticmethod
            def run(**kwargs):
                self.runs.append(kwargs)
                return {"week": "2026-11-02", "sent": kwargs["send_now"], "reason": "built", "notes": 1, "text": "x"}
        with (patch.object(server, "WEEKLY_DIGEST_DIR", self.out),
              patch.object(server, "_weekly_digest_module", return_value=Digest),
              patch.object(server, "_dashboard_run_token", return_value="fixture-owner"),
              patch.object(server.Handler, "_cloudflare_access_owner", return_value=False)):
            getattr(handler, f"do_{method}")()
        return output

    def test_owner_reads_the_weeks_others_only_a_count(self):
        owner = self.call("GET", "/api/weekly")
        self.assertEqual(owner["payload"]["weeks"][0]["week"], "2026-10-26")
        for host in ("localhost:9999", "command.meshly.fr"):
            public = self.call("GET", "/api/weekly", token=None, host=host)
            self.assertEqual(public["payload"], {"ok": True, "owner_view": False, "count": 1})
            self.assertNotIn("Секретная", json.dumps(public, ensure_ascii=False))

    def test_build_is_owner_only_and_sends_only_when_asked(self):
        built = self.call("POST", "/api/weekly/build", {}, origin="http://localhost:9999")
        self.assertEqual((built["status"], built["payload"]["build"]["sent"]), (200, False))
        self.assertEqual(self.runs[0], {"manual": True, "send_now": False})
        self.call("POST", "/api/weekly/build", {"send": True})
        self.assertEqual(self.runs[0]["send_now"], True)
        self.assertEqual(self.call("POST", "/api/weekly/build", {}, token=None)["status"], 401)
        self.assertEqual(self.runs, [])
        self.assertEqual(self.call("POST", "/api/weekly/build", {}, origin="https://evil.example")["status"], 403)


class InstallTests(unittest.TestCase):
    def test_plist_runs_on_monday_morning_and_deploy_installs_it(self):
        plist = plistlib.loads((BUILDER / "launchd" / "com.pirajoke.weekly-digest.plist.template").read_bytes())
        self.assertEqual(plist["StartCalendarInterval"], {"Weekday": 1, "Hour": 9, "Minute": 0})
        deploy = (BUILDER / "deploy_to_scripts.sh").read_text()
        self.assertIn('cp "$SRC_DIR/weekly_digest.py"', deploy)
        self.assertIn("com.pirajoke.weekly-digest", deploy)


if __name__ == "__main__":
    unittest.main()
