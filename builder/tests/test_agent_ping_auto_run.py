from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


BUILDER_DIR = Path(__file__).resolve().parents[1]
HTML_PATH = BUILDER_DIR / "mac-mini-dashboard" / "index.html"
SERVER_PATH = BUILDER_DIR / "dashboard-server-m4.py"
PIPELINE_PATH = BUILDER_DIR / "jarvis-agent-pipeline"

CANONICAL_ROLES = (
    "coordinator",
    "researcher",
    "builder",
    "designer",
    "infrastructure",
    "vault",
    "analyst",
)
SAFE_STATES = {"checking", "working", "idle", "blocked", "failed"}
SAFE_STATUS_KEYS = {
    "run_id",
    "role",
    "state",
    "summary",
    "next_step",
    "issue_url",
    "issue_number",
    "auto_started",
    "updated_at",
}
PRIVATE_MARKERS = (
    "prompt",
    "issue_body",
    "tool_output",
    "model_output",
    "credentials",
    "environment",
    "report_path",
    "project_dir",
    "bridge_task_id",
    "private_url",
    "traceback",
    "/Users/private",
    "ghp_private",
)

if str(BUILDER_DIR) not in sys.path:
    sys.path.insert(0, str(BUILDER_DIR))


def _load_server():
    spec = importlib.util.spec_from_file_location(
        f"dashboard_server_m4_agent_auto_run_{id(object())}", SERVER_PATH
    )
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _function_source(source: str, name: str) -> str:
    match = re.search(rf"(?:async\s+)?function\s+{re.escape(name)}\s*\([^)]*\)\s*\{{", source)
    if match is None:
        return ""
    next_function = re.search(r"\n(?:async\s+)?function\s+[A-Za-z_$]", source[match.end() :])
    end = match.end() + next_function.start() if next_function else len(source)
    return source[match.start() : end]


def _last_rule(css: str, selector: str) -> str:
    matches = list(
        re.finditer(rf"{re.escape(selector)}\s*\{{(?P<body>[^}}]*)\}}", css, re.DOTALL)
    )
    return matches[-1].group("body") if matches else ""


def _first_rule(css: str, selector: str) -> str:
    match = re.search(rf"{re.escape(selector)}\s*\{{(?P<body>[^}}]*)\}}", css, re.DOTALL)
    return match.group("body") if match else ""


def _card_source(source: str, role: str) -> str:
    marker = f'data-role="{role}"'
    start = source.index(marker)
    start = source.rfind('<div class="jarvis-flow-step', 0, start)
    end = source.find("</button>", start)
    return source[start : end + len("</button>")]


class AgentPingSafeStatusTests(unittest.TestCase):
    def _status(self, report_text: str, *, role: str = "builder") -> dict:
        server = _load_server()
        with tempfile.TemporaryDirectory() as tmp:
            report_dir = Path(tmp)
            run_id = f"ping-{role}-20260812-010203-abc123"
            report_path = report_dir / f"{run_id}.md"
            report_path.write_text(report_text, encoding="utf-8")
            handler = server.Handler.__new__(server.Handler)
            response: dict[str, object] = {}
            handler._require_dashboard_run_auth = MagicMock(return_value=True)
            handler._json_response = lambda status, payload: response.update(
                http_status=status, payload=payload
            )
            raw = {
                "status": "done",
                "result_summary": "provider output must not be projected",
                "updated_at": "2026-08-12T01:02:03Z",
                "report_path": str(report_path),
                "project_dir": "/Users/private/JARVIS",
                "task": "private task body",
                "report_tail": "ghp_private tool_output traceback",
                "steps": [{"prompt": "private"}],
            }
            with (
                patch.object(server, "JARVIS_PIPELINE_REPORT_DIR", report_dir),
                patch.object(server, "_pipeline_report_payload", return_value=raw),
                patch.object(server, "_jarvis_ping_role", return_value=role),
            ):
                handler._handle_jarvis_pipeline_status(
                    SimpleNamespace(query=f"run_id={run_id}")
                )
        self.assertEqual(response["http_status"], 200)
        return response["payload"]

    def test_ac2_status_projects_only_the_safe_localized_runner_schema(self):
        payload = self._status(
            "# Ping\n"
            "- Agent state: working\n"
            "- Agent summary: Разработчик начал одобренную задачу.\n"
            "- Agent next step: Дождитесь результата и проверки.\n"
            "- Agent auto-started: true\n"
            "- Agent issue URL: https://github.com/pirajoke/jarvis/issues/71\n"
            "- Agent issue number: 71\n"
            "- Prompt: /Users/private ghp_private\n"
        )

        self.assertEqual(set(payload), SAFE_STATUS_KEYS)
        self.assertEqual(payload["role"], "builder")
        self.assertEqual(payload["state"], "working")
        self.assertEqual(payload["summary"], "Разработчик начал одобренную задачу.")
        self.assertEqual(payload["next_step"], "Дождитесь результата и проверки.")
        self.assertIs(payload["auto_started"], True)
        self.assertEqual(payload["issue_number"], 71)
        self.assertEqual(
            payload["issue_url"], "https://github.com/pirajoke/jarvis/issues/71"
        )
        serialized = json.dumps(payload, ensure_ascii=False).lower()
        for marker in PRIVATE_MARKERS:
            self.assertNotIn(marker.lower(), serialized)

    def test_ac2_known_run_without_report_is_a_safe_checking_response(self):
        server = _load_server()
        with tempfile.TemporaryDirectory() as tmp:
            report_dir = Path(tmp)
            run_id = "ping-vault-20260812-010203-abc123"
            handler = server.Handler.__new__(server.Handler)
            response: dict[str, object] = {}
            handler._require_dashboard_run_auth = MagicMock(return_value=True)
            handler._json_response = lambda status, payload: response.update(
                http_status=status, payload=payload
            )
            with (
                patch.object(server, "JARVIS_PIPELINE_REPORT_DIR", report_dir),
                patch.object(server, "_jarvis_ping_role", return_value="vault"),
            ):
                handler._handle_jarvis_pipeline_status(
                    SimpleNamespace(query=f"run_id={run_id}")
                )

        self.assertEqual(response["http_status"], 200)
        payload = response["payload"]
        self.assertEqual(
            set(payload),
            {
                "run_id",
                "role",
                "state",
                "summary",
                "next_step",
                "auto_started",
                "updated_at",
            },
        )
        self.assertEqual(payload["state"], "checking")
        self.assertIs(payload["auto_started"], False)

    def test_ac2_only_five_states_are_public_and_malformed_output_fails_closed(self):
        for state in sorted(SAFE_STATES):
            with self.subTest(state=state):
                payload = self._status(
                    "# Ping\n"
                    f"- Agent state: {state}\n"
                    "- Agent summary: Безопасный публичный статус.\n"
                    "- Agent next step: Безопасный следующий шаг.\n"
                    "- Agent auto-started: false\n"
                )
                self.assertEqual(payload.get("state"), state)

        malformed = self._status(
            "# Ping\n"
            "- Agent state: done\n"
            "- Agent summary: /Users/private ghp_private\n"
            "- Agent next step: https://private.example/action\n"
            "- Agent auto-started: definitely\n"
            "- Agent issue URL: file:///Users/private/task\n"
        )
        self.assertEqual(malformed.get("state"), "failed")
        self.assertIs(malformed.get("auto_started"), False)
        self.assertNotIn("issue_url", malformed)
        self.assertNotIn("issue_number", malformed)
        self.assertRegex(str(malformed.get("summary", "")).lower(), r"не удалось|ошиб")
        self.assertRegex(str(malformed.get("next_step", "")).lower(), r"повтор|позже|проверь")
        serialized = json.dumps(malformed, ensure_ascii=False).lower()
        for marker in PRIVATE_MARKERS:
            self.assertNotIn(marker.lower(), serialized)

    def test_ac2_non_github_or_mismatched_issue_links_are_never_projected(self):
        for url, number in (
            ("http://github.com/pirajoke/jarvis/issues/71", 71),
            ("https://evil.example/pirajoke/jarvis/issues/71", 71),
            ("https://github.com/pirajoke/jarvis/pull/71", 71),
            ("https://github.com/pirajoke/jarvis/issues/72", 71),
        ):
            with self.subTest(url=url):
                payload = self._status(
                    "# Ping\n"
                    "- Agent state: idle\n"
                    "- Agent summary: Агент на связи.\n"
                    "- Agent next step: Нет одобренной задачи для этого агента.\n"
                    "- Agent auto-started: false\n"
                    f"- Agent issue URL: {url}\n"
                    f"- Agent issue number: {number}\n"
                )
                self.assertNotIn("issue_url", payload)
                self.assertNotIn("issue_number", payload)


class AgentPingRunnerDelegationTests(unittest.TestCase):
    def _run_pipeline(self, *, pong: str, runner_output: object) -> tuple[subprocess.CompletedProcess, Path, Path]:
        zsh = shutil.which("zsh")
        if zsh is None:
            self.skipTest("behavioral shell scenarios require zsh")
        root = Path(tempfile.mkdtemp(prefix="agent-ping-auto-run-test-"))
        self.addCleanup(shutil.rmtree, root, True)
        home = root / "home"
        bin_dir = home / ".local" / "bin"
        project = root / "jarvis"
        reports = root / "reports"
        bin_dir.mkdir(parents=True)
        project.mkdir()

        claude = bin_dir / "claude"
        claude.write_text(f"#!/bin/sh\nprintf '%s\\n' {json.dumps(pong)}\n", encoding="utf-8")
        claude.chmod(0o700)

        calls = root / "runner-calls"
        runner = root / "agent-auto-runner"
        output_text = (
            json.dumps(runner_output, ensure_ascii=False, separators=(",", ":"))
            if not isinstance(runner_output, str)
            else runner_output
        )
        runner.write_text(
            "#!/bin/sh\n"
            "printf '%s\\n' \"$*\" >> \"$JARVIS_TEST_RUNNER_CALLS\"\n"
            f"printf '%s\\n' {json.dumps(output_text)}\n",
            encoding="utf-8",
        )
        runner.chmod(0o700)

        env = os.environ.copy()
        env.update(
            HOME=str(home),
            JARVIS_AGENT_ENV_FILE=str(root / "missing.env"),
            JARVIS_AGENT_PING_ROLE="builder",
            JARVIS_AGENT_PROVIDER="claude",
            JARVIS_CLAUDE_BIN=str(claude),
            JARVIS_AGENT_PROJECT_NAME="jarvis",
            JARVIS_PROJECT_DIR=str(project),
            JARVIS_AGENT_REPORT_DIR=str(reports),
            JARVIS_AGENT_RUN_ID="ping-builder-test",
            JARVIS_AGENT_AUTO_RUNNER=str(runner),
            JARVIS_TEST_RUNNER_CALLS=str(calls),
            JARVIS_OMNI_APPROVAL_LEDGER=str(root / "omni.jsonl"),
            JARVIS_AGENT_SELF_LEARNING_LEDGER=str(root / "learning.jsonl"),
        )
        result = subprocess.run(
            [zsh, str(PIPELINE_PATH), "Read-only ping; then dispatch one approved task."],
            cwd=project,
            env=env,
            capture_output=True,
            text=True,
            timeout=20,
        )
        return result, calls, reports / "ping-builder-test.md"

    def test_ac1_ac4_valid_pong_precedes_exact_installed_runner_delegation(self):
        source = PIPELINE_PATH.read_text(encoding="utf-8")
        self.assertTrue(
            "JARVIS_AGENT_AUTO_RUNNER" in source,
            "ping route must expose only the installed-runner executable override",
        )
        self.assertIsNotNone(
            re.search(
                r'"?\$\{?JARVIS_AGENT_AUTO_RUNNER[^\n]*\}?"?[^\n]*"?\$\{?PING_ROLE\}?"?',
                source,
            ),
            "override runner must receive the exact role as its only positional argument",
        )
        self.assertIsNotNone(
            re.search(
                r'\.venv/bin/python.*?-m\s+jarvis\.dashboard_agent_runner\s+--role\s+"?\$\{?PING_ROLE\}?"?',
                source,
                re.DOTALL,
            ),
            "production fallback must use the installed JARVIS module and exact role",
        )
        valid_guard = source.index('ping_output_valid "$PING_OUTPUT"')
        runner_call = source.index("JARVIS_AGENT_AUTO_RUNNER", valid_guard)
        self.assertGreater(runner_call, valid_guard)

        result, calls, report = self._run_pipeline(
            pong="PONG — Разработчик на связи",
            runner_output={
                "role": "builder",
                "state": "idle",
                "summary": "Разработчик на связи.",
                "next_step": "Нет одобренной задачи для этого агента.",
                "auto_started": False,
            },
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls.read_text(encoding="utf-8").splitlines(), ["builder"])
        report_text = report.read_text(encoding="utf-8")
        self.assertIn("- Agent state: idle", report_text)
        self.assertIn("- Agent auto-started: false", report_text)

    def test_ac1_invalid_pong_never_calls_the_mutating_runner(self):
        result, calls, report = self._run_pipeline(
            pong="на связи без обязательного маркера",
            runner_output={
                "role": "builder",
                "state": "working",
                "summary": "Нельзя увидеть.",
                "next_step": "Нельзя увидеть.",
                "auto_started": True,
            },
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(calls.exists(), "runner must not execute before a valid PONG")
        report_text = report.read_text(encoding="utf-8")
        self.assertNotIn("Agent auto-started: true", report_text)

    def test_ac2_malformed_or_private_runner_json_becomes_one_generic_failed_result(self):
        unsafe_outputs = (
            '{"role":"builder","state":"working","auto_started":true,'
            '"summary":"/Users/private ghp_private","next_step":"deploy"} trailing',
            {
                "role": "researcher",
                "state": "working",
                "summary": "wrong role",
                "next_step": "continue",
                "auto_started": True,
            },
            {
                "role": "builder",
                "state": "done",
                "summary": "unknown public state",
                "next_step": "continue",
                "auto_started": False,
            },
            {
                "role": "builder",
                "state": "working",
                "summary": "/Users/private ghp_private",
                "next_step": "https://private.example/action",
                "auto_started": True,
                "bridge_task_id": "private-bridge-id",
            },
        )
        for runner_output in unsafe_outputs:
            with self.subTest(runner_output=runner_output):
                result, calls, report = self._run_pipeline(
                    pong="PONG", runner_output=runner_output
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(
                    calls.read_text(encoding="utf-8").splitlines(), ["builder"]
                )
                report_text = report.read_text(encoding="utf-8")
                self.assertIn("- Agent state: failed", report_text)
                self.assertIn("- Agent auto-started: false", report_text)
                for marker in PRIVATE_MARKERS:
                    self.assertNotIn(marker.lower(), report_text.lower())


class AgentPingInlineProductTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.html = HTML_PATH.read_text(encoding="utf-8")

    def test_ac5_each_card_has_two_live_lines_and_one_safe_optional_task_link(self):
        for role in CANONICAL_ROLES:
            with self.subTest(role=role):
                card = _card_source(self.html, role)
                self.assertRegex(
                    card,
                    rf'id="jarvis-{role}-status"[^>]*(?:role="status"|aria-live="polite")[^>]*>\s*Статус:',
                )
                self.assertRegex(
                    card,
                    rf'id="jarvis-{role}-next"[^>]*>\s*Дальше:',
                )
                self.assertRegex(
                    card,
                    rf'id="jarvis-{role}-task"[^>]*(?:hidden|aria-hidden="true")',
                )
                self.assertRegex(
                    card,
                    rf'id="jarvis-{role}-task"[^>]*rel="[^"]*noopener[^"]*"',
                )
                button = re.search(
                    rf'<button\b[^>]*data-jarvis-ping-role="{role}"[^>]*>', card
                )
                self.assertIsNotNone(button)
                describedby = re.search(r'aria-describedby="([^"]+)"', button.group())
                self.assertIsNotNone(describedby)
                self.assertEqual(
                    set(describedby.group(1).split()),
                    {f"jarvis-{role}-status", f"jarvis-{role}-next"},
                )

        status_rule = _first_rule(self.html, ".jarvis-role-status")
        next_rule = _first_rule(self.html, ".jarvis-role-next")
        for rule in (status_rule, next_rule):
            self.assertRegex(rule, r"white-space\s*:\s*normal")
            self.assertRegex(rule, r"overflow-wrap\s*:\s*anywhere")
            self.assertNotRegex(rule, r"text-overflow\s*:\s*ellipsis")

    def test_ac5_poll_renders_honest_state_next_step_and_button_transitions(self):
        setter = _function_source(self.html, "setJarvisPingState")
        poll = _function_source(self.html, "pollJarvisAgentPing")
        self.assertTrue(setter)
        self.assertTrue(poll)
        for field in ("state", "summary", "next_step", "auto_started"):
            self.assertRegex(poll, rf"data(?:\?\.|\.){field}\b")
        for state in sorted(SAFE_STATES):
            self.assertIn(state, poll + setter)
        for copy in ("Статус:", "Дальше:", "Проверяем…", "Работает", "Пинг"):
            self.assertIn(copy, setter + poll)
        self.assertRegex(setter, r"button\.disabled\s*=.*checking.*working")
        self.assertRegex(setter, r"button\.textContent\s*=")
        self.assertRegex(
            poll,
            r"data\.run_id\s*!==?\s*runId\s*\|\|\s*data\.role\s*!==?\s*role",
        )

    def test_ac5_issue_link_is_strict_github_issue_only_and_clears_stale_links(self):
        safe_url = _function_source(self.html, "safeGitHubIssueUrl")
        render = _function_source(self.html, "setJarvisPingState")
        self.assertTrue(safe_url)
        self.assertRegex(safe_url, r"\.protocol\s*===\s*['\"]https:['\"]")
        self.assertRegex(safe_url, r"\.hostname\s*===\s*['\"]github\.com['\"]")
        self.assertRegex(safe_url, r"/issues/|issues")
        self.assertIn("issue_number", render)
        self.assertRegex(render, r"removeAttribute\(\s*['\"]href['\"]\s*\)")
        self.assertRegex(render, r"(?:hidden\s*=\s*true|setAttribute\(\s*['\"]hidden['\"])")

    def test_ac5_existing_geometry_focus_motion_and_history_contracts_remain(self):
        desktop = _first_rule(self.html, ".jarvis-pipeline-role-strip")
        self.assertRegex(desktop, r"repeat\(4,\s*minmax\(0,\s*1fr\)\)")
        self.assertRegex(
            self.html,
            r"@media\s*\(max-width:\s*840px\)[\s\S]*?repeat\(3,\s*minmax\(0,\s*1fr\)\)",
        )
        mobile_start = self.html.rfind("@media (max-width: 640px)")
        mobile_end = self.html.find("@media", mobile_start + 1)
        mobile = self.html[mobile_start : mobile_end if mobile_end >= 0 else len(self.html)]
        self.assertRegex(mobile, r"repeat\(2,\s*minmax\(0,\s*1fr\)\)")
        self.assertRegex(self.html, r"\.jarvis-ping-button:focus-visible\s*\{")
        self.assertRegex(
            self.html,
            r"@media\s*\(prefers-reduced-motion:\s*reduce\)[\s\S]*?"
            r"\.jarvis-ping-button[\s\S]*?animation\s*:\s*none\s*!important",
        )
        history = _function_source(self.html, "renderJarvisHistory")
        self.assertRegex(history, r"items\.slice\(0,\s*5\)")
        self.assertIn("safeGitHubHistoryUrl(item.url)", history)
        self.assertNotRegex(
            self.html, r'<details\s+class="jarvis-history-panel"[^>]*\sopen(?:\s|>)'
        )


class AgentPingBoundaryRegressionTests(unittest.TestCase):
    def test_ac1_exact_roles_auth_first_busy_lock_and_512_byte_cap_remain(self):
        server = _load_server()
        self.assertEqual(set(server.JARVIS_PING_ROLES), set(CANONICAL_ROLES))
        source = SERVER_PATH.read_text(encoding="utf-8")
        handler_start = source.index("def _handle_jarvis_pipeline_ping(self):")
        handler_end = source.index("def _handle_jarvis_pipeline_status", handler_start)
        handler = source[handler_start:handler_end]
        self.assertLess(handler.index("_require_dashboard_run_auth"), handler.index("_read_json_body"))
        self.assertRegex(handler, r"_read_json_body\(max_bytes=512\)")
        self.assertRegex(handler, r"set\(body\)\s*!=\s*\{['\"]role['\"]\}")
        self.assertIn("_JARVIS_PING_LOCK", handler)
        self.assertIn("agent_ping_busy", handler)
        self.assertRegex(handler, r"_JARVIS_PING_PROCESS\.poll\(\)\s+is\s+None")


if __name__ == "__main__":
    unittest.main()
