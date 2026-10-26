"""Агенты → Сессии (Mark 2026-10-25): every Claude Code and Codex session open on his Macs, in one place."""
from __future__ import annotations

import importlib.util
import io
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

BUILDER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BUILDER))

import live_sessions_collector as collector  # noqa: E402
from dashboard_builder.live_sessions import ask_of, projection  # noqa: E402

spec = importlib.util.spec_from_file_location("dashboard_live_sessions_test", BUILDER / "dashboard-server-m4.py")
SERVER = importlib.util.module_from_spec(spec)
spec.loader.exec_module(SERVER)
PAGE = (BUILDER / "mac-mini-dashboard" / "index.html").read_text()
NOW = datetime(2026, 10, 25, 22, 0, tzinfo=timezone.utc)


def ts(minutes_ago: float) -> str:
    return (NOW - timedelta(minutes=minutes_ago)).isoformat().replace("+00:00", "Z")


def write_jsonl(path: Path, records: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(record) for record in records) + "\n")
    return path


def claude_user(minutes_ago, text, **extra):
    return {"type": "user", "sessionId": "c1a2b3c4-0000", "timestamp": ts(minutes_ago), "cwd": "/tmp/agent-dashboard",
            "entrypoint": "cli", "message": {"role": "user", "content": text}, **extra}


def claude_assistant(minutes_ago, content, stop="end_turn"):
    return {"type": "assistant", "sessionId": "c1a2b3c4-0000", "timestamp": ts(minutes_ago), "cwd": "/tmp/agent-dashboard",
            "entrypoint": "cli", "message": {"role": "assistant", "stop_reason": stop, "content": content}}


TOOL_USE = [{"type": "tool_use", "id": "tu1", "name": "Bash", "input": {"command": "ls"}}]


class ClaudeStateTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "c1a2b3c4-0000.jsonl"

    def parse(self, records, links=None):
        write_jsonl(self.path, records)
        with patch.object(collector, "repo_for_cwd", return_value="pirajoke/agent-dashboard"):
            return collector.parse_claude(self.path, NOW, links)

    def test_answered_turn_waits_for_mark_with_title_and_reply(self):
        session = self.parse([
            claude_user(30, "Сделай дашборд сессий"),
            {"type": "ai-title", "aiTitle": "Дашборд сессий"},
            claude_assistant(5, [{"type": "text", "text": "Готово, PR открыт. token=abcdefghijk"}]),
        ])
        self.assertEqual(session["state"], "waiting")
        self.assertEqual(session["title"], "Дашборд сессий")
        self.assertEqual(session["project"], "agent-dashboard")
        self.assertIn("Готово, PR открыт", session["reply"])
        self.assertNotIn("abcdefghijk", session["reply"])
        self.assertIsNone(session["approval"])

    def test_ask_keeps_the_end_of_a_long_reply(self):
        long = "Сделал. " + "Проверил всё по шагам. " * 40 + "Сливать PR #154?"
        session = self.parse([claude_user(30, "go"), claude_assistant(5, [{"type": "text", "text": long}])])
        self.assertTrue(session["ask"].endswith("Сливать PR #154?"))
        self.assertTrue(session["ask"].startswith("Проверил"))
        self.assertEqual(ask_of(session["ask"]), "Сливать PR #154?")
        self.assertEqual(session["resume"], "cd /tmp/agent-dashboard && claude --resume c1a2b3c4-0000")

    def test_tool_call_left_waiting_reads_as_a_permission_question(self):
        waiting = self.parse([claude_user(10, "go"), claude_assistant(5, TOOL_USE, "tool_use")])
        self.assertEqual((waiting["state"], waiting["approval"]), ("approve", "Разрешить команду: ls"))
        self.assertEqual(self.parse([claude_user(1, "go"), claude_assistant(0.5, TOOL_USE, "tool_use")])["state"], "working")

    def test_tool_result_means_working_until_it_stalls(self):
        result = {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "tu1", "content": "ok"}]}
        fresh = self.parse([claude_user(3, "go"), claude_assistant(2, TOOL_USE, "tool_use"),
                            {**claude_user(1, ""), "message": result}])
        self.assertEqual(fresh["state"], "working")
        stalled = self.parse([claude_user(40, "go"), claude_assistant(35, TOOL_USE, "tool_use"),
                              {**claude_user(30, ""), "message": result}])
        self.assertEqual(stalled["state"], "stopped")

    def test_interrupted_turn_waits(self):
        self.assertEqual(self.parse([claude_user(3, "go"), claude_user(1, "[Request interrupted by user]")])["state"], "waiting")

    def test_remote_control_link_is_found_even_deep_in_the_log(self):
        links = {}
        session = self.parse([claude_user(3, "go"),
                              {"type": "system", "content": "Remote Control: https://claude.ai/code/session_01ABCdefGHIjkl"},
                              claude_assistant(1, [{"type": "text", "text": "ok"}])], links)
        self.assertEqual(session["link"], "https://claude.ai/code/session_01ABCdefGHIjkl")
        self.assertEqual(links, {"c1a2b3c4-0000": "https://claude.ai/code/session_01ABCdefGHIjkl"})

    def test_link_is_searched_again_once_the_log_grows(self):
        links = {}
        first = self.parse([claude_user(3, "go"), claude_assistant(2, [{"type": "text", "text": "ok"}])], links)
        self.assertIsNone(first["link"])
        self.assertIsInstance(links["c1a2b3c4-0000"], dict)
        with self.path.open("a") as handle:
            handle.write(json.dumps({"type": "system", "content": "https://claude.ai/code/session_01LaterOnABC"}) + "\n")
        with patch.object(collector, "repo_for_cwd", return_value=None):
            later = collector.parse_claude(self.path, NOW, links)
        self.assertEqual(later["link"], "https://claude.ai/code/session_01LaterOnABC")

    def test_title_skips_wrappers_and_falls_back_to_the_project(self):
        wrapped = self.parse([claude_user(3, "[MESSAGE FROM NON-USER SOURCE] wake"), claude_assistant(1, [{"type": "text", "text": "ok"}])])
        self.assertEqual(wrapped["title"], "Сессия в agent-dashboard")
        renamed = self.parse([claude_user(3, "go"), {"type": "ai-title", "aiTitle": "Авто"},
                              {"type": "custom-title", "customTitle": "Моё имя"}, claude_assistant(1, [{"type": "text", "text": "ok"}])])
        self.assertEqual(renamed["title"], "Моё имя")

    def test_headless_runs_are_left_out(self):
        record = {**claude_user(1, "summarise"), "entrypoint": "sdk-cli"}
        self.assertIsNone(self.parse([record]))


class CodexStateTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "rollout-2026-10-25T21-00-00-0199aaaa-bbbb-cccc-dddd-eeeeffff0000.jsonl"

    def meta(self, **extra):
        return {"type": "session_meta", "timestamp": ts(60), "payload": {
            "id": "0199aaaa-bbbb-cccc-dddd-eeeeffff0000", "cwd": "/tmp/shop", "originator": "Codex Desktop", **extra}}

    def parse(self, records, names=None):
        write_jsonl(self.path, records)
        with patch.object(collector, "repo_for_cwd", return_value=None):
            return collector.parse_codex(self.path, NOW, names or {})

    def test_finished_task_waits_and_opens_in_the_codex_app(self):
        session = self.parse([
            self.meta(),
            {"type": "event_msg", "timestamp": ts(20), "payload": {"type": "user_message", "message": "Почини корзину"}},
            {"type": "event_msg", "timestamp": ts(4), "payload": {"type": "task_complete", "last_agent_message": "Корзина починена"}},
        ])
        self.assertEqual((session["state"], session["title"], session["app"]), ("waiting", "Почини корзину", "Приложение Codex"))
        self.assertEqual(session["link"], "codex://threads/0199aaaa-bbbb-cccc-dddd-eeeeffff0000")
        self.assertEqual(session["reply"], "Корзина починена")
        self.assertTrue(session["resume"].endswith("codex resume 0199aaaa-bbbb-cccc-dddd-eeeeffff0000"))

    def test_final_response_item_ends_the_turn(self):
        session = self.parse([self.meta(),
                              {"type": "response_item", "timestamp": ts(3), "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "go"}]}},
                              {"type": "response_item", "timestamp": ts(2), "payload": {"type": "message", "role": "assistant", "channel": "commentary", "content": [{"type": "output_text", "text": "смотрю"}]}},
                              {"type": "response_item", "timestamp": ts(1), "payload": {"type": "message", "role": "assistant", "channel": "final", "content": [{"type": "output_text", "text": "Готово"}]}}])
        self.assertEqual((session["state"], session["reply"]), ("waiting", "Готово"))

    def test_approval_request_and_running_call(self):
        approval = self.parse([self.meta(),
                               {"type": "event_msg", "timestamp": ts(3), "payload": {"type": "task_started"}},
                               {"type": "response_item", "timestamp": ts(2), "payload": {"type": "function_call", "call_id": "c1"}},
                               {"type": "event_msg", "timestamp": ts(2), "payload": {"type": "exec_approval_request",
                                                                                     "command": ["npm", "install"]}}])
        self.assertEqual((approval["state"], approval["approval"]), ("approve", "Разрешить команду: npm install"))
        running = self.parse([self.meta(),
                              {"type": "event_msg", "timestamp": ts(1), "payload": {"type": "task_started"}},
                              {"type": "response_item", "timestamp": ts(0.5), "payload": {"type": "function_call", "call_id": "c1"}}])
        self.assertEqual(running["state"], "working")
        # A scheduled run's long command is not a permission question: Codex logs those as events.
        long = self.parse([self.meta(),
                           {"type": "event_msg", "timestamp": ts(6), "payload": {"type": "task_started"}},
                           {"type": "response_item", "timestamp": ts(5), "payload": {"type": "function_call", "call_id": "c1"}}])
        self.assertEqual(long["state"], "working")

    def test_app_title_wins_and_helpers_and_exec_runs_are_skipped(self):
        session = self.parse([self.meta(), {"type": "event_msg", "timestamp": ts(1), "payload": {"type": "user_message", "message": "x"}}],
                             {"0199aaaa-bbbb-cccc-dddd-eeeeffff0000": "Корзина"})
        self.assertEqual(session["title"], "Корзина")
        self.assertIsNone(self.parse([self.meta(originator="codex_exec")]))
        self.assertIsNone(self.parse([self.meta(source={"subagent": "review"})]))


class ProjectionTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.dir = Path(temp.name)

    def write(self, machine, collected_minutes_ago, sessions):
        (self.dir / f"{machine}.json").write_text(json.dumps(
            {"schema": 1, "machine": machine, "collected_at": ts(collected_minutes_ago), "sessions": sessions}))

    def session(self, sid, state, minutes_ago, link=None, **extra):
        return {"id": sid, "tool": "claude", "app": "Терминал", "title": sid, "project": "p", "state": state,
                "started_at": ts(minutes_ago + 10), "last_at": ts(minutes_ago), "link": link,
                "resume": f"claude --resume {sid}", "reply": "Сливать #154?", **extra}

    def test_order_quiet_and_stale_machines(self):
        self.write("mac-mini", 1, [self.session("work", "working", 0), self.session("old", "waiting", 300),
                                   self.session("done", "waiting", 5, "javascript:alert(1)"), self.session("ask", "approve", 3)])
        self.write("macbook-pro", 60, [self.session("gone", "waiting", 61)])
        result = projection(self.dir, NOW)
        self.assertEqual([s["id"] for s in result["sessions"]], ["ask", "done", "work", "old"])
        self.assertTrue(result["sessions"][-1]["quiet"])
        self.assertIsNone(result["sessions"][1]["link"])
        self.assertEqual(result["sessions"][0]["machine"], "Mac mini")
        self.assertEqual({m["label"]: m["fresh"] for m in result["machines"]}, {"Mac mini": True, "MacBook Pro": False})

    def test_only_a_question_or_permission_waits_for_mark(self):
        # Mark 2026-10-26: a scheduled check that reported its result and a turn that only laid out a
        # plan wanted nothing from him, yet showed «Ждёт тебя».
        self.write("mac-mini", 1, [
            self.session("doctolib", "waiting", 5, reply="Vérification Doctolib terminée : aucun créneau disponible."),
            self.session("plan", "waiting", 5, reply="I'll check the parser first, then set up the scheduled run."),
            self.session("offer", "waiting", 5, reply="Готово, PR #12 слит. Если хочешь, могу добавить тесты?"),
            self.session("question", "waiting", 5, reply="Сделал два варианта.", ask="Сделал два варианта. Какой оставить?"),
            self.session("perm", "approve", 5, approval="Разрешить команду: git push -u origin x"),
            self.session("stuck", "stopped", 40)])
        sessions = {s["id"]: s for s in projection(self.dir, NOW)["sessions"]}
        self.assertEqual({k: (s["state"], s["quiet"]) for k, s in sessions.items()}, {
            "doctolib": ("done", True), "plan": ("done", True), "offer": ("done", True),
            "question": ("waiting", False), "perm": ("approve", False), "stuck": ("stopped", True)})
        self.assertEqual(sessions["question"]["need"], "Какой оставить?")
        self.assertEqual(sessions["perm"]["need"], "Разрешить команду: git push -u origin x")
        self.assertIsNone(sessions["doctolib"]["need"])

    def test_ask_words_without_a_question_mark(self):
        self.assertEqual(ask_of("Всё готово к выкату. Нужно твоё подтверждение, чтобы слить PR."),
                         "Нужно твоё подтверждение, чтобы слить PR.")
        self.assertIsNone(ask_of("Тесты прошли. PR слит."))
        self.assertIsNone(ask_of("Сейчас этим занимаются: MAIN MANAGER на Mac mini отвечает за продолжение: "
                                 "проверяет результаты и запускает следующие разрешённые шаги."))

    def test_missing_folder_is_empty(self):
        self.assertEqual(projection(self.dir / "nope", NOW)["sessions"], [])


class EndpointTests(unittest.TestCase):
    def call(self, token):
        handler = SERVER.Handler.__new__(SERVER.Handler)
        handler.path, handler.command = "/api/live-sessions", "GET"
        handler.headers = {"Host": "command.meshly.fr"}
        if token:
            handler.headers["X-Dashboard-Run-Token"] = token
        handler.rfile = io.BytesIO(b"")
        output = {}
        handler._json_response = lambda status, payload: output.update(status=status, payload=payload)
        with (patch.object(SERVER, "_dashboard_run_token", return_value="fixture-owner"),
              patch.object(SERVER.Handler, "_cloudflare_access_owner", return_value=False),
              patch.object(SERVER, "LIVE_SESSIONS_DIR", Path(tempfile.gettempdir()) / "no-live-sessions-here")):
            handler.do_GET()
        return output

    def test_owner_only(self):
        self.assertEqual(self.call(None)["status"], 401)
        self.assertEqual(self.call(None)["payload"]["sessions"], [])
        self.assertEqual(self.call("wrong")["status"], 401)
        owner = self.call("fixture-owner")
        self.assertEqual((owner["status"], owner["payload"]["state"]), (200, "ready"))


class PageTests(unittest.TestCase):
    def test_agents_open_on_sessions(self):
        self.assertIn('aria-controls="agents-sessions" aria-pressed="true" onclick="showAgentsView(\'sessions\')">Сессии</button>', PAGE)
        self.assertIn('<section id="agents-sessions" aria-label="Сессии">', PAGE)
        self.assertIn("/api/live-sessions", PAGE)
        self.assertIn("if (name === 'agents') setTimeout(liveSessionsLoad, 0);", PAGE)

    def test_installed_on_every_mac_and_deployed(self):
        install = (BUILDER / "install_daily_work_collector.sh").read_text()
        self.assertIn("install_agent com.pirajoke.live-sessions live_sessions_collector.py 60", install)
        deploy = (BUILDER / "deploy_to_scripts.sh").read_text()
        self.assertIn('cp "$SRC_DIR/live_sessions_collector.py" "$SCRIPTS_DIR/live_sessions_collector.py"', deploy)


if __name__ == "__main__":
    unittest.main()
