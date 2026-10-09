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

    def test_server_exposes_daily_work_endpoint(self):
        server = (BUILDER_DIR / "dashboard-server-m4.py").read_text(encoding="utf-8")
        self.assertIn('"/api/work/daily"', server)
        self.assertIn("owner=self._dashboard_run_authorized()", server)


if __name__ == "__main__":
    unittest.main()
