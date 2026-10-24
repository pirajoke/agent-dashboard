"""Agents take items off «Ждёт тебя» (Mark 2026-10-23, «Агент делает сам»)."""
from __future__ import annotations

import importlib.util
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import stat
import sys
import tempfile
import textwrap
import unittest

from dashboard_builder.owner_todo import (
    change_items, load_items, queued_items, set_triage, untriaged_items, update_agent)

BUILDER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BUILDER))
import agent_task_runner as RUNNER  # noqa: E402

spec = importlib.util.spec_from_file_location("dashboard_agent_tasks_test", BUILDER / "dashboard-server-m4.py")
SERVER = importlib.util.module_from_spec(spec)
spec.loader.exec_module(SERVER)
PAGE = (BUILDER / "mac-mini-dashboard" / "index.html").read_text()


class AgentStoreTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "owner-todo.json"

    def item(self, item_id):
        return next(item for item in load_items(self.path)["items"] if item["id"] == item_id)

    def test_mark_hands_an_item_over_and_takes_it_back(self):
        change_items(self.path, {"action": "assign", "id": "t-00000001"})
        self.assertEqual(self.item("t-00000001")["agent"]["state"], "queued")
        self.assertEqual([item["id"] for item in queued_items(self.path)], ["t-00000001"])
        change_items(self.path, {"action": "unassign", "id": "t-00000001"})
        item = self.item("t-00000001")
        self.assertNotIn("agent", item)
        # Taken back on purpose: the runner does not hand it straight back.
        self.assertNotIn("t-00000001", [entry["id"] for entry in untriaged_items(self.path)])

    def test_assign_refuses_unknown_agents_and_closed_items(self):
        with self.assertRaises(ValueError):
            change_items(self.path, {"action": "assign", "id": "t-00000001", "by": "someone"})
        change_items(self.path, {"action": "done", "id": "t-00000002"})
        with self.assertRaises(ValueError):
            change_items(self.path, {"action": "assign", "id": "t-00000002"})

    def test_agent_moves_only_forward_and_keeps_its_result(self):
        change_items(self.path, {"action": "assign", "id": "t-00000003"})
        update_agent(self.path, "t-00000003", "working", by="claude")
        with self.assertRaises(ValueError):
            update_agent(self.path, "t-00000003", "done", by="codex")  # Someone else's work.
        update_agent(self.path, "t-00000003", "done", by="claude", result="Открыл черновой PR.",
                     url="https://github.com/pirajoke/agent-dashboard/pull/1")
        agent = self.item("t-00000003")["agent"]
        self.assertEqual((agent["state"], agent["result"], agent["url"]),
                         ("done", "Открыл черновой PR.", "https://github.com/pirajoke/agent-dashboard/pull/1"))
        with self.assertRaises(ValueError):
            update_agent(self.path, "t-00000003", "working", by="claude")  # Finished stays finished.

    def test_agent_cannot_touch_items_mark_did_not_give(self):
        with self.assertRaises(ValueError):
            update_agent(self.path, "t-00000001", "working", by="claude")
        change_items(self.path, {"action": "assign", "id": "t-00000001"})
        for kwargs in ({"url": "javascript:alert(1)"}, {"url": "http://example.com/x"}):
            with self.assertRaises(ValueError):
                update_agent(self.path, "t-00000001", "done", by="claude", **kwargs)

    def test_triage_queues_what_an_agent_can_do_and_asks_again_after_an_edit(self):
        self.assertEqual(len(untriaged_items(self.path)), 4)
        set_triage(self.path, "t-00000001", False, "Нужно купить и поставить руками")
        record = change_items(self.path, {"action": "add", "text": "Сравнить три модели ИБП"})
        new_id = record["items"][0]["id"]
        set_triage(self.path, new_id, True, "Можно найти и сравнить в интернете")
        self.assertEqual(self.item(new_id)["agent"]["state"], "queued")
        self.assertNotIn("t-00000001", [item["id"] for item in untriaged_items(self.path)])
        change_items(self.path, {"action": "edit", "id": "t-00000001", "text": "Поставить ИБП к пятнице"})
        self.assertIn("t-00000001", [item["id"] for item in untriaged_items(self.path)])

    def test_a_broken_agent_record_falls_back_to_marks_item(self):
        self.path.write_text(json.dumps({"items": [
            {"id": "t-0000000a", "text": "Дело", "agent": {"by": "robot", "state": "working"}},
            {"id": "t-0000000b", "text": "Дело 2", "agent": {"by": "claude", "state": "done", "url": "javascript:x"}},
        ]}))
        items = load_items(self.path)["items"]
        self.assertNotIn("agent", items[0])
        self.assertNotIn("url", items[1]["agent"])


FAKE_CLI = """#!{python}
import json, sys
prompt = sys.stdin.read()
args = sys.argv[1:]
with open({log!r}, "a") as log:
    log.write(json.dumps(args) + "\\n")
if '"items"' in prompt:
    items = json.loads(prompt)["items"]
    answer = {{"items": [{{"id": item["id"], "agent": "Сравнить" in item["text"], "why": "тест"}} for item in items]}}
else:
    answer = {{"state": "done", "result": "Сравнил три модели, отчёт готов.", "url": "https://example.com/report"}}
print(json.dumps({{"result": "Готово.\\n" + json.dumps(answer, ensure_ascii=False)}}))
"""


class RunnerTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.todo = self.root / "owner-todo.json"
        self.tasks = self.root / "agent-tasks"
        self.calls = self.root / "calls.log"
        self.cli = self.root / "claude"
        self.cli.write_text(FAKE_CLI.format(python=sys.executable, log=str(self.calls)))
        self.cli.chmod(self.cli.stat().st_mode | stat.S_IXUSR)
        os.environ.pop("CLAUDE_CODE_OAUTH_TOKEN", None)

    def run_once(self, *extra):
        return RUNNER.main(["--todo", str(self.todo), "--tasks", str(self.tasks), "--claude", str(self.cli),
                            *extra])

    def test_sorts_queues_and_works_one_item(self):
        record = change_items(self.todo, {"action": "add", "text": "Сравнить три модели ИБП"})
        new_id = record["items"][0]["id"]
        self.assertEqual(self.run_once(), 0)
        item = next(entry for entry in load_items(self.todo)["items"] if entry["id"] == new_id)
        self.assertEqual(item["agent"]["state"], "done")
        self.assertEqual(item["agent"]["url"], "https://example.com/report")
        others = [entry for entry in load_items(self.todo)["items"] if entry["id"] != new_id]
        self.assertTrue(all("agent" not in entry and entry["triage"]["agent"] is False for entry in others))
        status = json.loads((self.tasks / "status.json").read_text())
        self.assertEqual((status["ok"], status["worked"]["state"]), (True, "done"))
        calls = [json.loads(line) for line in self.calls.read_text().splitlines()]
        triage_call, work_call = calls
        self.assertIn("--tools", triage_call)  # Sorting runs with no tools at all.
        self.assertEqual(triage_call[triage_call.index("--tools") + 1], "")
        self.assertIn("--allowedTools", work_call)
        disallowed = work_call[work_call.index("--disallowedTools") + 1:]
        self.assertIn("Bash(gh pr merge:*)", disallowed)
        self.assertFalse(any("merge" in tool for tool in work_call[work_call.index("--allowedTools") + 1:
                                                                     work_call.index("--disallowedTools")]))

    def test_idle_when_nothing_to_do(self):
        for item_id in ("t-00000001", "t-00000002", "t-00000003", "t-00000004"):
            set_triage(self.todo, item_id, False, "только Марк")
        self.assertEqual(self.run_once(), 0)
        self.assertFalse(self.calls.exists())

    def test_stale_working_item_is_blocked_without_replaying_unknown_actions(self):
        change_items(self.todo, {"action": "assign", "id": "t-00000001"})
        update_agent(self.todo, "t-00000001", "working", by="claude",
                     now=datetime(2020, 1, 1, tzinfo=timezone.utc))

        self.assertEqual(self.run_once("--no-triage", "--timeout", "60"), 0)

        item = next(entry for entry in load_items(self.todo)["items"] if entry["id"] == "t-00000001")
        self.assertEqual(item["agent"]["state"], "needs_mark")
        self.assertIn("не повтор", item["agent"]["result"].lower())
        self.assertFalse(self.calls.exists())
        status = json.loads((self.tasks / "status.json").read_text())
        self.assertEqual(status["reconciled"], [{"id": "t-00000001", "state": "needs_mark"}])

    def test_recent_working_item_keeps_the_next_queued_item_from_starting(self):
        change_items(self.todo, {"action": "assign", "id": "t-00000001"})
        update_agent(self.todo, "t-00000001", "working", by="claude",
                     now=datetime.now(timezone.utc))
        change_items(self.todo, {"action": "assign", "id": "t-00000002"})

        self.assertEqual(self.run_once("--no-triage", "--timeout", "3600"), 0)

        items = {entry["id"]: entry for entry in load_items(self.todo)["items"]}
        self.assertEqual(items["t-00000001"]["agent"]["state"], "working")
        self.assertEqual(items["t-00000002"]["agent"]["state"], "queued")
        self.assertFalse(self.calls.exists())
        status = json.loads((self.tasks / "status.json").read_text())
        self.assertEqual(status["working"], [{"id": "t-00000001", "by": "claude"}])

    def test_reply_parsing_takes_the_last_json_object(self):
        self.assertEqual(RUNNER.parse_json_reply('Сделал.\n```json\n{"state": "done"}\n```'), {"state": "done"})
        self.assertIsNone(RUNNER.parse_json_reply("без ответа"))


class AgentPageAndApiTests(unittest.TestCase):
    def test_runner_status_says_only_what_the_page_needs(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "status.json"
            self.assertEqual(SERVER._agent_runner_status(path), {"state": "unknown"})
            path.write_text(json.dumps({"ok": False, "reason": "claude_auth_failed: token sk-ant-xyz", "last_run": "2026-10-23T12:00:00Z"}))
            self.assertEqual(SERVER._agent_runner_status(path),
                             {"state": "error", "last_run": "2026-10-23T12:00:00Z", "reason": "claude_auth_failed"})

    def test_page_offers_hand_off_and_shows_agents_walking(self):
        for needle in ("data-todo-give", "data-todo-take", "action: 'assign'", "action: 'unassign'",
                       "mm-agent-lane", "prefers-reduced-motion: reduce) {\n  .mm-agent-walker"):
            self.assertIn(needle, PAGE)


    def test_deploy_ships_and_installs_the_runner(self):
        deploy = (BUILDER / "deploy_to_scripts.sh").read_text()
        self.assertIn('cp "$SRC_DIR/agent_task_runner.py"', deploy)
        self.assertIn("com.pirajoke.agent-task-runner", deploy)
        plist = (BUILDER / "launchd" / "com.pirajoke.agent-task-runner.plist.template").read_text()
        self.assertIn("<integer>300</integer>", plist)

if __name__ == "__main__":
    unittest.main()
