from __future__ import annotations

from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


BUILDER_DIR = Path(__file__).resolve().parents[1]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


INFRA = _load("infra_change_collector", BUILDER_DIR / "infra_change_collector.py")
WORK = _load("daily_work_collector_for_infra", BUILDER_DIR / "daily_work_collector.py")
from dashboard_builder.infra_changes import infra_projection  # noqa: E402


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class AgentCommandFilterTest(unittest.TestCase):
    MOMENT = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)

    def test_changing_commands_are_logged(self):
        for command in (
            "launchctl bootout gui/501/com.pirajoke.bridge-tunnel",
            "cd ~/agent-dashboard && git pull origin main && builder/deploy_to_scripts.sh",
            "docker compose up -d lexi-bot",
            "brew services restart postgresql@17",
            "mv ~/Library/LaunchAgents/com.x.plist ~/Library/LaunchAgents/com.x.plist.disabled",
            "gh pr merge 49 --squash",
        ):
            with self.subTest(command=command):
                self.assertIsNotNone(WORK.infra_action(command, self.MOMENT))

    def test_read_only_commands_are_ignored(self):
        for command in (
            "launchctl list | grep pirajoke",
            "docker ps -a",
            "cat builder/deploy_to_scripts.sh",
            "git status --short",
            "grep -n 'launchctl bootstrap' README.md",
            "cat > notes.md <<'EOF'\nlaunchctl bootstrap gui/501 x.plist\nEOF",
        ):
            with self.subTest(command=command):
                self.assertIsNone(WORK.infra_action(command, self.MOMENT))

    def test_ssh_records_the_remote_host_and_redacts_secrets(self):
        action = WORK.infra_action(
            "ssh ovh-main-manager 'cd /srv/main-manager && docker compose up -d && echo token=ghp_abcdefghijklmnopqrstuvwxyz0123'",
            self.MOMENT,
        )
        self.assertEqual(action["host"], "ovh-main-manager")
        self.assertNotIn("ghp_", action["command"])
        self.assertIsNone(WORK.infra_action("ssh maxxs-mac-mini 'uptime'", self.MOMENT))

    def test_claude_session_title_and_commands_reach_day_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "s1.jsonl"
            t0 = datetime(2026, 10, 9, 10, 0, tzinfo=timezone.utc)
            records = [
                {"type": "ai-title", "aiTitle": "Deploy Daily Work to Mac mini"},
                {"type": "user", "sessionId": "s1", "timestamp": _iso(t0), "cwd": "/nonexistent/agent-dashboard",
                 "message": {"role": "user", "content": "go"}},
                {"type": "assistant", "sessionId": "s1", "timestamp": _iso(t0 + timedelta(minutes=2)),
                 "message": {"role": "assistant", "content": [
                     {"type": "tool_use", "name": "Bash", "input": {"command": "ssh maxxs-mac-mini 'launchctl kickstart -k gui/501/com.pirajoke.dashboard'"}},
                     {"type": "tool_use", "name": "Bash", "input": {"command": "ls ~/scripts"}},
                 ]}},
            ]
            path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
            sessions = WORK.parse_claude_file(path)
        day = WORK.day_records(sessions, {t0.astimezone().date().isoformat()})
        record = next(iter(day.values()))[0]
        self.assertEqual(record["topic"], "Deploy Daily Work to Mac mini")
        self.assertEqual(len(record["infra_actions"]), 1)
        self.assertEqual(record["infra_actions"][0]["host"], "maxxs-mac-mini")


class SnapshotDiffTest(unittest.TestCase):
    def test_diff_reports_service_container_port_and_file_changes(self):
        prev = {
            "launchd_files": {"com.a.plist": "1", "com.old.plist": "2"},
            "launchd_jobs": {"com.a": {"running": True, "pid": "10", "exit": "0"}},
            "docker": {"lexi-bot": {"image": "lexi:1", "state": "running", "id": "aaa"}},
            "brew": {"postgresql@17": "started"},
            "ports": {"7777": {"process": "Python", "scope": "network"}},
            "repos": None,
            "runtime_files": {"scripts/a.py": "1"},
            "tunnel_files": {".cloudflared/config.yml": "1"},
            "crontab": {"entries": 1, "hash": "x"},
        }
        cur = {
            "launchd_files": {"com.a.plist": "9", "com.new.plist": "3"},
            "launchd_jobs": {"com.a": {"running": True, "pid": "11", "exit": "0"}},
            "docker": {"lexi-bot": {"image": "lexi:2", "state": "running", "id": "bbb"}},
            "brew": {"postgresql@17": "stopped"},
            "ports": {"8791": {"process": "node", "scope": "local"}},
            "repos": {"agent-dashboard": {"head": "abc", "branch": "main"}},
            "runtime_files": {"scripts/a.py": "2", "scripts/b.sh": "1"},
            "tunnel_files": {".cloudflared/config.yml": "1"},
            "crontab": {"entries": 2, "hash": "y"},
        }
        events = INFRA.diff(prev, cur)
        pairs = {(e["category"], e["action"], e["subject"]) for e in events}
        self.assertIn(("launchd", "changed", "com.a.plist"), pairs)
        self.assertIn(("launchd", "added", "com.new.plist"), pairs)
        self.assertIn(("launchd", "removed", "com.old.plist"), pairs)
        self.assertIn(("launchd", "restarted", "com.a"), pairs)
        self.assertIn(("docker", "changed", "lexi-bot"), pairs)
        self.assertIn(("brew", "changed", "postgresql@17"), pairs)
        self.assertIn(("port", "opened", "8791"), pairs)
        self.assertIn(("port", "closed", "7777"), pairs)
        self.assertIn(("cron", "changed", "crontab"), pairs)
        runtime = next(e for e in events if e["category"] == "runtime")
        self.assertEqual(sorted(runtime["files"]), ["scripts/a.py", "scripts/b.sh"])
        # A part that failed to collect last time is skipped, not reported as all-new.
        self.assertFalse(any(e["category"] == "repo" for e in events))
        self.assertFalse(any(e["category"] == "tunnel" for e in events))

    def test_periodic_launchd_runs_are_not_changes(self):
        prev = {"launchd_jobs": {"com.pull": {"running": False, "pid": None, "exit": "0"},
                                 "com.pub": {"running": True, "pid": "40", "exit": "0"},
                                 "com.bot": {"running": False, "pid": None, "exit": "0"}}}
        cur = {"launchd_jobs": {"com.pull": {"running": True, "pid": "41", "exit": "0"},
                                "com.pub": {"running": False, "pid": None, "exit": "0"},
                                "com.bot": {"running": False, "pid": None, "exit": "78"}}}
        events = INFRA.diff(prev, cur)
        self.assertEqual([(e["action"], e["subject"]) for e in events], [("failed", "com.bot")])
        back = INFRA.diff(cur, {"launchd_jobs": {**cur["launchd_jobs"], "com.bot": {"running": False, "pid": None, "exit": "0"}}})
        self.assertEqual([(e["action"], e["subject"]) for e in back], [("recovered", "com.bot")])

    def test_identical_snapshots_produce_no_events(self):
        snap = {"launchd_files": {"a": "1"}, "docker": {}, "ports": {"22": {"process": "sshd", "scope": "network"}}}
        self.assertEqual(INFRA.diff(snap, snap), [])

    def test_first_run_writes_baseline_and_private_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            original = INFRA.snapshot
            INFRA.snapshot = lambda: {"launchd_files": {}, "docker": None}
            try:
                INFRA.main(["--out", str(out), "--machine", "mac-mini"])
                INFRA.main(["--out", str(out), "--machine", "mac-mini"])
            finally:
                INFRA.snapshot = original
            state = json.loads((out / "mac-mini" / "state.json").read_text())
            events = [json.loads(line) for path in (out / "mac-mini").glob("events-*.jsonl") for line in path.read_text().splitlines()]
            mode = (out / "mac-mini" / "state.json").stat().st_mode & 0o777
        self.assertEqual(state["unavailable"], ["docker"])
        self.assertEqual([e["category"] for e in events], ["baseline"])
        self.assertEqual(mode, 0o600)


class InfraProjectionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.infra = base / "infra-changes"
        self.work = base / "daily-work"
        self.now = datetime(2026, 10, 9, 18, 0, tzinfo=timezone.utc)
        machine = self.infra / "mac-mini"
        machine.mkdir(parents=True)
        (machine / "state.json").write_text(json.dumps({
            "machine": "mac-mini", "collected_at": _iso(self.now - timedelta(minutes=5)), "unavailable": []}))
        (machine / "events-2026-10.jsonl").write_text("\n".join(json.dumps(e) for e in [
            {"at": _iso(self.now - timedelta(hours=2)), "machine": "mac-mini", "category": "launchd",
             "action": "loaded", "subject": "com.pirajoke.private-job", "detail": "задача загружена в launchd"},
            {"at": _iso(self.now - timedelta(days=30)), "machine": "mac-mini", "category": "docker",
             "action": "removed", "subject": "too-old", "detail": "контейнер удалён"},
        ]) + "\n")
        sessions = self.work / "sessions" / "macbook-pro"
        sessions.mkdir(parents=True)
        (sessions / "2026-10-09.json").write_text(json.dumps({"machine": "macbook-pro", "sessions": [{
            "tool": "claude", "project": "agent-dashboard", "topic": "private topic",
            "infra_actions": [{"at": _iso(self.now - timedelta(hours=1)), "command": "ssh maxxs-mac-mini 'builder/deploy_to_scripts.sh'",
                               "host": "maxxs-mac-mini"}]}]}))
        (self.work / "github.json").write_text(json.dumps({"ok": True, "prs": [
            {"repo": "pirajoke/agent-dashboard", "number": 49, "title": "Private PR title",
             "url": "https://github.com/pirajoke/agent-dashboard/pull/49", "merged_at": _iso(self.now - timedelta(hours=3))}]}))

    def tearDown(self):
        self.tmp.cleanup()

    def test_owner_timeline_merges_all_sources(self):
        payload = infra_projection(self.infra, self.work, now=self.now, owner=True)
        self.assertEqual(payload["state"], "live")
        self.assertEqual(payload["total"], 3)
        events = [e for day in payload["timeline"] for e in day["events"]]
        self.assertEqual([e["category"] for e in events], ["agent", "launchd", "pr"])
        self.assertEqual(events[0]["subject"], "Claude · agent-dashboard")
        self.assertEqual(events[0]["host"], "maxxs-mac-mini")
        counts = {c["id"]: c["count"] for c in payload["categories"]}
        self.assertEqual(counts["docker"], 0)

    def test_public_payload_has_counts_only(self):
        payload = infra_projection(self.infra, self.work, now=self.now, owner=False)
        text = json.dumps(payload, ensure_ascii=False)
        for private in ("private-job", "private topic", "Private PR title", "deploy_to_scripts", "mac-mini", "macbook"):
            self.assertNotIn(private, text)
        self.assertNotIn("timeline", payload)
        self.assertEqual(payload["total"], 3)

    def test_missing_and_stale_collection(self):
        with tempfile.TemporaryDirectory() as tmp:
            empty = infra_projection(Path(tmp) / "none", Path(tmp) / "none", now=self.now, owner=True)
        self.assertEqual(empty["state"], "empty")
        stale = infra_projection(self.infra, self.work, now=self.now + timedelta(hours=2), owner=True)
        self.assertEqual(stale["state"], "stale")


class CommandCenterMainManagerTest(unittest.TestCase):
    def test_section_is_scoped_and_wired(self):
        html = (BUILDER_DIR / "mac-mini-dashboard" / "index.html").read_text(encoding="utf-8")
        self.assertIn('class="mm-os" id="mm-os"', html)
        self.assertIn("/api/infra/changes", html)
        self.assertIn("if (name === 'work') setTimeout(openMainManager, 0);", html)
        # Property OS tokens live on .mm-os only, never on :root or body.
        self.assertNotIn(":root { --mm-", html)
        self.assertIn(".mm-os {\n  color-scheme: light;\n  --mm-background: #f8f3ea;", html)

    def test_server_exposes_infra_endpoint(self):
        server = (BUILDER_DIR / "dashboard-server-m4.py").read_text(encoding="utf-8")
        self.assertIn('"/api/infra/changes"', server)
        self.assertIn("infra_projection(", server)


if __name__ == "__main__":
    unittest.main()
