from __future__ import annotations

from datetime import datetime, timedelta, timezone
import importlib.util
import json
import os
import shutil
import subprocess
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch


BUILDER_DIR = Path(__file__).resolve().parents[1]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


COLLECTOR = _load("daily_work_collector", BUILDER_DIR / "daily_work_collector.py")
from dashboard_builder.daily_work import work_projection  # noqa: E402


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8")


class CollectorParsingTest(unittest.TestCase):
    def test_active_intervals_drop_breaks_over_thirty_minutes(self):
        start = datetime(2026, 10, 8, 9, 0, tzinfo=timezone.utc)
        times = [start, start + timedelta(minutes=10), start + timedelta(minutes=25),
                 start + timedelta(hours=2), start + timedelta(hours=2, minutes=5)]
        intervals = COLLECTOR.active_intervals(times)
        self.assertEqual(len(intervals), 2)
        self.assertEqual(COLLECTOR.interval_minutes(intervals), 26 + 6)

    def test_session_crossing_midnight_stays_continuous(self):
        os.environ["TZ"] = "UTC"
        time.tzset()
        session = COLLECTOR.Session("claude", "night")
        session.events = [datetime(2026, 10, 7, 23, 50, tzinfo=timezone.utc), datetime(2026, 10, 8, 0, 10, tzinfo=timezone.utc)]
        days = COLLECTOR.day_records([session], {"2026-10-07", "2026-10-08"})
        self.assertEqual(days["2026-10-07"][0]["active_minutes"], 10)
        self.assertEqual(days["2026-10-08"][0]["active_minutes"], 11)

    def test_topic_is_redacted_and_shortened(self):
        topic = COLLECTOR.redact_topic("deploy with token=ghp_abcdefghijklmnopqrstuvwxyz0123 please " + "x " * 100)
        self.assertNotIn("ghp_", topic)
        self.assertIn("[скрыто]", topic)
        self.assertLessEqual(len(topic), COLLECTOR.TOPIC_LIMIT)
        self.assertIsNone(COLLECTOR.redact_topic("<command-name>/clear</command-name>"))

    def test_claude_and_codex_logs_become_day_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            t0 = datetime(2026, 10, 8, 10, 0, tzinfo=timezone.utc)
            _write_jsonl(home / "claude" / "-Users-mark-Projects-jarvis" / "s1.jsonl", [
                {"type": "user", "sessionId": "s1", "timestamp": _iso(t0), "cwd": "/nonexistent/jarvis",
                 "gitBranch": "feat/x", "message": {"role": "user", "content": "Почини деплой бота"}},
                {"type": "assistant", "sessionId": "s1", "timestamp": _iso(t0 + timedelta(minutes=20)),
                 "message": {"role": "assistant", "content": [{"type": "text", "text": "ok"}]}},
                {"type": "user", "sessionId": "s1", "timestamp": _iso(t0 + timedelta(minutes=21)),
                 "message": {"role": "user", "content": [{"type": "tool_result", "content": "secret output"}]}},
            ])
            _write_jsonl(home / "codex" / "2026" / "10" / "08" / "rollout-1.jsonl", [
                {"timestamp": _iso(t0), "type": "session_meta", "payload": {
                    "id": "c1", "cwd": "/nonexistent/lexi",
                    "git": {"branch": "codex/fix", "repository_url": "git@github.com:pirajoke/lexi.git"}}},
                {"timestamp": _iso(t0 + timedelta(minutes=1)), "type": "response_item", "payload": {
                    "type": "message", "role": "user", "content": [{"type": "input_text", "text": "<environment_context>"}]}},
                {"timestamp": _iso(t0 + timedelta(minutes=1)), "type": "event_msg", "payload": {
                    "type": "user_message", "message": "Add price review"}},
                {"timestamp": _iso(t0 + timedelta(minutes=9)), "type": "event_msg", "payload": {"type": "agent_message", "message": "done"}},
            ])
            claude = COLLECTOR.parse_claude_file(home / "claude" / "-Users-mark-Projects-jarvis" / "s1.jsonl")
            codex = COLLECTOR.parse_codex_file(home / "codex" / "2026" / "10" / "08" / "rollout-1.jsonl")
        self.assertEqual(claude[0].topic, "Почини деплой бота")
        self.assertEqual(len(claude[0].prompts), 1)
        self.assertEqual(claude[0].branch, "feat/x")
        self.assertEqual(codex[0].repo, "pirajoke/lexi")
        self.assertEqual(codex[0].topic, "Add price review")
        self.assertEqual(len(codex[0].prompts), 1)
        with patch.object(COLLECTOR, "local_day", lambda moment: moment.date().isoformat()):
            days = COLLECTOR.day_records(claude + codex, {"2026-10-08"})
        records = days["2026-10-08"]
        self.assertEqual({r["tool"] for r in records}, {"claude", "codex"})
        self.assertNotIn("secret output", json.dumps(records, ensure_ascii=False))
        lexi = next(r for r in records if r["tool"] == "codex")
        self.assertEqual(lexi["project"], "lexi")
        self.assertEqual(lexi["active_minutes"], 10)

    def test_newer_codex_rollouts_keep_asks_replies_and_the_repo(self):
        os.environ["TZ"] = "UTC"
        time.tzset()
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            clone = home / "clones" / "agent-dashboard"
            (clone / ".git").mkdir(parents=True)
            t0 = datetime(2026, 10, 12, 10, 0, tzinfo=timezone.utc)
            path = home / "rollout-new.jsonl"
            _write_jsonl(path, [
                # The working folder is a file:// URI to a worktree that is gone by now.
                {"timestamp": _iso(t0), "type": "session_meta", "payload": {
                    "id": "n1", "cwd": "file:///nonexistent/tmp/agent-dashboard-unified-tabs-v1",
                    "agent_path": "/root/dashboard_pr_gate"}},
                {"timestamp": _iso(t0), "type": "response_item", "payload": {
                    "type": "message", "role": "user", "content": [{"type": "input_text", "text": "# AGENTS.md instructions"}]}},
                {"timestamp": _iso(t0 + timedelta(minutes=1)), "type": "response_item", "payload": {
                    "type": "message", "role": "user", "content": [{"type": "input_text", "text": "Объедини вкладки"}]}},
                {"timestamp": _iso(t0 + timedelta(minutes=5)), "type": "response_item", "payload": {
                    "type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "Смотрю код"}]}},
                {"timestamp": _iso(t0 + timedelta(minutes=9)), "type": "event_msg", "payload": {
                    "type": "task_complete", "last_agent_message": "Вкладки объединены, тесты зелёные"}},
            ])
            with patch.object(COLLECTOR, "CLONE_PARENTS", [home / "clones"]), \
                    patch.object(COLLECTOR, "_git_remote",
                                 lambda cwd: "pirajoke/agent-dashboard" if cwd == str(clone) else None), \
                    patch.dict(COLLECTOR._REMOTE_CACHE, clear=True):
                sessions = COLLECTOR.parse_codex_file(path)
        session = sessions[0]
        self.assertEqual(session.cwd, "/nonexistent/tmp/agent-dashboard-unified-tabs-v1")
        self.assertEqual(session.repo, "pirajoke/agent-dashboard")
        self.assertEqual(session.topic, "Объедини вкладки")
        record = COLLECTOR.day_records(sessions, {"2026-10-12"})["2026-10-12"][0]
        self.assertEqual(record["project"], "agent-dashboard")
        self.assertEqual(record["asks"], ["Объедини вкладки"])
        self.assertEqual(record["outcome"], "Вкладки объединены, тесты зелёные")

    def test_chatgpt_export_is_read_once_per_export(self):
        os.environ["TZ"] = "UTC"
        time.tzset()
        now = datetime.now(timezone.utc).replace(microsecond=0)
        t0 = (now - timedelta(days=1)).replace(hour=10, minute=0, second=0)

        def node(role, minutes, text, parent=None, **meta):
            return {"parent": parent, "message": {
                "author": {"role": role}, "create_time": (t0 + timedelta(minutes=minutes)).timestamp(),
                "content": {"content_type": "text", "parts": [text]}, "metadata": meta}}

        shop = {"id": "c1", "title": "Запуск магазина", "update_time": (t0 + timedelta(minutes=20)).timestamp(),
                "conversation_template_id": "g-p-abc123def456", "current_node": "g", "mapping": {
                    "a": {"message": None, "parent": None}, "b": node("system", 0, "system prompt", "a"),
                    "c": node("user", 1, "Составь план запуска магазина", "b"),
                    "d": node("assistant", 4, "План из пяти шагов готов", "c"),
                    "e": node("user", 9, "скрытое", "d", is_visually_hidden_from_conversation=True),
                    "f": node("user", 15, "Добавь бюджет на рекламу", "e"),
                    "g": node("assistant", 20, "Бюджет добавлен: 300 евро", "f"),
                    # An edited prompt: the old branch stays in the export but is not the conversation.
                    "x": node("user", 14, "Старый вариант вопроса", "e"), "y": node("assistant", 16, "Старый ответ", "x")}}
        post = {"id": "c2", "title": "Пост для LinkedIn", "update_time": (t0 - timedelta(days=1, minutes=-50)).timestamp(),
                "mapping": {"a": node("user", 40 - 1440, "Напиши пост про запуск"), "b": node("assistant", 50 - 1440, "Пост готов")}}
        old = {"id": "old", "title": "Старое", "update_time": (now - timedelta(days=200)).timestamp(), "mapping": {
            "a": {"message": {"author": {"role": "user"}, "create_time": (now - timedelta(days=200)).timestamp(),
                              "content": {"parts": ["давно"]}}}}}
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            exports = home / "ChatGPT-export"
            exports.mkdir()
            import zipfile

            def export(name, conversations):
                with zipfile.ZipFile(exports / name, "w") as archive:
                    archive.writestr("conversations.json", json.dumps(conversations, ensure_ascii=False))
                    archive.writestr("user.json", "{}")
                os.utime(exports / name, (time.time() + len(name), time.time() + len(name)))

            export("chatgpt-export.zip", [shop, post, old])
            out = home / "daily-work"
            out.mkdir()
            since = now - timedelta(days=45)
            first = COLLECTOR.import_chatgpt_export(out, since, [exports, home / "missing"])
            again = COLLECTOR.import_chatgpt_export(out, since, [exports])
            day, post_day = t0.date().isoformat(), (t0 - timedelta(days=1)).date().isoformat()
            data = json.loads((out / "sessions" / "chatgpt" / f"{day}.json").read_text(encoding="utf-8"))
            projection = work_projection(out, now=now, owner=True)
            # Naming the project later rewrites the days with the name.
            (out / "chatgpt_projects.json").write_text(json.dumps({"g-p-abc123def456": "SHOPIFY"}), encoding="utf-8")
            renamed = COLLECTOR.import_chatgpt_export(out, since, [exports])
            named = json.loads((out / "sessions" / "chatgpt" / f"{day}.json").read_text(encoding="utf-8"))
            # A newer export without the LinkedIn chat empties its day.
            export("chatgpt-export-newer.zip", [shop])
            newer = COLLECTOR.import_chatgpt_export(out, since, [exports])
            emptied = json.loads((out / "sessions" / "chatgpt" / f"{post_day}.json").read_text(encoding="utf-8"))
        self.assertEqual((first["fresh"], first["conversations"], again["fresh"], again["needs_push"]), (True, 2, False, True))
        record = data["sessions"][0]
        self.assertEqual((record["project"], record["app"], record["tool"], record["topic"]),
                         ("ChatGPT · проект def456", "chatgpt", "codex", "Запуск магазина"))
        self.assertEqual(record["asks"], ["Составь план запуска магазина", "Добавь бюджет на рекламу"])  # no hidden, no old branch
        self.assertEqual((record["outcome"], record["active_minutes"]), ("Бюджет добавлен: 300 евро", 20))
        self.assertEqual(data["machine"], "chatgpt")
        self.assertTrue({"ChatGPT · проект def456", "ChatGPT · без проекта"} <= {item["name"] for item in projection["projects"]})
        # A folder that is not a Platforms product is secondary on the board.
        self.assertFalse(any(item["main"] for item in projection["projects"] if item["name"].startswith("ChatGPT")))
        self.assertEqual((renamed["fresh"], named["sessions"][0]["project"]), (True, "ChatGPT · SHOPIFY"))
        self.assertEqual((newer["days"], emptied["sessions"]), (sorted([day, post_day]), []))

    def test_no_chatgpt_export_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = COLLECTOR.import_chatgpt_export(Path(tmp), datetime.now(timezone.utc), [Path(tmp) / "none"])
        self.assertEqual(result, {"ok": False, "reason": "export_not_found"})

    def test_chatgpt_app_projects_are_labelled(self):
        name = COLLECTOR.project_name
        self.assertEqual(name("/Users/mark/Documents/ChatGPT/SHOPIFY", None), "ChatGPT · SHOPIFY")
        self.assertEqual(name("/Users/mark/Documents/ChatGPT/LYBOV LINKEDIN/notes", None), "ChatGPT · LYBOV LINKEDIN")
        # A chat outside a project gets a folder named by its id or «new-chat»: grouped, not listed one by one.
        for folder in ("39f9f538-1c2d-4e5f-8a9b-0c1d2e3f4a5b", "new-chat", "New Chat 2", ""):
            self.assertEqual(name(f"/Users/mark/Documents/ChatGPT/{folder}".rstrip("/"), None), "ChatGPT · без проекта")
        self.assertEqual(name("/Users/mark/Documents/ChatGPT/SHOPIFY", "pirajoke/shop"), "shop")  # a repo wins
        self.assertEqual(name("/Users/mark/Projects/ChatGPT", None), "ChatGPT")  # not the app's folder

    def test_existing_folder_outside_git_is_not_matched_to_a_clone(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            clone = home / "clones" / "agent-dashboard"
            (clone / ".git").mkdir(parents=True)
            notes = home / "agent-dashboard-notes"
            notes.mkdir()
            with patch.object(COLLECTOR, "CLONE_PARENTS", [home / "clones"]), \
                    patch.object(COLLECTOR, "_git_remote",
                                 lambda cwd: "pirajoke/agent-dashboard" if cwd == str(clone) else None), \
                    patch.dict(COLLECTOR._REMOTE_CACHE, clear=True):
                self.assertIsNone(COLLECTOR.repo_for_cwd(str(notes)))
                self.assertEqual(COLLECTOR.repo_for_cwd(str(home / "agent-dashboard-gone-v1")), "pirajoke/agent-dashboard")

    def test_codex_sub_agent_without_asks_is_named_by_its_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rollout-sub.jsonl"
            t0 = datetime(2026, 10, 12, 10, 0, tzinfo=timezone.utc)
            _write_jsonl(path, [
                {"timestamp": _iso(t0), "type": "session_meta", "payload": {
                    "id": "s1", "cwd": "/nonexistent/x", "agent_path": "/root/health_proxy_final_review"}},
                {"timestamp": _iso(t0 + timedelta(minutes=2)), "type": "event_msg", "payload": {"type": "task_started"}},
            ])
            with patch.dict(COLLECTOR._REMOTE_CACHE, clear=True):
                session = COLLECTOR.parse_codex_file(path)[0]
        self.assertEqual(session.topic, "health proxy final review")
        self.assertEqual(session.asks, [])

    def test_ssh_host_alias_remotes_resolve(self):
        self.assertEqual(COLLECTOR.repo_from_remote("git@github.com-agent-dashboard:pirajoke/agent-dashboard.git"),
                         "pirajoke/agent-dashboard")
        self.assertEqual(COLLECTOR.normalize_cwd("file:///Users/me/MAIN%20MANAGER"), "/Users/me/MAIN MANAGER")


    def test_day_records_keep_asks_and_last_reply_for_the_summary(self):
        os.environ["TZ"] = "UTC"
        time.tzset()
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            t0 = datetime(2026, 10, 8, 10, 0, tzinfo=timezone.utc)
            _write_jsonl(home / "claude" / "p" / "s1.jsonl", [
                {"type": "user", "sessionId": "s1", "timestamp": _iso(t0), "cwd": "/nonexistent/jarvis",
                 "message": {"role": "user", "content": "Почини деплой бота, token=ghp_abcdefghijklmnopqrstuvwxyz0123"}},
                {"type": "assistant", "sessionId": "s1", "timestamp": _iso(t0 + timedelta(minutes=5)),
                 "message": {"role": "assistant", "content": [{"type": "text", "text": "Смотрю логи"}]}},
                {"type": "user", "sessionId": "s1", "timestamp": _iso(t0 + timedelta(minutes=6)),
                 "message": {"role": "user", "content": "Почини деплой бота, token=ghp_abcdefghijklmnopqrstuvwxyz0123"}},
                {"type": "user", "sessionId": "s1", "timestamp": _iso(t0 + timedelta(minutes=7)),
                 "message": {"role": "user", "content": "И добавь проверку"}},
                {"type": "assistant", "sessionId": "s1", "timestamp": _iso(t0 + timedelta(minutes=20)),
                 "message": {"role": "assistant", "content": [{"type": "text", "text": "Готово: бот снова отвечает."},
                                                               {"type": "tool_use", "name": "Bash", "input": {"command": "ls"}}]}},
                {"type": "assistant", "sessionId": "s1", "timestamp": _iso(t0 + timedelta(minutes=21)),
                 "message": {"role": "assistant", "content": [{"type": "tool_use", "name": "Bash", "input": {"command": "pwd"}}]}},
            ])
            _write_jsonl(home / "codex" / "rollout-1.jsonl", [
                {"timestamp": _iso(t0), "type": "session_meta", "payload": {"id": "c1", "cwd": "/nonexistent/lexi"}},
                {"timestamp": _iso(t0 + timedelta(minutes=1)), "type": "event_msg", "payload": {
                    "type": "user_message", "message": "Add price review"}},
                {"timestamp": _iso(t0 + timedelta(minutes=8)), "type": "event_msg", "payload": {"type": "agent_message", "message": "Draft ready"}},
                {"timestamp": _iso(t0 + timedelta(minutes=9)), "type": "event_msg", "payload": {"type": "agent_message", "message": "Price review added"}},
            ])
            sessions = (COLLECTOR.parse_claude_file(home / "claude" / "p" / "s1.jsonl")
                        + COLLECTOR.parse_codex_file(home / "codex" / "rollout-1.jsonl"))
        records = {r["tool"]: r for r in COLLECTOR.day_records(sessions, {"2026-10-08"})["2026-10-08"]}
        claude = records["claude"]
        self.assertEqual(len(claude["asks"]), 2)  # the repeated ask counts once
        self.assertIn("[скрыто]", claude["asks"][0])
        self.assertNotIn("ghp_", json.dumps(claude, ensure_ascii=False))
        self.assertEqual(claude["outcome"], "Готово: бот снова отвечает.")  # tool-only turns don't replace it
        self.assertEqual(records["codex"]["asks"], ["Add price review"])
        self.assertEqual(records["codex"]["outcome"], "Price review added")

    def test_many_asks_keep_the_first_and_last_ones(self):
        moment = datetime(2026, 10, 8, 10, 0, tzinfo=timezone.utc)
        asks = [(moment + timedelta(minutes=i), f"ask {i}") for i in range(12)]
        with patch.object(COLLECTOR, "local_day", lambda m: m.date().isoformat()):
            kept = COLLECTOR._day_asks(asks, "2026-10-08")
        self.assertEqual(kept, ["ask 0", "ask 1", "ask 2", "ask 3", "ask 4", "ask 9", "ask 10", "ask 11"])

    def test_summarizer_sessions_are_not_counted_as_work(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            now = datetime.now(timezone.utc)
            out = (home / "custom-out").resolve()
            for name, cwd in (("mine", "/nonexistent/jarvis"), ("robot", str(out / "summarizer"))):
                _write_jsonl(home / "claude" / "p" / f"{name}.jsonl", [
                    {"type": "user", "sessionId": name, "timestamp": _iso(now), "cwd": cwd,
                     "message": {"role": "user", "content": "Сделай итог дня"}}])
            with patch.object(COLLECTOR, "CLAUDE_DIRS", [home / "claude"]), patch.object(COLLECTOR, "CODEX_DIRS", []):
                sessions, _ = COLLECTOR.collect_sessions(now - timedelta(days=1), out)
        self.assertEqual([s.session_id for s in sessions], ["mine"])

    def test_pr_body_is_redacted_and_shortened(self):
        item = COLLECTOR._pr_item({"number": 5, "title": "Fix", "repository_url": "https://api.github.com/repos/pirajoke/x",
                                   "body": "Uses sk-proj-abcdefghijklmnopqrstuvwxyz " + "word " * 400,
                                   "pull_request": {"merged_at": None}})
        self.assertNotIn("sk-proj", item["body"])
        self.assertLessEqual(len(item["body"]), COLLECTOR.PR_BODY_LIMIT)

    def test_old_day_files_are_upgraded_without_losing_sessions(self):
        os.environ["TZ"] = "UTC"
        time.tzset()
        with tempfile.TemporaryDirectory() as tmp:
            home, out = Path(tmp) / "home", Path(tmp) / "out"
            today = datetime.now(timezone.utc).date()
            kept_day, redone_day = (today - timedelta(days=3)).isoformat(), (today - timedelta(days=2)).isoformat()
            machine_dir = out / "sessions" / "m"
            machine_dir.mkdir(parents=True)
            old_session = {"tool": "claude", "session_id": "gone", "start": f"{kept_day}T09:00:00Z", "active_minutes": 5}
            for day, sessions in ((kept_day, [old_session]), (redone_day, [])):
                (machine_dir / f"{day}.json").write_text(json.dumps({"schema": 1, "date": day, "machine": "m", "sessions": sessions}))
            start = datetime.fromisoformat(f"{redone_day}T10:00:00+00:00")
            _write_jsonl(home / "claude" / "p" / "s.jsonl", [
                {"type": "user", "sessionId": "s", "timestamp": _iso(start), "cwd": "/nonexistent/jarvis",
                 "message": {"role": "user", "content": "Добавь напоминания"}},
                {"type": "assistant", "sessionId": "s", "timestamp": _iso(start + timedelta(minutes=3)),
                 "message": {"role": "assistant", "content": [{"type": "text", "text": "Напоминания работают"}]}},
            ])
            with patch.object(COLLECTOR, "CLAUDE_DIRS", [home / "claude"]), patch.object(COLLECTOR, "CODEX_DIRS", []):
                COLLECTOR.main(["--out", str(out), "--machine", "m", "--backfill-days", "5", "--recent-days", "1"])
            kept = json.loads((machine_dir / f"{kept_day}.json").read_text())
            redone = json.loads((machine_dir / f"{redone_day}.json").read_text())
        self.assertEqual(kept["schema"], COLLECTOR.SCHEMA)
        self.assertEqual(kept["sessions"], [old_session])  # logs are gone: the old record stays
        self.assertEqual(redone["schema"], COLLECTOR.SCHEMA)
        self.assertEqual(redone["sessions"][0]["asks"], ["Добавь напоминания"])
        self.assertEqual(redone["sessions"][0]["outcome"], "Напоминания работают")

    def test_pull_heads_follow_every_page(self):
        pages = {1: [{"number": n, "head": {"ref": f"b{n}"}, "state": "closed"} for n in range(100)],
                 2: [{"number": 100, "head": {"ref": "late-branch"}, "state": "open"}]}

        def fake_get(path, token, params=None):
            return pages.get(int(params["page"]), [])

        with patch.object(COLLECTOR, "github_get", side_effect=fake_get):
            heads = COLLECTOR.repo_pull_heads("pirajoke/x", "t")
        self.assertEqual(len(heads), 101)
        self.assertIn("late-branch", {pull["head"] for pull in heads})

        def failing_second_page(path, token, params=None):
            if params["page"] == "2":
                raise OSError("network")
            return pages[1]

        with patch.object(COLLECTOR, "github_get", side_effect=failing_second_page):
            self.assertIsNone(COLLECTOR.repo_pull_heads("pirajoke/x", "t"))


class ProjectionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        os.environ["TZ"] = "UTC"
        time.tzset()
        self.now = datetime(2026, 10, 9, 8, 0, tzinfo=timezone.utc)
        yesterday = "2026-10-08"
        start = datetime(2026, 10, 8, 9, 0, tzinfo=timezone.utc)

        def session(tool, project, repo, branch, minutes, offset=0, topic="private topic", day=start):
            begin = day + timedelta(minutes=offset)
            return {"tool": tool, "session_id": f"{tool}-{project}-{offset}", "project": project, "repo": repo,
                    "branch": branch, "start": _iso(begin), "end": _iso(begin + timedelta(minutes=minutes)),
                    "active_minutes": minutes, "prompts": 3, "topic": topic,
                    "intervals": [[_iso(begin), _iso(begin + timedelta(minutes=minutes))]]}

        self._write_day("mac-mini", yesterday, [
            session("claude", "agent-dashboard", "pirajoke/agent-dashboard", "claude/work", 60),
            session("codex", "agent-dashboard", "pirajoke/agent-dashboard", "main", 30, offset=30),
        ])
        self._write_day("macbook-pro", yesterday, [session("claude", "jarvis", "pirajoke/jarvis", "feat/voice", 45, offset=120)])
        self._write_day("macbook-pro", "2026-10-05", [session("codex", "jarvis", "pirajoke/jarvis", "old/idea", 20, day=start - timedelta(days=3))])
        self._write_day("macbook-pro", "2026-09-25", [session("claude", "lexi", "pirajoke/lexi", "stale/branch", 15, day=start - timedelta(days=13))])
        github = {
            "ok": True, "collected_at": _iso(self.now - timedelta(hours=1)),
            "prs": [
                {"repo": "pirajoke/agent-dashboard", "number": 49, "title": "Daily work", "url": "https://github.com/pirajoke/agent-dashboard/pull/49",
                 "state": "closed", "created_at": "2026-10-08T09:10:00Z", "updated_at": "2026-10-08T15:00:00Z",
                 "closed_at": "2026-10-08T15:00:00Z", "merged_at": "2026-10-08T15:00:00Z"},
                {"repo": "pirajoke/jarvis", "number": 140, "title": "Abandoned idea", "url": "https://github.com/pirajoke/jarvis/pull/140",
                 "state": "closed", "created_at": "2026-10-06T09:10:00Z", "updated_at": "2026-10-07T15:00:00Z",
                 "closed_at": "2026-10-07T15:00:00Z", "merged_at": None},
                {"repo": "pirajoke/lexi", "number": 12, "title": "Old open PR", "url": "https://github.com/pirajoke/lexi/pull/12",
                 "state": "open", "created_at": "2026-09-01T09:10:00Z", "updated_at": "2026-09-20T15:00:00Z",
                 "closed_at": None, "merged_at": None},
            ],
            "open_issues": [], "commits": [{"repo": "pirajoke/agent-dashboard", "date": "2026-10-08T15:00:00Z"}],
            "pr_heads": {
                "pirajoke/agent-dashboard": [{"number": 49, "head": "claude/work", "state": "closed"}],
                "pirajoke/jarvis": [{"number": 140, "head": "other", "state": "closed"}],
                "pirajoke/lexi": [{"number": 12, "head": "something", "state": "open"}],
            },
        }
        (self.root / "github.json").write_text(json.dumps(github), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def _write_day(self, machine, day, sessions):
        path = self.root / "sessions" / machine / f"{day}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"schema": 1, "date": day, "machine": machine,
                                    "collected_at": _iso(self.now - timedelta(hours=1)),
                                    "sources": {"claude": {"ok": True}, "codex": {"ok": True}},
                                    "sessions": sessions}), encoding="utf-8")

    def test_owner_projection_merges_machines_and_finds_outcomes(self):
        payload = work_projection(self.root, now=self.now, owner=True)
        self.assertEqual(payload["state"], "live")
        self.assertEqual(payload["selected_date"], "2026-10-08")
        day = payload["day"]
        self.assertEqual(day["claude_minutes"], 105)
        self.assertEqual(day["codex_minutes"], 30)
        self.assertEqual(day["total_minutes"], 105)  # codex overlapped claude in time
        self.assertEqual(day["prs_merged"], 1)
        self.assertEqual(day["projects"][0]["project"], "agent-dashboard")
        self.assertEqual(day["projects"][0]["merged"][0]["number"], 49)
        dropped = {(item["kind"], item.get("branch") or item.get("number")) for item in payload["dropped"]}
        self.assertIn(("pr_closed", 140), dropped)
        self.assertIn(("branch", "old/idea"), dropped)
        self.assertNotIn(("branch", "feat/voice"), dropped)  # touched yesterday, still in progress
        forgot = {(item["kind"], item.get("branch") or item.get("number")) for item in payload["forgot"]}
        self.assertIn(("pr_open", 12), forgot)
        self.assertIn(("branch", "stale/branch"), forgot)
        self.assertEqual(len(payload["series"]), 30)
        self.assertEqual(payload["traction"]["last_7"]["prs_merged"], 1)

    def test_public_projection_has_numbers_only(self):
        payload = work_projection(self.root, now=self.now, owner=False)
        text = json.dumps(payload, ensure_ascii=False)
        for private in ("agent-dashboard", "jarvis", "private topic", "Daily work", "feat/voice", "macbook-pro"):
            self.assertNotIn(private, text)
        self.assertEqual(payload["day"]["total_minutes"], 105)
        self.assertGreaterEqual(payload["dropped_count"], 2)
        self.assertNotIn("dropped", payload)

    def test_projects_use_platform_products_and_drill_down(self):
        payload = work_projection(self.root, now=self.now, owner=True, project="jarvis")
        projects = {item["id"]: item for item in payload["projects"]}
        self.assertEqual(set(projects), {"command-center", "jarvis", "mydictionary"})
        self.assertEqual(projects["command-center"]["mascot"], "hub")
        self.assertEqual(projects["command-center"]["total_minutes"], 60)  # Codex overlapped Claude
        self.assertEqual(projects["command-center"]["prs_merged"], 1)
        self.assertEqual(projects["jarvis"]["total_minutes"], 65)
        self.assertEqual(projects["jarvis"]["loose"], 2)
        self.assertEqual(projects["mydictionary"]["name"], "Lexi")
        self.assertEqual(projects["mydictionary"]["prs_open"], 1)
        self.assertEqual(len(projects["jarvis"]["daily_minutes"]), 30)
        # The board splits each week by agent and puts Platforms products first (2026-10-21).
        self.assertEqual(len(projects["command-center"]["daily_claude_minutes"]), 30)
        self.assertEqual(sum(projects["command-center"]["daily_claude_minutes"]), projects["command-center"]["claude_minutes"])
        self.assertEqual(sum(projects["command-center"]["daily_codex_minutes"]), projects["command-center"]["codex_minutes"])
        self.assertTrue(all(item["main"] for item in projects.values()))
        self.assertEqual(payload["project_total"], 3)
        detail = payload["project"]
        timeline = {day["date"]: day for day in detail["timeline"]}
        self.assertEqual(list(timeline), ["2026-10-08", "2026-10-07", "2026-10-06", "2026-10-05"])
        self.assertEqual(timeline["2026-10-08"]["sessions"][0]["topic"], "private topic")
        self.assertEqual(timeline["2026-10-06"]["opened"][0]["number"], 140)
        self.assertEqual(timeline["2026-10-07"]["closed_unmerged"][0]["number"], 140)
        self.assertEqual({item["bucket"] for item in detail["loose_list"]}, {"dropped"})

    def _write_summary(self, day, projects, headline="Главное за день"):
        path = self.root / "summaries" / f"{day}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"schema": 1, "date": day, "generated_at": "2026-10-09T03:00:00Z",
                                    "day": headline, "projects": projects}, ensure_ascii=False), encoding="utf-8")

    def test_owner_sees_plain_language_summaries(self):
        self._write_summary("2026-10-08", {
            "command-center": ["Появился раздел с итогами дня"],
            "jarvis": ["Голосовые ответы стали быстрее", "  "],
            "unknown": ["не продукт"],
        })
        self._write_summary("2026-10-05", {"jarvis": ["Начали голосовой режим"]})
        (self.root / "summaries" / "status.json").write_text(json.dumps({"ok": True, "pending": 0}))
        payload = work_projection(self.root, now=self.now, owner=True, project="jarvis")
        summary = payload["day"]["summary"]
        self.assertEqual(summary["headline"], "Главное за день")
        self.assertEqual([(p["id"], p["bullets"]) for p in summary["projects"]], [
            ("command-center", ["Появился раздел с итогами дня"]),
            ("jarvis", ["Голосовые ответы стали быстрее"]),
        ])
        self.assertEqual(payload["summaries_status"], {"ok": True, "pending": 0})
        projects = {item["id"]: item for item in payload["projects"]}
        self.assertTrue(projects["jarvis"]["description"].startswith("Личный ассистент"))
        self.assertEqual(projects["jarvis"]["last_summary"], {"date": "2026-10-08", "bullets": ["Голосовые ответы стали быстрее"]})
        self.assertIsNone(projects["mydictionary"]["last_summary"])
        timeline = {day["date"]: day for day in payload["project"]["timeline"]}
        self.assertEqual(timeline["2026-10-05"]["summary"], ["Начали голосовой режим"])
        self.assertIsNone(timeline["2026-10-07"]["summary"])

    def test_day_without_summary_says_so(self):
        payload = work_projection(self.root, now=self.now, owner=True)
        self.assertIsNone(payload["day"]["summary"])
        self.assertIsNone(payload["summaries_status"])

    def test_summary_inputs_are_never_served(self):
        self._write_day("mac-mini", "2026-10-07", [{
            "tool": "claude", "session_id": "x", "project": "jarvis", "repo": "pirajoke/jarvis", "branch": "main",
            "start": "2026-10-07T09:00:00Z", "end": "2026-10-07T09:20:00Z", "active_minutes": 20, "prompts": 1,
            "topic": "t", "intervals": [["2026-10-07T09:00:00Z", "2026-10-07T09:20:00Z"]],
            "asks": ["secret ask"], "outcome": "secret reply"}])
        github = json.loads((self.root / "github.json").read_text())
        github["prs"][0]["body"] = "secret body"
        (self.root / "github.json").write_text(json.dumps(github))
        self._write_summary("2026-10-08", {"jarvis": ["Голосовые ответы стали быстрее"]})
        owner = json.dumps([work_projection(self.root, now=self.now, owner=True, project=pid, selected=day)
                            for pid in ("jarvis", "command-center") for day in ("2026-10-07", "2026-10-08")], ensure_ascii=False)
        for secret in ("secret ask", "secret reply", "secret body"):
            self.assertNotIn(secret, owner)
        public = json.dumps(work_projection(self.root, now=self.now, owner=False, project="jarvis"), ensure_ascii=False)
        for private in ("Голосовые", "Личный ассистент", "summaries_status", "secret"):
            self.assertNotIn(private, public)
        self.assertNotIn("summary", work_projection(self.root, now=self.now, owner=False)["day"])

    def _write_paper_summary(self, day, details, headline="Главное за день", in_progress=False):
        path = self.root / "summaries" / f"{day}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "schema": 2, "date": day, "generated_at": "2026-10-09T03:00:00Z", "day": headline, "in_progress": in_progress,
            "projects": {pid: (d.get("agents") or []) + (d.get("you") or []) for pid, d in details.items()},
            "details": details}, ensure_ascii=False), encoding="utf-8")

    def test_days_list_the_newest_work_first(self):
        payload = work_projection(self.root, now=self.now, owner=True, edition=True)
        feed = payload["feed"]
        # Only days with work, newest first; nothing yet today; older than 14 days is left out.
        self.assertEqual([day["date"] for day in feed], ["2026-10-08", "2026-10-07", "2026-10-06", "2026-10-05"])
        day = feed[0]
        self.assertEqual((day["is_today"], day["headline"], day["total_minutes"], day["prs_merged"]), (False, None, 105, 1))
        self.assertEqual([p["id"] for p in day["projects"]], ["command-center", "jarvis"])  # busiest first
        hub = day["projects"][0]
        self.assertEqual((hub["minutes"], hub["sessions"], hub["bullets"]), (60, 2, []))
        self.assertFalse(hub["quiet"])  # no summary yet: named until Claude retells it
        self.assertEqual(hub["merged"][0]["number"], 49)
        closed = feed[1]["projects"]
        self.assertEqual(([p["id"] for p in closed], closed[0]["closed"][0]["number"], closed[0]["minutes"]), (["jarvis"], 140, 0))

        self._write_day("mac-mini", "2026-10-09", [{
            "tool": "claude", "session_id": "today", "project": "lexi", "repo": "pirajoke/lexi", "branch": "main",
            "start": "2026-10-09T07:00:00Z", "end": "2026-10-09T07:30:00Z", "active_minutes": 30, "prompts": 1,
            "topic": "t", "intervals": [["2026-10-09T07:00:00Z", "2026-10-09T07:30:00Z"]],
            "infra_actions": [{"at": "2026-10-09T07:10:00Z", "command": "launchctl kickstart x"}]}])
        today = work_projection(self.root, now=self.now, owner=True, edition=True)["feed"][0]
        self.assertEqual((today["date"], today["is_today"], [p["id"] for p in today["projects"]]),
                         ("2026-10-09", True, ["mydictionary"]))
        self.assertEqual(today["projects"][0]["commands"], 1)

    def test_days_read_what_claude_wrote(self):
        self._write_paper_summary("2026-10-05", {"jarvis": {
            "lead": "Голос в работе", "you": [], "agents": ["Начали голосовой режим"], "next": ["Проверить голос"],
            "deadlines": [{"date": "2026-11-07", "what": "Продлить проверку цен"}, {"date": "2026-10-01", "what": "Прошло"}]}})
        self._write_paper_summary("2026-10-08", {
            "jarvis": {"lead": "Бот отвечает голосом", "you": ["Решили оставить голос"], "agents": ["Ответы стали быстрее"],
                       "next": [], "deadlines": [{"date": "2026-10-20", "what": "Показать друзьям"}]},
            "command-center": {"lead": "Появились итоги дня", "you": [], "agents": ["Итоги дня на сайте"],
                               "next": ["Сохранить токен на Mac mini"],
                               "deadlines": [{"date": "2026-10-20", "what": "Показать друзьям"}]},
            "mydictionary": {"lead": "Старое", "you": [], "agents": ["Устаревший итог"], "next": [], "deadlines": []},
        }, headline="Голос и итоги дня", in_progress=True)
        self._write_paper_summary("2026-10-04", {"jarvis": {"lead": "Старое", "you": [], "agents": ["Устаревший итог"],
                                                            "next": [], "deadlines": []}})
        payload = work_projection(self.root, now=self.now, owner=True, edition=True)
        days = {day["date"]: day for day in payload["feed"]}
        # A summary without work behind it that day (sessions moved elsewhere) is not shown.
        self.assertNotIn("2026-10-04", days)
        self.assertNotIn("Устаревший итог", json.dumps(payload["feed"], ensure_ascii=False))
        day = days["2026-10-08"]
        self.assertEqual((day["headline"], day["in_progress"], day["written_at"]), ("Голос и итоги дня", True, "2026-10-09T03:00:00Z"))
        projects = {p["id"]: p for p in day["projects"]}
        self.assertEqual(projects["jarvis"]["bullets"], ["Ответы стали быстрее", "Решили оставить голос"])
        self.assertFalse(projects["jarvis"]["quiet"])
        self.assertEqual(projects["command-center"]["bullets"], ["Итоги дня на сайте"])
        self.assertEqual(days["2026-10-05"]["projects"][0]["bullets"], ["Начали голосовой режим"])
        self.assertIsNone(days["2026-10-07"]["headline"])
        self.assertEqual(payload["deadlines"], [
            {"date": "2026-10-20", "what": "Показать друзьям", "project_id": "command-center", "project": "Command Center"},
            {"date": "2026-10-20", "what": "Показать друзьям", "project_id": "jarvis", "project": "JARVIS"},
            {"date": "2026-11-07", "what": "Продлить проверку цен", "project_id": "jarvis", "project": "JARVIS"},
        ])  # past ones dropped, every summary in the window counts, same words in two projects kept apart

    def test_quick_looks_and_empty_retellings_are_not_news(self):
        self._write_day("mac-mini", "2026-10-04", [{
            "tool": "codex", "session_id": "peek", "project": "lexi", "repo": "pirajoke/lexi", "branch": "main",
            "start": "2026-10-04T09:00:00Z", "end": "2026-10-04T09:01:00Z", "active_minutes": 1, "prompts": 1,
            "topic": "peek", "intervals": [["2026-10-04T09:00:00Z", "2026-10-04T09:01:00Z"]]}])
        self._write_day("macbook-pro", "2026-10-08", [
            {"tool": "claude", "session_id": "j", "project": "jarvis", "repo": "pirajoke/jarvis", "branch": "feat/voice",
             "start": "2026-10-08T11:00:00Z", "end": "2026-10-08T11:45:00Z", "active_minutes": 45, "prompts": 3, "topic": "t",
             "intervals": [["2026-10-08T11:00:00Z", "2026-10-08T11:45:00Z"]]},
            {"tool": "codex", "session_id": "l", "project": "lexi", "repo": "pirajoke/lexi", "branch": "main",
             "start": "2026-10-08T12:00:00Z", "end": "2026-10-08T12:02:00Z", "active_minutes": 2, "prompts": 1, "topic": "t",
             "intervals": [["2026-10-08T12:00:00Z", "2026-10-08T12:02:00Z"]]},
        ])
        path = self.root / "summaries" / "2026-10-08.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"schema": 2, "date": "2026-10-08", "day": "Итоги дня",
                                    "projects": {"command-center": ["Появились итоги дня"]},
                                    "details": {"command-center": {"lead": None, "you": [], "agents": ["Появились итоги дня"],
                                                                   "next": [], "deadlines": []}},
                                    "quiet": ["jarvis"]}, ensure_ascii=False), encoding="utf-8")
        feed = work_projection(self.root, now=self.now, owner=True, edition=True)["feed"]
        self.assertNotIn("2026-10-04", [day["date"] for day in feed])  # one minute in one project only
        projects = {p["id"]: p for p in feed[0]["projects"]}
        self.assertEqual({pid: p["quiet"] for pid, p in projects.items()},
                         {"command-center": False, "jarvis": True, "mydictionary": True})

    def test_todo_lists_what_waits_on_mark(self):
        github = json.loads((self.root / "github.json").read_text(encoding="utf-8"))
        github["prs"].append({"repo": "pirajoke/jarvis", "number": 150, "title": "Draft", "url": "https://github.com/pirajoke/jarvis/pull/150",
                              "state": "open", "draft": True, "created_at": "2026-10-08T09:00:00Z", "updated_at": "2026-10-08T09:00:00Z",
                              "closed_at": None, "merged_at": None})
        (self.root / "github.json").write_text(json.dumps(github), encoding="utf-8")
        self._write_paper_summary("2026-10-05", {"jarvis": {
            "lead": None, "you": [], "agents": ["Начали голос"], "next": ["Старый шаг"], "deadlines": []}})
        self._write_paper_summary("2026-10-08", {
            "jarvis": {"lead": None, "you": [], "agents": ["Голос готов"], "next": [],
                       "deadlines": [{"date": "2026-10-20", "what": "Показать друзьям"}]},
            "command-center": {"lead": None, "you": [], "agents": ["Итоги дня"], "next": ["Сохранить токен"], "deadlines": []},
        })
        todo = {item["id"]: item for item in work_projection(self.root, now=self.now, owner=True)["todo"]}
        # The nearest deadline first; the newest summary decides the next steps, an older list is not reused.
        self.assertEqual(list(todo), ["jarvis", "command-center", "mydictionary"])
        self.assertEqual((todo["jarvis"]["next"], todo["jarvis"]["deadlines"], todo["jarvis"]["open_prs"], todo["jarvis"]["drafts"]),
                         ([], [{"date": "2026-10-20", "what": "Показать друзьям"}], [], 1))
        self.assertEqual((todo["command-center"]["next"], todo["command-center"]["next_from"]), (["Сохранить токен"], "2026-10-08"))
        self.assertEqual(([pr["number"] for pr in todo["mydictionary"]["open_prs"]], todo["mydictionary"]["loose"]), ([12], 2))
        public = work_projection(self.root, now=self.now, owner=False)
        self.assertNotIn("todo", public)

    def test_todo_keeps_old_ready_prs_and_every_deadline(self):
        github = json.loads((self.root / "github.json").read_text(encoding="utf-8"))
        github["prs"].append({"repo": "pirajoke/quiet-repo", "number": 3, "title": "Ready long ago",
                              "url": "https://github.com/pirajoke/quiet-repo/pull/3", "state": "open",
                              "created_at": "2026-07-01T09:00:00Z", "updated_at": "2026-07-02T09:00:00Z",
                              "closed_at": None, "merged_at": None})
        (self.root / "github.json").write_text(json.dumps(github), encoding="utf-8")
        deadlines = [{"date": f"2026-10-{day}", "what": f"Срок {day}"} for day in range(10, 20)]
        self._write_paper_summary("2026-10-08", {"jarvis": {"lead": None, "you": [], "agents": ["Голос"], "next": [],
                                                            "deadlines": deadlines}})
        payload = work_projection(self.root, now=self.now, owner=True, edition=True)
        todo = {item["id"]: item for item in payload["todo"]}
        self.assertEqual([pr["number"] for pr in todo["p-quietrepo"]["open_prs"]], [3])  # no activity in the window
        self.assertEqual(len(todo["jarvis"]["deadlines"]), 10)
        self.assertEqual(len(payload["deadlines"]), 8)  # the banner in «По дням» stays short
        project = work_projection(self.root, now=self.now, owner=True, project="jarvis")["project"]
        self.assertEqual([d["date"] for d in project["deadlines"]], [f"2026-10-{day}" for day in range(10, 20)])

    def test_a_quick_look_with_an_old_summary_is_still_quiet(self):
        self._write_day("mac-mini", "2026-10-06", [{
            "tool": "codex", "session_id": "peek", "project": "lexi", "repo": "pirajoke/lexi", "branch": "main",
            "start": "2026-10-06T09:00:00Z", "end": "2026-10-06T09:01:00Z", "active_minutes": 1, "prompts": 1,
            "topic": "peek", "intervals": [["2026-10-06T09:00:00Z", "2026-10-06T09:01:00Z"]]}])
        self._write_paper_summary("2026-10-06", {"mydictionary": {"lead": None, "you": [], "agents": ["Агенты работали"],
                                                                  "next": [], "deadlines": []}})
        day = {d["date"]: d for d in work_projection(self.root, now=self.now, owner=True, edition=True)["feed"]}["2026-10-06"]
        lexi = {p["id"]: p for p in day["projects"]}["mydictionary"]
        self.assertEqual((lexi["bullets"], lexi["quiet"]), ([], True))

    def test_open_issues_are_the_project_todo(self):
        github = json.loads((self.root / "github.json").read_text(encoding="utf-8"))
        github["open_issues"] = [
            {"repo": "pirajoke/jarvis", "number": 7, "title": "Голос в машине", "url": "https://github.com/pirajoke/jarvis/issues/7",
             "created_at": "2026-10-01T09:00:00Z", "updated_at": "2026-10-08T09:00:00Z"},
            {"repo": "pirajoke/lexi", "number": 3, "title": "Продлить цены", "url": "https://github.com/pirajoke/lexi/issues/3",
             "created_at": "2026-10-01T09:00:00Z", "updated_at": "2026-10-02T09:00:00Z"},
            {"repo": "pirajoke/unknown-repo", "number": 1, "title": "Чужое", "url": "https://github.com/pirajoke/unknown-repo/issues/1",
             "created_at": "2026-10-01T09:00:00Z", "updated_at": "2026-10-02T09:00:00Z"},
        ]
        (self.root / "github.json").write_text(json.dumps(github), encoding="utf-8")
        self._write_paper_summary("2026-10-08", {"jarvis": {"lead": "Голос", "you": [], "agents": ["Быстрее"],
                                                            "next": ["Проверить голос"], "deadlines": []}})
        project = work_projection(self.root, now=self.now, owner=True, project="jarvis")["project"]
        self.assertEqual(([i["number"] for i in project["open_issues_list"]], project["open_issues_count"], project["next_steps"]),
                         ([7], 1, ["Проверить голос"]))
        self.assertEqual(project["now"], {"date": "2026-10-08", "text": "Голос"})
        self.assertEqual(project["deadlines"], [])
        # A newer summary without a lead does not bring back the old one as «what is going on now».
        self._write_paper_summary("2026-10-08", {"jarvis": {"lead": None, "you": [], "agents": ["Голос готов"],
                                                            "next": [], "deadlines": []}})
        self._write_paper_summary("2026-10-07", {"jarvis": {"lead": "Начали голос", "you": [], "agents": ["Начали"],
                                                            "next": [], "deadlines": []}})
        self.assertIsNone(work_projection(self.root, now=self.now, owner=True, project="jarvis")["project"]["now"])
        lexi = work_projection(self.root, now=self.now, owner=True, edition=True, project="mydictionary")
        self.assertEqual([i["title"] for i in lexi["project"]["open_issues_list"]], ["Продлить цены"])
        self.assertNotIn("Чужое", json.dumps(lexi, ensure_ascii=False))  # a repo with no product stays out
        public = json.dumps(work_projection(self.root, now=self.now, owner=False, edition=True, project="jarvis"), ensure_ascii=False)
        self.assertNotIn("Голос в машине", public)

    def test_a_known_project_with_only_an_open_issue_keeps_its_todo(self):
        github = json.loads((self.root / "github.json").read_text(encoding="utf-8"))
        github["open_issues"] = [
            {"repo": "pirajoke/accountable-os", "number": 4, "title": "Декларация URSSAF", "url": "https://github.com/pirajoke/accountable-os/issues/4",
             "created_at": "2026-07-01T09:00:00Z", "updated_at": "2026-07-02T09:00:00Z"},
        ]
        (self.root / "github.json").write_text(json.dumps(github), encoding="utf-8")
        payload = work_projection(self.root, now=self.now, owner=True, edition=True, project="accountable")
        self.assertIn("accountable", {item["id"] for item in payload["projects"]})
        self.assertNotIn("accountable", {p["id"] for day in payload["feed"] for p in day["projects"]})  # no work, no day
        self.assertEqual((payload["project"]["open_issues_count"], payload["project"]["total_minutes"]), (1, 0))

    def test_days_count_a_day_with_only_a_closed_pr(self):
        github = json.loads((self.root / "github.json").read_text(encoding="utf-8"))
        github["prs"].append({"repo": "pirajoke/jarvis", "number": 141, "title": "Dropped", "url": "https://github.com/pirajoke/jarvis/pull/141",
                              "state": "closed", "created_at": "2026-10-08T10:00:00Z", "updated_at": "2026-10-09T07:00:00Z",
                              "closed_at": "2026-10-09T07:00:00Z", "merged_at": None})
        (self.root / "github.json").write_text(json.dumps(github), encoding="utf-8")
        day = work_projection(self.root, now=self.now, owner=True, edition=True)["feed"][0]
        self.assertEqual((day["date"], day["total_minutes"], [p["id"] for p in day["projects"]]), ("2026-10-09", 0, ["jarvis"]))
        self.assertEqual([pr["number"] for pr in day["projects"][0]["closed"]], [141])  # the only fact that day

    def test_days_are_owner_only(self):
        self._write_paper_summary("2026-10-08", {"jarvis": {"lead": "Бот отвечает голосом", "you": [], "agents": ["Быстрее"],
                                                            "next": [], "deadlines": [{"date": "2026-10-20", "what": "Показать"}]}})
        public = work_projection(self.root, now=self.now, owner=False, edition=True)
        self.assertNotIn("feed", public)
        self.assertNotIn("deadlines", public)
        self.assertEqual(public["day"]["date"], "2026-10-08")  # the newest working day's numbers only
        text = json.dumps(public, ensure_ascii=False)
        for private in ("Быстрее", "Показать", "JARVIS", "private topic"):
            self.assertNotIn(private, text)
        self.assertNotIn("feed", work_projection(self.root, now=self.now, owner=True))  # only when asked

    def test_product_mapping_follows_platforms(self):
        from dashboard_builder.daily_work import product_for
        self.assertEqual(product_for("FINANCIAL OS", None)["id"], "financial")
        self.assertEqual(product_for(None, "pirajoke/agent-dashboard")["mascot"], "hub")
        self.assertEqual(product_for("health-os", None)["mascot"], "health")
        other = product_for("skills-library", None)
        self.assertEqual((other["id"], other["mascot"]), ("p-skillslibrary", None))
        # Cyrillic names keep their letters, so two ChatGPT projects do not merge into one.
        self.assertNotEqual(product_for("ChatGPT · Любовь", None)["id"], product_for("ChatGPT · без проекта", None)["id"])
        self.assertEqual(product_for("ChatGPT · SHOPIFY", None)["name"], "ChatGPT · SHOPIFY")
        self.assertIsNone(other["description"])
        self.assertEqual(product_for(None, "pirajoke/ai-singularity-news-bot")["id"], "ai-singularity")
        self.assertEqual(product_for("context-news-france", None)["id"], "context-news")
        self.assertEqual(product_for("ai-singularity", None)["id"], "ai-singularity")
        self.assertEqual(product_for("urssaf-helper", None)["id"], "accountable")
        self.assertTrue(product_for("lexi", None)["description"])
        self.assertTrue(product_for("lexi", None)["about"])
        self.assertIsNone(other["about"])

    def test_public_projection_hides_projects(self):
        payload = work_projection(self.root, now=self.now, owner=False, project="jarvis")
        self.assertNotIn("projects", payload)
        self.assertNotIn("project", payload)
        self.assertEqual(payload["project_total"], 3)

    def test_missing_collection_is_reported_as_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload = work_projection(Path(tmp), now=self.now, owner=True)
        self.assertEqual(payload["state"], "empty")
        self.assertEqual(payload["day"]["total_minutes"], 0)

    def test_old_collection_is_stale(self):
        payload = work_projection(self.root, now=self.now + timedelta(hours=12), owner=True)
        self.assertEqual(payload["state"], "stale")


class SourceFreshnessTests(unittest.TestCase):
    """AC-5/6, EC-5: source age never comes from response generated_at."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.now = datetime(2026, 10, 19, 16, 0, tzinfo=timezone.utc)

    def machine(self, name, timestamp, sources=None):
        path = self.root / "sessions" / name / "2026-10-19.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {"schema": 2, "machine": name, "date": "2026-10-19", "sessions": [],
                "sources": sources if sources is not None else {"claude": {"ok": True}, "codex": {"ok": True}}}
        if timestamp is not None:
            data["collected_at"] = timestamp
        path.write_text(json.dumps(data))

    def github(self, timestamp, ok=True):
        (self.root / "github.json").write_text(json.dumps({"ok": ok, "collected_at": timestamp,
                                                        "prs": [], "commits": [], "open_issues": []}))

    def test_ac_5_mini_pro_and_github_have_independent_freshness(self):
        self.machine("mac-mini", _iso(self.now - timedelta(minutes=10)))
        self.machine("macbook-pro", _iso(self.now - timedelta(hours=8)))
        self.github(_iso(self.now - timedelta(hours=9)))
        payload = work_projection(self.root, now=self.now, owner=True)
        sources = payload["sources"]
        by_name = {m["machine"]: m for m in sources["machines"]}
        self.assertEqual((by_name["mac-mini"].get("state"), by_name["mac-mini"].get("age_seconds")), ("live", 600))
        self.assertEqual((by_name["macbook-pro"].get("state"), by_name["macbook-pro"].get("age_seconds")), ("stale", 28800))
        self.assertEqual((sources["github"].get("state"), sources["github"].get("age_seconds")), ("stale", 32400))
        # Preserve existing aggregate fields without using them to recolor every source.
        self.assertEqual(payload["generated_at"], _iso(self.now))
        self.assertEqual(payload["collected_at"], _iso(self.now - timedelta(minutes=10)))
        self.assertEqual(payload["state"], "live")
        self.assertIn("Оценка по активности сессий", payload["time_estimate_note"])

    def test_ec_5_exact_six_hour_boundary_is_live_then_stale(self):
        for seconds, state in ((21600, "live"), (21601, "stale")):
            self.machine("boundary", _iso(self.now - timedelta(seconds=seconds)))
            self.github(_iso(self.now - timedelta(seconds=seconds)))
            with self.subTest(seconds=seconds):
                sources = work_projection(self.root, now=self.now, owner=True)["sources"]
                for item in (sources["machines"][0], sources["github"]):
                    self.assertEqual(item.get("state"), state)
                    self.assertEqual(item.get("age_seconds"), seconds)

    def test_ac_5_ec_5_missing_invalid_and_future_times_stay_unknown_not_dropped(self):
        for name, value in (("missing", None), ("invalid", "bad-date"),
                            ("naive", "2026-10-19T15:00:00"), ("future", _iso(self.now + timedelta(seconds=1)))):
            self.machine(name, value)
        self.github("bad-date")
        sources = work_projection(self.root, now=self.now, owner=True)["sources"]
        self.assertEqual({m["machine"] for m in sources["machines"]}, {"missing", "invalid", "naive", "future"})
        for item in sources["machines"] + [sources["github"]]:
            with self.subTest(source=item):
                self.assertEqual(item.get("state"), "unknown")
                self.assertIn("age_seconds", item)
                self.assertIsNone(item["age_seconds"])
        self.assertEqual(work_projection(self.root, now=self.now, owner=True)["generated_at"], _iso(self.now))

    def test_ac_5_explicit_source_failure_is_unavailable_even_with_fresh_timestamp(self):
        self.machine("mac-mini", _iso(self.now), {"claude": {"ok": False, "error": "private path"}, "codex": {"ok": True}})
        self.github(_iso(self.now), ok=False)
        sources = work_projection(self.root, now=self.now, owner=True)["sources"]
        self.assertEqual(sources["machines"][0].get("state"), "unavailable")
        self.assertEqual(sources["github"].get("state"), "unavailable")

    def test_ac_5_new_github_failure_overrides_old_success(self):
        self.github(_iso(self.now - timedelta(minutes=20)))
        (self.root / "github-error.json").write_text(json.dumps({"collected_at": _iso(self.now), "reason": "fixture-failure"}))
        self.assertEqual(work_projection(self.root, now=self.now, owner=True)["sources"]["github"].get("state"), "unavailable")

    def test_ac_5_public_freshness_keeps_anonymized_machine_names(self):
        self.machine("private-owner-laptop", _iso(self.now - timedelta(hours=10)))
        self.github(_iso(self.now - timedelta(hours=1)))
        out = work_projection(self.root, now=self.now, owner=False)
        source = out["sources"]["machines"][0]
        self.assertEqual(source["machine"], "machine-1")
        self.assertEqual(source.get("state"), "stale")
        self.assertEqual(source.get("age_seconds"), 36000)
        self.assertEqual(out["sources"]["github"].get("state"), "live")
        self.assertNotIn("private-owner-laptop", json.dumps(out))
        self.assertNotIn("sources", source)

    def test_ac_5_newest_declared_day_invalid_or_failure_is_not_hidden_by_history(self):
        machine_dir = self.root / "sessions" / "macbook-pro"
        machine_dir.mkdir(parents=True)
        for latest in ({"collected_at": "invalid"}, {"collected_at": None},
                       {"collected_at": _iso(self.now), "sources": {"codex": {"ok": False}}}):
            older = {"schema": 2, "machine": "macbook-pro", "date": "2026-10-18",
                     "collected_at": _iso(self.now), "sources": {"codex": {"ok": True}}, "sessions": []}
            newer = {**older, "date": "2026-10-19", **latest}
            # Filename sorting differs deliberately from the declared dates.
            (machine_dir / "z-old.json").write_text(json.dumps(older))
            (machine_dir / "a-new.json").write_text(json.dumps(newer))
            with self.subTest(latest=latest):
                source = work_projection(self.root, now=self.now, owner=True)["sources"]["machines"][0]
                expected = "unavailable" if latest.get("sources") else "unknown"
                self.assertEqual(source.get("state"), expected)

    def test_ac_5_same_day_snapshots_use_latest_collection_time(self):
        folder = self.root / "sessions" / "mac-mini"
        folder.mkdir(parents=True)
        for filename, age, ok in (("z-old.json", 28800, False), ("a-new.json", 60, True)):
            (folder / filename).write_text(json.dumps({"schema": 2, "machine": "mac-mini", "date": "2026-10-19",
                "collected_at": _iso(self.now - timedelta(seconds=age)), "sources": {"codex": {"ok": ok}}, "sessions": []}))
        source = work_projection(self.root, now=self.now, owner=True)["sources"]["machines"][0]
        self.assertEqual(source.get("state"), "live")
        self.assertEqual(source.get("age_seconds"), 60)

    def test_ac_5_missing_github_is_unknown_not_a_green_zero(self):
        source = work_projection(self.root, now=self.now, owner=True)["sources"]["github"]
        self.assertEqual(source.get("state"), "unknown")
        self.assertIsNone(source.get("age_seconds"))
        self.assertIsNone(source.get("collected_at"))


class CommandCenterWorkSectionTest(unittest.TestCase):
    def test_ac_6_browser_displays_independent_states_and_paris_collection_time(self):
        import re
        import shutil
        import subprocess
        html = (BUILDER_DIR / "mac-mini-dashboard" / "index.html").read_text(encoding="utf-8")
        functions = re.findall(r"function (?:mmRenderSources|mmSource[\w]*)\([^)]*\)\s*\{[\s\S]*?\n\}", html)
        self.assertTrue(functions)
        javascript = r'''
const target = {textContent:''};
const document={getElementById:()=>target};
const dailyWorkData={sources:{machines:[
{machine:'Mini fixture',state:'live',collected_at:'2026-10-19T16:00:00Z',age_seconds:600},
{machine:'Pro fixture',state:'stale',collected_at:'2026-10-19T08:00:00Z',age_seconds:29400},
{machine:'Unknown fixture',state:'unknown',collected_at:null,age_seconds:null}],
github:{ok:false,state:'unavailable',collected_at:null,age_seconds:null}}};
const infraData={machines:[]};
function mmAgo(){return 'old relative formatter';}
''' + "\n".join(functions) + "\nmmRenderSources();process.stdout.write(JSON.stringify(target.textContent));"
        node = shutil.which("node") or str(Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node")
        run = subprocess.run([node, "-e", javascript], capture_output=True, text=True, timeout=10,
                             env={**os.environ, "TZ": "UTC"})
        self.assertEqual(run.returncode, 0, run.stderr)
        text = json.loads(run.stdout)
        self.assertRegex(text, r"(?i)Mini fixture[^·]*актуал")
        self.assertRegex(text, r"(?i)Pro fixture[^·]*устар")
        self.assertRegex(text, r"(?i)Unknown fixture[^·]*(?:неизвест|нет дат)")
        self.assertRegex(text, r"(?i)GitHub[^·]*(?:недоступ|ошиб)")
        self.assertIn("18:00", text, "16:00 UTC must display as 18:00 Paris on this date")
        self.assertNotIn("old relative formatter", text)

    def _render(self, setup, call):
        """Runs the page's own render functions in node on synthetic data and returns the HTML they build."""
        import re
        import shutil
        import subprocess
        html = (BUILDER_DIR / "mac-mini-dashboard" / "index.html").read_text(encoding="utf-8")
        names = ("mmPlural", "mmResultDay", "mmProjectBrief", "renderProjectPage", "mmMapResult", "mmMapCard",
                 "mmAttention", "mmBullets", "mmEsc", "escapeHtml")
        functions = [re.search(rf"function {name}\([^)]*\)\s*\{{[\s\S]*?\n\}}", html).group(0) for name in names]
        javascript = r'''
const nodes = {};
const document = {getElementById: id => (nodes[id] = nodes[id] || {textContent: '', innerHTML: '', addEventListener() {}})};
const MM_RESULT_DAYS_SHOWN = 5; let mmReturnView = 'map';
function npDue(iso) { return `срок ${iso}`; }
function mmDayHeading(iso) { return `день ${iso}`; }
function mmRelDay() { return 'сегодня, 14:50'; }
function mmArt() { return ''; } function mmPulse() { return ''; } function mmShowView() {}
''' + "\n".join(functions) + "\n" + setup + f"\nprocess.stdout.write(JSON.stringify({call}));"
        node = shutil.which("node") or str(Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node")
        run = subprocess.run([node, "-e", javascript], capture_output=True, text=True, timeout=10)
        self.assertEqual(run.returncode, 0, run.stderr)
        return json.loads(run.stdout)

    def test_project_page_tells_results_in_plain_words(self):
        # Mark 2026-10-23: «убери всю техническую дату … только результаты, чёткая сводка, понимание того,
        # что происходит». No hours, sessions, prompts, PRs, GitHub issues or repo names on the page.
        project = r'''
const base = {name: 'JARVIS', description: 'Ассистент', last_activity: '2026-10-23T14:50:00Z',
  dates: ['2026-10-22', '2026-10-23'], repos: ['pirajoke/jarvis'], sessions: 27, prompts: 22, total_minutes: 366,
  prs_open: 2, open_prs_list: [{number: 148, title: 'Hand the photos', draft: false}, {number: 150, title: 'WIP', draft: true}],
  open_issues_list: [{number: 98, title: 'Проверить агентов'}], open_issues_count: 1,
  now: {date: '2026-10-23', text: 'Ассистент стал надёжнее'}, next_steps: ['Включить голос'],
  deadlines: [{date: '2026-10-28', what: 'Выпустить версию'}],
  timeline: [{date: '2026-10-23', summary: ['Разбирает почту'], merged: [{number: 140, title: 'Mail'}]},
             {date: '2026-10-22', summary: null, merged: []}]};
function page(p) { mmProjectData = p; renderProjectPage(); return nodes['mm-project-page'].innerHTML; }
let mmProjectData;
'''
        full = self._render(project, "page(base)")
        for shown in ("Что сейчас", "Ассистент стал надёжнее", "Что дальше", "срок 2026-10-28", "Выпустить версию",
                      "Включить голос", "1 готовое изменение ждёт проверки", "Что получилось", "Разбирает почту"):
            self.assertIn(shown, full)
        for gone in ("pirajoke/jarvis", "#148", "Hand the photos", "WIP", "#98", "Проверить агентов", "#140",
                     "сесс", "промпт", "мин", "PR"):
            self.assertNotIn(gone, full)
        # Without a lead the newest result says what is going on; with nothing at all the page says so plainly.
        no_lead = self._render(project, "page({...base, now: null})")
        self.assertRegex(no_lead, r"Что сейчас</h4>\s*<p class=\"mm-brief-now\">Разбирает почту")
        empty = self._render(project, "page({...base, now: null, next_steps: [], deadlines: [], open_prs_list: [], timeline: []})")
        for shown in ("Сводка появится после первого итога дня.", "Следующих шагов пока нет.", "Итогов за 30 дней пока нет."):
            self.assertIn(shown, empty)

    def test_project_card_shows_its_last_result_not_numbers(self):
        card = self._render("", "mmMapCard({id: 'jarvis', name: 'JARVIS', last_activity: '2026-10-23T14:50:00Z', "
                                "daily_minutes: [90, 60], daily_claude_minutes: [90, 0], daily_codex_minutes: [0, 60], "
                                "last_summary: {date: '2026-10-23', bullets: ['Разбирает почту сам']}}, "
                                "{deadlines: [], open_prs_count: 3}, '2026-10-23')")
        self.assertIn("Разбирает почту сам", card)
        self.assertIn("ждёт проверки: 3", card)
        for gone in ("мин", " ч", "Claude", "Codex", "PR"):
            self.assertNotIn(gone, card)

    def test_dashboard_has_work_section_and_nav(self):
        html = (BUILDER_DIR / "mac-mini-dashboard" / "index.html").read_text(encoding="utf-8")
        self.assertIn('aria-controls="section-work"', html)
        self.assertIn('id="section-work"', html)
        self.assertIn("/api/work/daily", html)
        self.assertRegex(html, r"'work'[^\]]*\]\.includes\(INITIAL_SECTION\)")
        # MAIN MANAGER (Mark, 2026-10-14: «чтобы была визуализация проекта, который я делаю»):
        # the project board. Since 2026-10-26 («это все мусор») there is no history under it: no Notion
        # task list, no change log, no «Откуда данные» footer; sources and the phone QR sit behind «i».
        self.assertIn("renderMap(data);", html)
        self.assertNotIn("renderTodo(data);", html)
        self.assertNotIn('data-mm-view="loose"', html)
        for gone in ('id="mm-history"', 'id="mm-shared-tasks"', 'data-mm-panel="todo"', 'data-mm-panel="infra"',
                     'Открыть доску в Notion', 'class="mm-more"', 'Откуда данные · открыть на телефоне'):
            self.assertNotIn(gone, html)
        about = html[html.index('id="mm-about-dialog"'):html.index('</dialog>', html.index('id="mm-about-dialog"'))]
        self.assertIn('id="mm-sources"', about)
        self.assertIn('id="np-device"', about)
        self.assertIn('aria-controls="mm-about-dialog"', html)
        self.assertNotIn('Хвосты', html)
        self.assertNotIn('Готовы к слиянию', html)
        # Projects reuse the Platforms mascots and open a per-project page.
        self.assertIn('<use href="#cc-mascot-${mmEsc(item.mascot)}"/>', html)
        self.assertIn("project: id", html)
        # No separate day summary (Mark, 2026-10-14: MAIN MANAGER already says it): no «По дням»
        # feed and no summary view; a day's bullets stay in each project's history.
        self.assertNotIn('id="section-today"', html)
        self.assertNotIn('id="dp-days"', html)
        self.assertNotIn("edition: '1'", html)
        self.assertNotIn('data-mm-view="overview"', html)
        self.assertNotIn('id="mm-day-summary"', html)
        self.assertIn("mm-project-desc", html)

    def test_summarizer_is_deployed_on_the_mac_mini_only(self):
        deploy = (BUILDER_DIR / "deploy_to_scripts.sh").read_text(encoding="utf-8")
        install = (BUILDER_DIR / "install_daily_work_collector.sh").read_text(encoding="utf-8")
        self.assertIn("daily_work_summarizer.py", deploy)
        self.assertIn("--machine mac-mini --github --summaries", deploy)
        self.assertIn("com.pirajoke.daily-work-summarizer daily_work_summarizer.py", install)
        self.assertIn('if [[ "$SUMMARIES" == "1" ]]', install)

    def test_server_exposes_daily_work_endpoint(self):
        server = (BUILDER_DIR / "dashboard-server-m4.py").read_text(encoding="utf-8")
        self.assertIn('"/api/work/daily"', server)
        self.assertIn("owner=self._dashboard_run_authorized()", server)
        self.assertIn("edition=(query.get('edition') or ['0'])[0] == '1'", server)

    def test_dashboard_opens_on_main_manager_in_one_design(self):
        html = (BUILDER_DIR / "mac-mini-dashboard" / "index.html").read_text(encoding="utf-8")
        # Mark (2026-10-14): «Нам не нужна сводка дня … сделай, чтобы это было красиво, унифицировано по
        # дизайну». MAIN MANAGER is the first screen; old «По дням» links (?tab=today) open it.
        self.assertIn('<section id="section-work" class="section active" aria-labelledby="mm-title">', html)
        self.assertIn("const INITIAL_SECTION = INITIAL_TAB === 'today' ? 'work' : INITIAL_TAB;", html)
        self.assertIn("  showSection('work');\n}", html)
        # One app shell: the only primary navigation sits in the sidebar, the sections in the page.
        primary_nav = '<nav class="nav-pills cc-main-nav" aria-label="Command Center sections">'
        self.assertEqual(html.count(primary_nav), 1)
        self.assertLess(html.index('<aside class="cc-side"'), html.index(primary_nav))
        self.assertLess(html.index(primary_nav), html.index('<main class="cc-main">'))
        self.assertLess(html.index('<main class="cc-main">'), html.index('<section id="section-work"'))
        # Every section opens with the same page header, and one switch sets light or dark for all.
        for title_id in ("mm-title", "agents-title", "platforms-title", "machines-title"):
            self.assertRegex(html, rf'<h2 class="cc-page-title[^"]*" id="{title_id}">')
        self.assertIn('id="cc-theme-toggle"', html)
        self.assertNotIn('id="mm-theme-toggle"', html)
        # The board (Mark 2026-10-26: «пересобери его полностью»): one grid of tiles. Main projects are
        # tiles, other folders open in a window, and the Claude Code / Codex split lives in «Сводка».
        self.assertIn("function renderMap(data)", html)
        self.assertIn("const main = projects.filter(p => p.main);", html)
        self.assertIn('id="mm-others-dialog"', html)
        self.assertNotIn("MM_MAP_AGENT_KEY", html)
        self.assertNotIn("mmSpark", html)
        self.assertIn("Карточки проектов видны только владельцу.", html)
        # A link with ?day= opens that day in the project's history, details unfolded.
        self.assertIn("if (day) mmOpenHistoryDay(day);", html)
        self.assertNotIn("через mm-command-center-auth", html)  # plain words, not a helper's name
        for gone in ("renderPaper", "np-articles", "Остальные проекты", "function renderDays()", "dpDay(", "loadDays"):
            self.assertNotIn(gone, html)

    def test_about_window_opens_closes_and_hides_the_qr(self):
        # Mark 2026-10-26: sources and the phone QR live behind «i»; run the real handlers on a small DOM.
        html = (BUILDER_DIR / "mac-mini-dashboard" / "index.html").read_text(encoding="utf-8")
        def source(name):
            start = html.index(f"function {name}(")
            return html[start:html.index("\n}\n", start) + 3]
        script = r"""
class El { constructor(id){ this.id=id; this.hidden=false; this.innerHTML=''; this.open=false; this.l={}; }
  addEventListener(t,f){ (this.l[t]=this.l[t]||[]).push(f); } fire(t){ (this.l[t]||[]).forEach(f=>f({})); }
  showModal(){ this.open=true; } close(){ if(!this.open) return; this.open=false; this.fire('close'); } }
const els={}; const document={ getElementById:id=>els[id]||(els[id]=new El(id)) };
let npQrTimer=null;
""" + source("npHideQr") + source("mmInitAbout") + r"""
const $=id=>document.getElementById(id);
mmInitAbout();
const about=$('mm-about-dialog');
$('mm-about-open').fire('click');
if(!about.open) throw new Error('«i» did not open the window');
$('np-qr').innerHTML='<svg>qr</svg>'; $('np-device-qr').hidden=false; $('np-device-show').hidden=true;
$('mm-about-close').fire('click');
if(about.open) throw new Error('✕ did not close the window');
if($('np-qr').innerHTML!=='' || !$('np-device-qr').hidden || $('np-device-show').hidden) throw new Error('QR stayed after closing');
$('mm-about-open').fire('click'); $('np-qr').innerHTML='<svg>qr</svg>';
about.close();  // Escape closes a modal dialog the same way
if($('np-qr').innerHTML!=='') throw new Error('QR stayed after Escape');
"""
        node = shutil.which("node")
        if not node:
            self.skipTest("Node runtime is required")
        run = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=15)
        self.assertEqual(run.returncode, 0, run.stderr)
        # The «i» is a real button wired to the modal, so it works from the keyboard and by touch.
        self.assertIn('<button type="button" class="cc-i" id="mm-about-open" aria-haspopup="dialog" aria-controls="mm-about-dialog"', html)

    def test_owner_browser_can_open_the_phone_by_qr(self):
        html = (BUILDER_DIR / "mac-mini-dashboard" / "index.html").read_text(encoding="utf-8")
        self.assertIn('<section class="np-device" id="np-device" aria-labelledby="np-device-title" hidden>', html)
        # Shown only to a browser on command.meshly.fr that already holds the owner key.
        self.assertIn("ownerView && IS_PUBLIC_DASHBOARD && npOwnerKey() && typeof ccQrcode === 'function'", html)
        self.assertIn("npDeviceSetup(false);", html)
        # The code is the usual login link the page already accepts; it hides itself again.
        self.assertIn("`${window.location.origin}/#dashboard_run_token=${encodeURIComponent(key)}`", html)
        self.assertIn("params.get('dashboard_run_token')", html)
        self.assertIn("npQrTimer = setTimeout(npHideQr, 120000);", html)
        self.assertIn("if (document.hidden) npHideQr();", html)
        # The QR library is inline (only index.html is deployed) and carries its licence notice.
        self.assertIn("qrcode-generator 2.0.4, Copyright (c) 2009 Kazuhiko Arase", html)
        self.assertIn("const ccQrcode=", html)
        # Mark 2026-10-24: no service or hook counters anywhere, neither in the header nor in «Техника».
        self.assertNotIn('id="stat-services"', html)
        self.assertNotIn('id="stat-hooks"', html)


if __name__ == "__main__":
    unittest.main()
