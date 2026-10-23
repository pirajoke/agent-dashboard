"""Evening summary of the day in Telegram (Mark 2026-10-23)."""
from __future__ import annotations

import importlib.util
import io
import json
import plistlib
import subprocess
import sys
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

BUILDER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BUILDER))
spec = importlib.util.spec_from_file_location("daily_digest_test", BUILDER / "daily_digest.py")
DIGEST = importlib.util.module_from_spec(spec)
spec.loader.exec_module(DIGEST)
TOKEN = "123456789:" + "A" * 35
TODAY = date(2026, 10, 23)


def project(pid, name, minutes, merged=(), quiet=False, bullets=None):
    return {"id": pid, "name": name, "minutes": minutes, "quiet": quiet, "bullets": bullets or [],
            "merged": [{"number": n, "title": t} for n, t in merged]}


def summary(details, day="Сайт научился сам присылать итоги"):
    return {"date": "2026-10-23", "day": day, "projects": {k: v.get("agents", []) for k, v in details.items()},
            "details": details}


class ComposeTests(unittest.TestCase):
    def test_date_numbers_and_projects_with_claude_words(self):
        entry = {"total_minutes": 390, "claude_minutes": 300, "codex_minutes": 90, "prs_merged": 3, "projects": [
            project("p-tmp", "tmp", 20),
            project("command-center", "Command Center", 240, merged=[(117, "Title"), (118, "Agents")]),
            project("mydictionary", "Lexi", 60, merged=[(9, "Fix <b> & stuff")]),
            project("health", "Health OS", 2, quiet=True)]}
        text = "\n".join(DIGEST.compose(entry, summary({"command-center": {
            "lead": "Агенты берут задачи сами", "agents": ["Появилась кнопка «Агенту»"], "you": ["Проверил вкладку"],
            "next": ["Добавить задачу"], "deadlines": [{"date": "2026-10-31", "what": "Accountable OS MVP"}]}}),
            [{"text": "Поставить ИБП"}, {"text": "Готово", "done": True}], TODAY))
        self.assertTrue(text.startswith("📅 <b>Резюме дня · 23 октября 2026, пятница</b>"))
        self.assertIn("⏱ Работа: <b>6,5 ч</b> (Claude Code 5 ч · Codex 1,5 ч)", text)
        self.assertIn("✅ Слито PR: <b>3</b> · 📂 Проектов: <b>3</b>", text)
        self.assertIn("💬 Сайт научился сам присылать итоги", text)
        self.assertIn("🧭 <b>Command Center</b> · 4 ч · ✅ PR: 2\n<i>Агенты берут задачи сами</i>", text)
        self.assertIn("🤖 Сделали агенты:\n• Появилась кнопка «Агенту»\n🙋 Ты:\n• Проверил вкладку", text)
        self.assertIn("👉 Дальше: Добавить задачу\n⏰ 31 окт: Accountable OS MVP", text)
        # Not retold yet: the merged PR titles, escaped for Telegram HTML.
        self.assertIn("📚 <b>Lexi</b> · 1 ч · ✅ PR: 1\n• Fix &lt;b&gt; &amp; stuff (#9)", text)
        # Main products before other folders; quick looks only named.
        self.assertLess(text.index("Lexi"), text.index("📁 <b>tmp</b>"))
        self.assertIn("👀 Заглядывали: Health OS", text)
        self.assertIn("📌 <b>Ждёт тебя (1)</b>\n• Поставить ИБП", text)
        self.assertNotIn("Готово", text)
        self.assertTrue(text.endswith(DIGEST.SITE))

    def test_an_empty_day_says_so(self):
        text = "\n".join(DIGEST.compose(None, None, [], TODAY))
        self.assertIn("Сегодня работы агентов в данных нет.", text)
        self.assertNotIn("0 мин", text)

    def test_long_days_are_split_for_telegram(self):
        long = ["x" * 200] * 4
        entry = {"total_minutes": 60, "prs_merged": 0,
                 "projects": [project(f"p-{n}", f"P{n}", 10 + n) for n in range(8)]}
        details = {f"p-{n}": {"agents": long, "you": long, "next": long} for n in range(8)}
        parts = DIGEST.compose(entry, summary(details, day=""), [], TODAY)
        self.assertGreater(len(parts), 1)
        self.assertTrue(all(len(part) <= 4096 for part in parts))


class RunTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.sent, self.ran = [], []

    def opener(self, request, timeout=None):
        self.sent.append(json.loads(request.data))
        return io.BytesIO(json.dumps({"ok": True}).encode())

    def runner(self, command, **kwargs):
        self.ran.append(command)
        return subprocess.CompletedProcess(command, 0)

    def run_digest(self, **kwargs):
        return DIGEST.run(now=datetime(2026, 10, 23, 19, 30, tzinfo=timezone.utc), root=self.root / "daily-work",
                          todo_file=self.root / "owner-todo.json", out=self.root / "out",
                          config_file=self.root / "telegram_digest.json", opener=self.opener, runner=self.runner, **kwargs)

    def test_without_config_it_saves_the_text_and_sends_nothing(self):
        result = self.run_digest()
        self.assertEqual((result["sent"], result["reason"]), (False, "telegram_not_configured"))
        day = result["day"]
        self.assertTrue((self.root / "out" / f"{day}.md").read_text().startswith("📅 <b>Резюме дня"))
        self.assertEqual(self.sent, [])

    def test_refreshes_the_day_then_sends_once_unless_forced(self):
        (self.root / "telegram_digest.json").write_text(json.dumps({"bot_token": TOKEN, "chat_id": "161537"}))
        self.assertTrue(self.run_digest()["sent"])
        self.assertEqual(self.sent[0]["parse_mode"], "HTML")
        self.assertEqual(self.sent[0]["chat_id"], "161537")
        collector, summarizer = self.ran
        self.assertEqual(collector[-3:], ["--machine", "mac-mini", "--github"])
        self.assertEqual(summarizer[-2], "--day")
        self.assertEqual(self.run_digest()["reason"], "already_sent")
        self.assertEqual(len(self.ran), 2)  # no refresh for a day already sent
        self.assertTrue(self.run_digest(force=True)["sent"])
        self.assertEqual(len(self.sent), 2)

    def test_a_failed_refresh_still_sends(self):
        (self.root / "telegram_digest.json").write_text(json.dumps({"bot_token": TOKEN, "chat_id": "161537"}))

        def broken(command, **kwargs):
            raise subprocess.TimeoutExpired(command, 1)
        result = DIGEST.run(now=datetime(2026, 10, 23, 19, 30, tzinfo=timezone.utc), root=self.root / "dw",
                            todo_file=self.root / "none.json", out=self.root / "out",
                            config_file=self.root / "telegram_digest.json", opener=self.opener, runner=broken)
        self.assertTrue(result["sent"])
        self.assertEqual(result["refresh_problems"], ["collector_TimeoutExpired", "summarizer_TimeoutExpired"])

    def test_a_refusal_never_leaks_the_token(self):
        (self.root / "telegram_digest.json").write_text(json.dumps({"bot_token": TOKEN, "chat_id": "161537"}))

        def failing(request, timeout=None):
            raise OSError(f"cannot reach {request.full_url}")
        result = DIGEST.run(now=datetime(2026, 10, 23, 19, 30, tzinfo=timezone.utc), root=self.root / "dw",
                            todo_file=self.root / "none.json", out=self.root / "out",
                            config_file=self.root / "telegram_digest.json", opener=failing, runner=self.runner)
        self.assertFalse(result["sent"])
        self.assertNotIn(TOKEN, json.dumps(result))
        self.assertNotIn(TOKEN, (self.root / "out" / "status.json").read_text())

    def test_reads_todays_feed_and_summary(self):
        with patch.object(DIGEST, "work_projection", return_value={"feed": []}) as projection:
            self.run_digest(dry_run=True)
        kwargs = projection.call_args.kwargs
        self.assertEqual((kwargs["owner"], kwargs["edition"]), (True, True))
        self.assertEqual(self.ran, [])  # a dry run changes nothing


class InstallTests(unittest.TestCase):
    def test_plist_runs_every_evening_before_22_and_deploy_installs_it(self):
        plist = plistlib.loads((BUILDER / "launchd" / "com.pirajoke.daily-digest.plist.template").read_bytes())
        self.assertEqual(plist["StartCalendarInterval"], {"Hour": 21, "Minute": 30})
        self.assertIn("/opt/homebrew/bin", plist["EnvironmentVariables"]["PATH"])
        deploy = (BUILDER / "deploy_to_scripts.sh").read_text()
        self.assertIn('cp "$SRC_DIR/daily_digest.py"', deploy)
        self.assertIn("com.pirajoke.daily-digest", deploy)


if __name__ == "__main__":
    unittest.main()
