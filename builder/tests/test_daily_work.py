from __future__ import annotations

from datetime import datetime, timedelta, timezone
import importlib.util
import json
import os
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
        self.assertEqual(hub["topics"], ["private topic"])  # no summary yet: what the sessions were about
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
        self.assertEqual(projects["jarvis"]["topics"], [])  # Claude's words replace the session titles
        self.assertEqual(projects["command-center"]["bullets"], ["Итоги дня на сайте"])
        self.assertEqual(days["2026-10-05"]["projects"][0]["bullets"], ["Начали голосовой режим"])
        self.assertIsNone(days["2026-10-07"]["headline"])
        self.assertEqual(payload["deadlines"], [
            {"date": "2026-10-20", "what": "Показать друзьям", "project_id": "command-center", "project": "Command Center"},
            {"date": "2026-10-20", "what": "Показать друзьям", "project_id": "jarvis", "project": "JARVIS"},
            {"date": "2026-11-07", "what": "Продлить проверку цен", "project_id": "jarvis", "project": "JARVIS"},
        ])  # past ones dropped, every summary in the window counts, same words in two projects kept apart

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
        self.assertIsNone(other["description"])
        self.assertEqual(product_for(None, "pirajoke/ai-singularity-news-bot")["id"], "context-news")
        self.assertEqual(product_for("ai-singularity", None)["id"], "ai-singularity")
        self.assertEqual(product_for("urssaf-helper", None)["id"], "accountable")
        self.assertTrue(product_for("lexi", None)["description"])

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


class CommandCenterWorkSectionTest(unittest.TestCase):
    def test_dashboard_has_work_section_and_nav(self):
        html = (BUILDER_DIR / "mac-mini-dashboard" / "index.html").read_text(encoding="utf-8")
        self.assertIn('aria-controls="section-work"', html)
        self.assertIn('id="section-work"', html)
        self.assertIn("/api/work/daily", html)
        self.assertIn("'work'].includes(INITIAL_SECTION)", html)
        # Projects reuse the Platforms mascots and open a per-project page.
        self.assertIn('data-mm-view="projects"', html)
        self.assertIn('<use href="#cc-mascot-${mmEsc(item.mascot)}"/>', html)
        self.assertIn("project: id", html)
        # The plain-language day summary lives only in «По дням», not again in MAIN MANAGER.
        self.assertIn('id="dp-days"', html)
        self.assertNotIn('data-mm-view="overview"', html)
        self.assertNotIn('id="mm-day-summary"', html)
        self.assertIn("mm-project-desc", html)
        self.assertIn("Технические детали", html)

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

    def test_dashboard_opens_on_the_days(self):
        html = (BUILDER_DIR / "mac-mini-dashboard" / "index.html").read_text(encoding="utf-8")
        # Mark (2026-10-11): «По дням» is the first thing he sees, in the MAIN MANAGER rows he liked.
        self.assertIn('<div id="section-today" class="section active" lang="ru">', html)
        self.assertIn('<div class="mm-os dp" id="dp-os" role="region" aria-labelledby="dp-title">', html)
        self.assertIn('<h2 class="dp-title" id="dp-title">По дням</h2>', html)
        self.assertIn("new URLSearchParams({ days: '30', edition: '1' })", html)
        self.assertIn("function renderDays()", html)
        self.assertIn("data.feed.map((day, index) => dpDay(day, index, data))", html)
        self.assertIn("index < DP_OPEN_DAYS", html)
        self.assertIn("<summary>Технические детали", html)
        # «По дням» stays inside the same top-level shell instead of replacing it
        # with a second, differently styled navigation row.
        primary_nav = '<nav class="nav-pills cc-main-nav" aria-label="Command Center sections">'
        self.assertEqual(html.count(primary_nav), 1)
        self.assertLess(html.index(primary_nav), html.index('<div id="section-today"'))
        today = html[
            html.index('<div id="section-today"') : html.index(
                '<section id="section-platforms"'
            )
        ]
        obsolete_replacements = []
        if '<nav class="dp-more" aria-label="Другие разделы">' in today:
            obsolete_replacements.append("the dp-more replacement navigation")
        if ".container:has(> #section-today.active) > .cc-main-nav { display: none; }" in html:
            obsolete_replacements.append("the CSS rule that hides the primary navigation")
        self.assertEqual(
            obsolete_replacements,
            [],
            "the shared primary navigation must remain visible on «По дням»",
        )
        # A project's technical line opens that day on its project page, details unfolded.
        self.assertIn("openProject(link.dataset.project, link.dataset.day || null)", html)
        self.assertIn("if (day) mmRevealDay(day);", html)
        # The project page starts with «По дням»; numbers, the to-do and the chart are folded below it.
        page = html[html.index("function renderProjectPage()"):html.index("function mmRevealDay(")]
        self.assertLess(page.index("<h3>По дням"), page.index('<details class="mm-panel mm-project-more"'))
        self.assertLess(page.index('<details class="mm-panel mm-project-more"'), page.index("${mmTodo(p)}"))
        self.assertIn("if (event.target.open) renderProjectChart();", page)
        # Without the owner token the page shows only the day's numbers.
        self.assertIn("if (!data.owner_view || !data.feed)", html)
        self.assertIn("Итоги по дням видит только владелец", html)
        self.assertNotIn("через mm-command-center-auth", html)  # plain words, not a helper's name
        for gone in ("renderPaper", "np-articles", "Остальные проекты"):
            self.assertNotIn(gone, html)

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
        # Service counters moved from the header into «Техника».
        header = html[html.index('<div class="header">'):html.index('<nav class="nav-pills cc-main-nav"')]
        self.assertNotIn('id="stat-services"', header)
        machines = html[html.index('<section id="section-machines"'):html.index('<nav class="nav-pills cc-machine-nav"')]
        self.assertIn('id="stat-services"', machines)
        self.assertIn('id="stat-hooks"', machines)


if __name__ == "__main__":
    unittest.main()
