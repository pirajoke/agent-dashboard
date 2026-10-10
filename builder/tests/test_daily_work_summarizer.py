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


SUMMARIZER = _load("daily_work_summarizer", BUILDER_DIR / "daily_work_summarizer.py")

# Stands in for `claude -p`: logs each call and answers with one bullet per
# project it was given, wrapped in a code fence like a chatty model would.
FAKE_CLAUDE = '''#!/usr/bin/env python3
import json, os, sys
args, text = sys.argv[1:], sys.stdin.read()
with open(os.environ["FAKE_CLAUDE_LOG"], "a", encoding="utf-8") as log:
    log.write(json.dumps({"args": args, "cwd": os.getcwd(), "stdin": text,
                          "token": os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"),
                          "scrub": os.environ.get("CLAUDE_CODE_SUBPROCESS_ENV_SCRUB")}, ensure_ascii=False) + "\\n")
mode = os.environ.get("FAKE_CLAUDE_MODE", "ok")
if mode == "old" and "--no-session-persistence" in args:
    sys.stderr.write("error: unknown option '--no-session-persistence'\\n")
    sys.exit(1)
if mode == "ancient" and "--tools" in args:
    sys.stderr.write("error: unknown option '--tools'\\n")
    sys.exit(1)
if mode == "leak":
    sys.stderr.write('TypeError: Invalid header value "Bearer ' + os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "") + '"\\n')
    sys.exit(1)
if mode == "auth":
    print(json.dumps({"type": "result", "is_error": True, "result": "Failed to authenticate. API Error: 401"}))
    sys.exit(1)
if mode == "error":
    print(json.dumps({"type": "result", "is_error": True, "result": "Overloaded, try again later"}))
    sys.exit(0)
body = text[text.index("Активность за"):]
products = json.loads(body[body.index("["):body.rindex("]") + 1])
if mode == "partial" or (mode == "partial-once" and "В прошлом ответе" not in text):
    products = products[:1]
answer = {"day": "Главное: стало удобнее", "projects": {p["id"]: [p["name"] + ": стало удобнее"] for p in products}}
print(json.dumps({"type": "result", "is_error": False,
                  "result": "```json\\n" + json.dumps(answer, ensure_ascii=False) + "\\n```"}))
'''


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class SummarizerTest(unittest.TestCase):
    def setUp(self):
        os.environ["TZ"] = "UTC"
        time.tzset()
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "daily-work"
        today = datetime.now(timezone.utc).date()
        self.yesterday = (today - timedelta(days=1)).isoformat()
        self.before = (today - timedelta(days=2)).isoformat()
        self._write_day(self.yesterday, [
            self._session("agent-dashboard", "pirajoke/agent-dashboard", self.yesterday, 9, 40,
                          asks=["Добавь итоги дня"], outcome="Итоги дня готовы"),
            self._session("jarvis", "pirajoke/jarvis", self.yesterday, 12, 20),
        ])
        self._write_day(self.before, [self._session("lexi", "pirajoke/lexi", self.before, 10, 30)])
        github = {"ok": True, "collected_at": _iso(datetime.now(timezone.utc)), "prs": [
            {"repo": "pirajoke/agent-dashboard", "number": 51, "title": "Day summaries", "body": "Adds summaries",
             "url": "https://github.com/pirajoke/agent-dashboard/pull/51", "state": "closed",
             "created_at": f"{self.yesterday}T10:00:00Z", "updated_at": f"{self.yesterday}T11:00:00Z",
             "closed_at": f"{self.yesterday}T11:00:00Z", "merged_at": f"{self.yesterday}T11:00:00Z"},
        ], "commits": [], "open_issues": []}
        (self.root / "github.json").write_text(json.dumps(github), encoding="utf-8")
        self.cli = Path(self.tmp.name) / "bin" / "claude"
        self.cli.parent.mkdir()
        self.cli.write_text(FAKE_CLAUDE, encoding="utf-8")
        self.cli.chmod(0o755)
        self.log = Path(self.tmp.name) / "calls.jsonl"
        self.env = patch.dict(os.environ, {"FAKE_CLAUDE_LOG": str(self.log), "FAKE_CLAUDE_MODE": "ok"})
        self.env.start()
        os.environ.pop("CLAUDE_CODE_OAUTH_TOKEN", None)
        self.token_file = Path(self.tmp.name) / "claude_oauth_token"
        self.token = patch.object(SUMMARIZER, "TOKEN_FILE", self.token_file)
        self.token.start()

    def tearDown(self):
        self.token.stop()
        self.env.stop()
        self.tmp.cleanup()

    @staticmethod
    def _session(project, repo, day, hour, minutes, asks=None, outcome=None):
        start = datetime.fromisoformat(f"{day}T{hour:02d}:00:00+00:00")
        end = start + timedelta(minutes=minutes)
        return {"tool": "claude", "session_id": f"{project}-{day}", "project": project, "repo": repo, "branch": "main",
                "start": _iso(start), "end": _iso(end), "active_minutes": minutes, "prompts": 2, "topic": f"{project} work",
                "intervals": [[_iso(start), _iso(end)]], "asks": asks or [], "outcome": outcome}

    def _write_day(self, day, sessions):
        path = self.root / "sessions" / "mac-mini" / f"{day}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"schema": 2, "date": day, "machine": "mac-mini",
                                    "collected_at": _iso(datetime.now(timezone.utc)), "sessions": sessions}), encoding="utf-8")

    def _calls(self):
        if not self.log.exists():
            return []
        return [json.loads(line) for line in self.log.read_text(encoding="utf-8").splitlines()]

    def _run(self, *extra):
        with patch("sys.stdout"):
            return SUMMARIZER.main(["--out", str(self.root), "--claude", str(self.cli), "--days", "3", *extra])

    def _summary(self, day):
        return json.loads((self.root / "summaries" / f"{day}.json").read_text(encoding="utf-8"))

    def _status(self):
        return json.loads((self.root / "summaries" / "status.json").read_text(encoding="utf-8"))

    def test_day_inputs_group_real_activity_by_product(self):
        inputs = SUMMARIZER.day_inputs(self.root, [self.before, self.yesterday])
        self.assertEqual(set(inputs), {self.before, self.yesterday})
        products = {p["id"]: p for p in inputs[self.yesterday]}
        self.assertEqual([p["id"] for p in inputs[self.yesterday]], ["command-center", "jarvis"])  # busiest first
        hub = products["command-center"]
        self.assertEqual(hub["minutes"], 40)
        self.assertTrue(hub["about"])
        self.assertEqual(hub["sessions"][0]["asks"], ["Добавь итоги дня"])
        self.assertEqual(hub["sessions"][0]["last_reply"], "Итоги дня готовы")
        self.assertEqual(hub["prs_merged"], [{"title": "Day summaries", "body": "Adds summaries"}])
        self.assertEqual(hub["prs_opened"], [])  # opened and merged the same day: listed once
        self.assertNotIn("asks", products["jarvis"]["sessions"][0])
        prompt = SUMMARIZER.user_prompt(self.yesterday, inputs[self.yesterday])
        self.assertIn(f"Активность за {self.yesterday}", prompt)
        self.assertNotIn("prs_closed_without_merge", prompt)  # empty lists are left out

    def test_parse_summary_keeps_known_projects_and_caps_bullets(self):
        text = 'Вот итог:\n```json\n' + json.dumps({"day": "  Главное  ", "projects": {
            "jarvis": ["  один  ", "", 5, "два", "три", "четыре", "пять"], "made-up": ["x"], "lexi": "not a list"}},
            ensure_ascii=False) + "\n```"
        summary = SUMMARIZER.parse_summary(text, {"jarvis", "lexi"})
        self.assertEqual(summary, {"day": "Главное", "projects": {"jarvis": ["один", "два", "три", "четыре"]}})
        with self.assertRaises(ValueError):
            SUMMARIZER.parse_summary('{"projects": {"made-up": ["x"]}}', {"jarvis"})
        with self.assertRaises(ValueError):
            SUMMARIZER.parse_summary("Не могу ответить", {"jarvis"})

    def test_runs_summarize_newest_days_first_and_only_once(self):
        self.assertEqual(self._run("--max-days", "1"), 0)
        self.assertEqual(self._status()["written"], [self.yesterday])
        self.assertEqual(self._status()["pending"], 1)
        summary = self._summary(self.yesterday)
        self.assertEqual(summary["day"], "Главное: стало удобнее")
        self.assertEqual(summary["projects"], {"command-center": ["Command Center: стало удобнее"],
                                               "jarvis": ["JARVIS: стало удобнее"]})
        call = self._calls()[0]
        self.assertEqual(Path(call["cwd"]).resolve(), (self.root / "summarizer").resolve())
        self.assertIn("--system-prompt", call["args"])
        self.assertEqual(call["args"][call["args"].index("--tools") + 1], "")
        self.assertIn("Итоги дня готовы", call["stdin"])

        self.assertEqual(self._run("--max-days", "1"), 0)
        self.assertEqual(self._status()["written"], [self.before])
        self.assertEqual(self._status()["pending"], 0)
        self.assertEqual(self._run(), 0)
        self.assertEqual(self._status()["written"], [])
        self.assertEqual(len(self._calls()), 2)

        # New activity on a summarized day brings it back; --day forces a rerun.
        self._write_day(self.before, [self._session("lexi", "pirajoke/lexi", self.before, 10, 30),
                                      self._session("health-os", "pirajoke/health-os", self.before, 15, 10)])
        self.assertEqual(self._run(), 0)
        self.assertEqual(self._status()["written"], [self.before])
        self.assertIn("health", self._summary(self.before)["projects"])
        self.assertEqual(self._run("--day", self.yesterday), 0)
        self.assertEqual(self._status()["written"], [self.yesterday])
        self.assertEqual(len(self._calls()), 4)

    def test_projects_left_out_are_asked_again(self):
        os.environ["FAKE_CLAUDE_MODE"] = "partial-once"
        self.assertEqual(self._run("--max-days", "1"), 0)
        self.assertEqual(len(self._calls()), 2)
        self.assertIn("В прошлом ответе не было проектов: jarvis", self._calls()[1]["stdin"])
        summary = self._summary(self.yesterday)
        self.assertEqual(set(summary["projects"]), {"command-center", "jarvis"})
        self.assertEqual(summary["missing"], [])

    def test_projects_still_left_out_are_listed_not_retried_forever(self):
        os.environ["FAKE_CLAUDE_MODE"] = "partial"
        self.assertEqual(self._run("--max-days", "1"), 0)
        summary = self._summary(self.yesterday)
        self.assertEqual(set(summary["projects"]), {"command-center"})
        self.assertEqual(summary["missing"], ["jarvis"])
        calls = len(self._calls())
        self.assertEqual(self._run("--max-days", "1"), 0)
        self.assertEqual(self._status()["written"], [self.before])  # yesterday is done for this input
        self.assertEqual(len(self._calls()), calls + 1)  # the older day has one project: no retry

    def test_older_cli_without_new_flags_still_works(self):
        os.environ["FAKE_CLAUDE_MODE"] = "old"
        self.assertEqual(self._run("--max-days", "1"), 0)
        calls = self._calls()
        self.assertEqual(len(calls), 2)
        self.assertNotIn("--system-prompt", calls[1]["args"])
        self.assertTrue(calls[1]["stdin"].startswith(SUMMARIZER.SYSTEM_PROMPT[:40]))
        for call in calls:  # the retry keeps tools and MCP servers switched off
            self.assertEqual(call["args"][call["args"].index("--tools") + 1], "")
            self.assertIn("--strict-mcp-config", call["args"])
        self.assertIn("command-center", self._summary(self.yesterday)["projects"])

    def test_cli_too_old_to_switch_tools_off_is_never_run_with_tools(self):
        os.environ["FAKE_CLAUDE_MODE"] = "ancient"
        self.assertEqual(self._run(), 1)
        self.assertTrue(self._status()["reason"].startswith("claude_too_old: error: unknown option '--tools'"))
        calls = self._calls()
        self.assertEqual(len(calls), 2)
        self.assertTrue(all("--tools" in call["args"] for call in calls))

    def test_claude_errors_are_reported_in_status(self):
        os.environ["FAKE_CLAUDE_MODE"] = "error"
        self.assertEqual(self._run(), 1)
        status = self._status()
        self.assertFalse(status["ok"])
        self.assertEqual(status["reason"], "claude_error: Overloaded, try again later")
        self.assertEqual(status["written"], [])
        self.assertEqual(status["pending"], 2)
        self.assertEqual(len(self._calls()), 1)  # stops at the first failure
        self.assertFalse((self.root / "summaries" / f"{self.yesterday}.json").exists())

    def test_saved_token_is_passed_to_the_cli(self):
        self.assertEqual(self._run("--max-days", "1"), 0)
        self.assertIsNone(self._calls()[0]["token"])  # no token file: the CLI uses its own sign-in
        self.token_file.write_text("sk-ant-oat01-test\n", encoding="utf-8")
        self.assertEqual(self._run("--max-days", "1"), 0)
        self.assertEqual(self._calls()[-1]["token"], "sk-ant-oat01-test")
        self.assertEqual(self._calls()[-1]["scrub"], "1")  # hooks and other subprocesses don't get it
        self.assertNotIn("sk-ant-oat01-test", json.dumps(self._status()))

    def test_token_pasted_with_line_breaks_is_joined(self):
        self.token_file.write_text("sk-ant-oat01-" + "A" * 40 + "\n  " + "B" * 40 + " \n" + "C" * 9 + "\n", encoding="utf-8")
        self.assertEqual(self._run("--max-days", "1"), 0)
        self.assertEqual(self._calls()[-1]["token"], "sk-ant-oat01-" + "A" * 40 + "B" * 40 + "C" * 9)

    def test_token_never_reaches_status_or_log(self):
        os.environ["FAKE_CLAUDE_MODE"] = "leak"
        self.token_file.write_text("sk-ant-oat01-" + "A" * 40 + "\n" + "B" * 40 + "\n", encoding="utf-8")
        with patch("sys.stdout") as stdout:
            self.assertEqual(SUMMARIZER.main(["--out", str(self.root), "--claude", str(self.cli), "--days", "3"]), 1)
        printed = "".join(str(call.args[0]) for call in stdout.write.call_args_list if call.args)
        reason = self._status()["reason"]
        self.assertTrue(reason.startswith("claude_failed: TypeError: Invalid header value"))
        for text in (reason, printed, (self.root / "summaries" / "status.json").read_text(encoding="utf-8")):
            self.assertNotIn("A" * 40, text)
            self.assertNotIn("B" * 40, text)
            self.assertNotIn("sk-ant-", text)

    def test_redact_hides_a_token_split_across_lines(self):
        self.token_file.write_text("sk-ant-oat01-" + "A" * 30 + "\n" + "B" * 30 + "\n" + "C" * 6, encoding="utf-8")
        text = SUMMARIZER.redact("bad header: Bearer sk-ant-oat01-" + "A" * 30 + " " + "B" * 30 + " " + "C" * 6 + " end")
        self.assertEqual(text, "bad header: [token] [token] [token] end")
        self.assertEqual(SUMMARIZER.redact("Not logged in · Please run /login"), "Not logged in · Please run /login")

    def test_failed_sign_in_is_named_in_status(self):
        os.environ["FAKE_CLAUDE_MODE"] = "auth"
        self.assertEqual(self._run(), 1)
        status = self._status()
        self.assertTrue(status["reason"].startswith("claude_auth_failed: Failed to authenticate"))
        self.assertEqual(len(self._calls()), 1)  # no retry with older flags for a sign-in problem

    def test_missing_cli_is_reported(self):
        with patch.object(SUMMARIZER, "find_cli", return_value=None), patch("sys.stdout"):
            code = SUMMARIZER.main(["--out", str(self.root), "--days", "3"])
        self.assertEqual(code, 1)
        self.assertEqual(self._status()["reason"], "claude_not_found")

    def test_dry_run_calls_nothing(self):
        with patch("sys.stdout"):
            self.assertEqual(SUMMARIZER.main(["--out", str(self.root), "--claude", str(self.cli), "--days", "3", "--dry-run"]), 0)
        self.assertEqual(self._calls(), [])
        self.assertFalse((self.root / "summaries").exists())

    def test_no_activity_means_no_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("sys.stdout"):
                code = SUMMARIZER.main(["--out", tmp, "--claude", str(self.cli), "--days", "3"])
            status = json.loads((Path(tmp) / "summaries" / "status.json").read_text(encoding="utf-8"))
        self.assertEqual(code, 0)
        self.assertEqual((status["written"], status["pending"]), ([], 0))
        self.assertEqual(self._calls(), [])


if __name__ == "__main__":
    unittest.main()
