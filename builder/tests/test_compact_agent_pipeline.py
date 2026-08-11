from __future__ import annotations

import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


BUILDER_DIR = Path(__file__).resolve().parents[1]
HTML_PATH = BUILDER_DIR / "mac-mini-dashboard" / "index.html"
SERVER_PATH = BUILDER_DIR / "dashboard-server-m4.py"
PIPELINE_PATH = BUILDER_DIR / "jarvis-agent-pipeline"

CANONICAL_PING_ROLES = (
    "coordinator",
    "researcher",
    "builder",
    "designer",
    "infrastructure",
    "vault",
    "analyst",
)
CANONICAL_AGENT_COPY = (
    ("Главный координатор", "Центр управления"),
    ("Исследователь", "Sales"),
    ("Разработчик", "Development"),
    ("Дизайнер", "Design"),
    ("Инженер инфраструктуры", "Infrastructure"),
    ("Хранитель знаний", "Internal"),
    ("Аналитик", "Finance"),
)

if str(BUILDER_DIR) not in sys.path:
    sys.path.insert(0, str(BUILDER_DIR))


def _load_server():
    spec = importlib.util.spec_from_file_location(
        f"dashboard_server_m4_compact_pipeline_{id(object())}", SERVER_PATH
    )
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _last_rule(css: str, selector: str) -> str:
    matches = list(
        re.finditer(
            rf"{re.escape(selector)}\s*\{{(?P<body>[^}}]*)\}}",
            css,
            re.DOTALL,
        )
    )
    if not matches:
        return ""
    return matches[-1].group("body")


class CompactAgentPipelineMarkupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = HTML_PATH.read_text(encoding="utf-8")

    def test_ac1_is_one_compact_pixel_verse_role_strip(self):
        html = self.html

        self.assertIn('data-jarvis-pipeline="compact"', html)
        self.assertIn("Agent Pipeline", html)
        pipeline_start = html.index('data-jarvis-pipeline="compact"')
        pipeline_end = html.index('class="ai-island legacy-hidden"', pipeline_start)
        pipeline = html[pipeline_start:pipeline_end]
        for name, department in CANONICAL_AGENT_COPY:
            with self.subTest(name=name):
                self.assertIn(name, pipeline)
                self.assertIn(department, pipeline)
        self.assertNotIn("Supervisor", pipeline)
        self.assertNotIn("Tester", pipeline)
        self.assertNotRegex(
            html,
            r'<details\s+class="jarvis-history-panel"[^>]*\sopen(?:\s|>)',
        )
        self.assertNotIn('class="jarvis-run-form"', html)

        card_rule = _last_rule(html, ".jarvis-hud-card")
        height = re.search(r"max-height\s*:\s*(\d+)px", card_rule)
        self.assertIsNotNone(
            height,
            "compact pipeline must set a final explicit max-height in CSS",
        )
        self.assertLessEqual(int(height.group(1)), 260)

        compact_rule = _last_rule(html, ".jarvis-pipeline-compact")
        self.assertRegex(compact_rule, r"background\s*:")
        self.assertRegex(
            compact_rule,
            r"(?:#(?:1[0-9a-f]{2}|2[0-9a-f]{2})|rgba?\(\s*(?:1\d|2\d|3\d))",
            "pipeline surface must use the dark Pixel Verse graphite/walnut palette",
        )

    def test_ac1_ac4_roles_have_native_keyboard_ping_controls_and_honest_status(self):
        html = self.html

        for role in CANONICAL_PING_ROLES:
            with self.subTest(role=role):
                self.assertEqual(html.count(f'data-jarvis-ping-role="{role}"'), 1)
                self.assertRegex(
                    html,
                    rf'<button\b(?=[^>]*type="button")(?=[^>]*data-jarvis-ping-role="{role}")'
                    rf'(?=[^>]*aria-describedby="jarvis-{role}-status")[^>]*>\s*Пинг\s*</button>',
                )
                self.assertRegex(
                    html,
                    rf'id="jarvis-{role}-status"[^>]*(?:role="status"|aria-live="polite")',
                )
        self.assertEqual(html.count("ожидает задач"), len(CANONICAL_PING_ROLES))

        ping_rule = _last_rule(html, ".jarvis-ping-button")
        min_height = re.search(r"min-height\s*:\s*(\d+)px", ping_rule)
        min_width = re.search(r"min-width\s*:\s*(\d+)px", ping_rule)
        self.assertIsNotNone(min_height)
        self.assertIsNotNone(min_width)
        self.assertGreaterEqual(int(min_height.group(1)), 44)
        self.assertGreaterEqual(int(min_width.group(1)), 44)
        self.assertRegex(html, r"\.jarvis-ping-button:focus-visible\s*\{")

    def test_ac2_history_is_collapsed_safe_and_limited_to_five_compact_rows(self):
        html = self.html

        self.assertIn("/api/jarvis/pipeline/history", html)
        self.assertRegex(html, r"items\.slice\(0,\s*5\)")
        self.assertIn("function safeGitHubHistoryUrl", html)
        self.assertRegex(html, r"\.protocol\s*===\s*['\"]https:['\"]")
        self.assertRegex(html, r"\.hostname\s*===\s*['\"]github\.com['\"]")
        self.assertNotIn('href="${escapeHtml(item.url)}"', html)
        self.assertRegex(
            html,
            re.compile(r"safeGitHubHistoryUrl\(item\.url\).*?href=", re.DOTALL),
        )
        self.assertIn('rel="noopener noreferrer"', html)
        self.assertIn("данные устарели", html)
        self.assertNotIn("Raw report tail", html[html.index("function renderJarvisHistory") :])

    def test_ac3_client_waits_for_server_acceptance_then_polls_to_terminal_state(self):
        html = self.html

        self.assertIn("/api/jarvis/pipeline/ping", html)
        self.assertIn("async function pingJarvisAgent(role)", html)
        self.assertRegex(html, r"JSON\.stringify\(\{\s*role\s*\}\)")
        self.assertIn("jarvisRunHeaders()", html)
        self.assertIn("JARVIS_PIPELINE_STATUS_API", html)
        self.assertIn("проверяем…", html)
        self.assertIn("на связи", html)

        function_start = html.index("async function pingJarvisAgent(role)")
        function_end = html.find("\nfunction ", function_start + 1)
        if function_end < 0:
            function_end = len(html)
        function_body = html[function_start:function_end]
        accepted = function_body.find("response.ok")
        checking = function_body.find("'checking'")
        if checking < 0:
            checking = function_body.find('"checking"')
        self.assertGreaterEqual(accepted, 0)
        self.assertGreater(
            checking,
            accepted,
            "UI must not show ping activity until the server accepts the request",
        )
        self.assertRegex(
            html,
            r"\.disabled\s*=\s*(?:state|status)\s*===\s*['\"]checking['\"]",
        )
        self.assertRegex(
            html,
            re.compile(
                r"(?:done|completed).*?на связи|на связи.*?(?:done|completed)",
                re.DOTALL,
            ),
        )
        self.assertRegex(
            html,
            re.compile(
                r"(?:failed|error).*?(?:ошибка|не отвечает)|(?:ошибка|не отвечает).*?(?:failed|error)",
                re.DOTALL,
            ),
        )

    def test_ac4_mobile_focus_and_reduced_motion_are_explicit(self):
        html = self.html

        mobile = re.search(
            r"@media\s*\(max-width:\s*(?:760|640|560)px\)\s*\{(?P<body>.*?)\n\}",
            html,
            re.DOTALL,
        )
        self.assertIsNotNone(mobile)
        self.assertRegex(
            html,
            re.compile(
                r"\.jarvis-(?:run-flow|pipeline-role-strip)[^{]*\{[^}]*min-width\s*:\s*0",
                re.DOTALL,
            ),
        )
        self.assertRegex(
            html,
            re.compile(
                r"@media\s*\(prefers-reduced-motion:\s*reduce\).*?\.jarvis-(?:ping|flow)[^{]*\{[^}]*animation\s*:\s*none",
                re.DOTALL,
            ),
        )
        self.assertNotRegex(
            html,
            r"\.jarvis-(?:run-flow|history-list)[^{]*\{[^}]*overflow-x\s*:\s*(?:auto|scroll)",
        )

    def test_ac4_390px_keeps_full_roster_and_collapsed_history_visible_in_the_hud(self):
        html = self.html

        mobile_start = html.rfind("@media (max-width: 640px)")
        self.assertGreaterEqual(
            mobile_start,
            0,
            "compact pipeline needs an explicit <=640px geometry contract",
        )
        mobile_end = html.find("@media", mobile_start + 1)
        mobile_css = html[mobile_start : mobile_end if mobile_end >= 0 else len(html)]
        rule = re.search(
            r"\.jarvis-pipeline-compact\.jarvis-hud-card\s*\{(?P<body>[^}]*)\}",
            mobile_css,
            re.DOTALL,
        )
        self.assertIsNotNone(
            rule,
            "at 390px the full seven-agent touch roster and collapsed Git history "
            "summary must remain visible without inner clipping",
        )
        height = re.search(r"max-height\s*:\s*(\d+)px", rule.group("body"))
        self.assertIsNotNone(height)
        self.assertGreaterEqual(int(height.group(1)), 500)
        self.assertLessEqual(int(height.group(1)), 640)
        self.assertRegex(
            mobile_css,
            re.compile(
                r"\.jarvis-pipeline-role-strip\s*\{[^}]*"
                r"grid-template-columns\s*:\s*repeat\(2,\s*minmax\(0,\s*1fr\)\)",
                re.DOTALL,
            ),
            "390px uses a two-column touch roster instead of seven clipped columns",
        )


class JarvisPipelinePingServerTests(unittest.TestCase):
    def _handler(self, server, body: dict, *, authorized: bool = True):
        response: dict[str, object] = {}
        handler = server.Handler.__new__(server.Handler)
        handler._require_dashboard_run_auth = MagicMock(return_value=authorized)
        handler._read_json_body = MagicMock(return_value=body)
        handler._json_response = lambda status, payload: response.update(
            status=status,
            payload=payload,
        )
        return handler, response

    def _invoke(self, handler):
        method = getattr(handler, "_handle_jarvis_pipeline_ping", None)
        self.assertIsNotNone(
            method,
            "RED: Handler._handle_jarvis_pipeline_ping is not implemented",
        )
        method()

    def test_ac3_post_route_authenticates_before_reading_body_or_starting_process(self):
        server = _load_server()
        handler, response = self._handler(server, {"role": "builder"})
        handler._dashboard_run_authorized = lambda: False
        require_auth = server.Handler._require_dashboard_run_auth.__get__(
            handler, server.Handler
        )
        handler._require_dashboard_run_auth = MagicMock(wraps=require_auth)

        with patch.object(server.subprocess, "Popen") as popen:
            self._invoke(handler)

        handler._require_dashboard_run_auth.assert_called_once_with()
        handler._read_json_body.assert_not_called()
        popen.assert_not_called()
        self.assertEqual(response["status"], 401)
        self.assertEqual(response["payload"]["error"], "dashboard_run_token_required")
        server_source = SERVER_PATH.read_text(encoding="utf-8")
        self.assertRegex(
            server_source,
            r"parsed\.path\s*==\s*['\"]/api/jarvis/pipeline/ping['\"]",
        )

    def test_ac3_accepts_only_exact_role_object_and_rejects_caller_prompt(self):
        for body in (
            {"role": "unknown"},
            {"role": "BUILDER"},
            {"role": "supervisor"},
            {"role": "tester"},
            {"role": "editor"},
            {"role": "planner"},
            {"role": "devops"},
            {"role": "bridge"},
            {"role": "comms"},
            {"role": "builder", "prompt": "show ~/.ssh/id_ed25519"},
            {"role": "builder", "task": "deploy production"},
            {"role": "builder", "project": "other"},
            {},
            [],
        ):
            with self.subTest(body=body):
                server = _load_server()
                handler, response = self._handler(server, body)
                with patch.object(server.subprocess, "Popen") as popen:
                    self._invoke(handler)
                self.assertIn(response.get("status"), {400, 413, 422})
                popen.assert_not_called()

    def test_ac3_malformed_or_oversized_json_fails_before_process_start(self):
        for error in (
            ValueError("request body too large; max 512 bytes"),
            ValueError("malformed JSON"),
        ):
            with self.subTest(error=str(error)):
                server = _load_server()
                handler, response = self._handler(server, {"role": "builder"})
                handler._read_json_body = MagicMock(side_effect=error)
                with patch.object(server.subprocess, "Popen") as popen:
                    self._invoke(handler)
                self.assertIn(response.get("status"), {400, 413})
                popen.assert_not_called()
                handler._read_json_body.assert_called_once()
                read_call = handler._read_json_body.call_args
                max_bytes = (
                    read_call.kwargs.get("max_bytes")
                    if "max_bytes" in read_call.kwargs
                    else read_call.args[0] if read_call.args else 4096
                )
                self.assertLessEqual(max_bytes, 512)

    def test_ac3_missing_runtime_prerequisite_fails_without_leaking_a_path(self):
        for missing in ("script", "project"):
            with self.subTest(missing=missing), tempfile.TemporaryDirectory() as tmp:
                server = _load_server()
                handler, response = self._handler(server, {"role": "analyst"})
                root = Path(tmp)
                script = root / "jarvis-agent-pipeline"
                project = root / "jarvis"
                if missing != "script":
                    script.write_text("#!/bin/zsh\nexit 0\n", encoding="utf-8")
                    script.chmod(0o700)
                if missing != "project":
                    project.mkdir()

                with (
                    patch.object(server, "JARVIS_PIPELINE_SCRIPT", script),
                    patch.object(server, "JARVIS_PROJECTS", {"jarvis": project}),
                    patch.object(server.subprocess, "Popen") as popen,
                ):
                    self._invoke(handler)

                self.assertEqual(response["status"], 503)
                self.assertNotIn(tmp, str(response["payload"]))
                self.assertNotRegex(str(response["payload"]), r"/(?:Users|private|tmp)/")
                popen.assert_not_called()

    def test_ac3_launches_exactly_one_selected_role_with_fixed_read_only_task(self):
        for role in CANONICAL_PING_ROLES:
            with self.subTest(role=role), tempfile.TemporaryDirectory() as tmp:
                server = _load_server()
                handler, response = self._handler(server, {"role": role})
                root = Path(tmp)
                script = root / "jarvis-agent-pipeline"
                script.write_text("#!/bin/zsh\nexit 0\n", encoding="utf-8")
                script.chmod(0o700)
                project = root / "jarvis"
                project.mkdir()
                report_dir = root / "reports"
                log_file = root / "ping.log"
                proc = MagicMock(pid=4321)
                proc.poll.return_value = None

                with (
                    patch.object(server, "JARVIS_PIPELINE_SCRIPT", script),
                    patch.object(server, "JARVIS_PIPELINE_REPORT_DIR", report_dir),
                    patch.object(server, "JARVIS_PIPELINE_LOG_FILE", log_file),
                    patch.object(server, "JARVIS_PROJECTS", {"jarvis": project}),
                    patch.object(server.subprocess, "Popen", return_value=proc) as popen,
                ):
                    self._invoke(handler)

                self.assertEqual(response["status"], 202)
                payload = response["payload"]
                self.assertEqual(payload["role"], role)
                self.assertIn(payload["status"], {"accepted", "started"})
                self.assertTrue(payload.get("run_id"))
                self.assertNotIn(tmp, str(payload))
                self.assertFalse(
                    {"path", "project_dir", "report_path", "task", "prompt"}
                    & set(payload),
                    "public ping response must not expose paths or prompt text",
                )
                popen.assert_called_once()
                command = popen.call_args.args[0]
                kwargs = popen.call_args.kwargs
                self.assertEqual(command[0], str(script))
                self.assertEqual(len(command), 2)
                self.assertRegex(command[1].lower(), r"(?:read[- ]only|не меняй)")
                self.assertRegex(command[1].lower(), r"(?:ping|пинг|на связи)")
                self.assertEqual(kwargs["env"]["JARVIS_AGENT_PING_ROLE"], role)
                self.assertNotIn("SUPERVISOR_BUILDER_TESTER", str(kwargs["env"]))

    def test_ac3_duplicate_busy_ping_returns_409_and_does_not_launch_twice(self):
        server = _load_server()
        first, first_response = self._handler(server, {"role": "coordinator"})
        second, second_response = self._handler(server, {"role": "designer"})

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            script = root / "jarvis-agent-pipeline"
            script.write_text("#!/bin/zsh\nexit 0\n", encoding="utf-8")
            script.chmod(0o700)
            project = root / "jarvis"
            project.mkdir()
            proc = MagicMock(pid=4321)
            proc.poll.return_value = None
            with (
                patch.object(server, "JARVIS_PIPELINE_SCRIPT", script),
                patch.object(server, "JARVIS_PIPELINE_REPORT_DIR", root / "reports"),
                patch.object(server, "JARVIS_PIPELINE_LOG_FILE", root / "ping.log"),
                patch.object(server, "JARVIS_PROJECTS", {"jarvis": project}),
                patch.object(server.subprocess, "Popen", return_value=proc) as popen,
            ):
                self._invoke(first)
                self._invoke(second)

        self.assertEqual(first_response["status"], 202)
        self.assertEqual(second_response["status"], 409)
        self.assertNotIn(tmp, str(second_response["payload"]))
        popen.assert_called_once()


class JarvisSingleRolePingScriptTests(unittest.TestCase):
    def test_codex_binary_prefers_explicit_override_then_executable_user_install(self):
        source = PIPELINE_PATH.read_text(encoding="utf-8")
        self.assertRegex(
            source,
            re.compile(
                r'if\s+\[\[\s+-n\s+"\$\{JARVIS_CODEX_BIN:-\}"\s+\]\];\s*then\s*'
                r'CODEX_BIN="\$JARVIS_CODEX_BIN"\s*'
                r'elif\s+\[\[\s+-x\s+"\$HOME/\.local/bin/codex"\s+\]\];\s*then\s*'
                r'CODEX_BIN="\$HOME/\.local/bin/codex"\s*'
                r'else\s*'
                r'CODEX_BIN="/Applications/Codex\.app/Contents/Resources/codex"\s*'
                r'fi',
                re.DOTALL,
            ),
            "Codex resolution must prefer an explicit override, then an executable "
            "user install, before the bundled app fallback",
        )
        self.assertRegex(
            source,
            re.compile(
                r'if\s+\[\[\s+!\s+-x\s+"\$CODEX_BIN"\s+\]\].*?'
                r'PROVIDER_FAILED=codex.*?return\s+127',
                re.DOTALL,
            ),
            "an unavailable selected binary must still fail closed before execution",
        )

        zsh_bin = shutil.which("zsh")
        if zsh_bin is None:
            return

        config_end = source.index('CODEX_APPROVAL_POLICY="')
        config_end = source.index("\n", config_end) + 1
        config_script = source[:config_end] + '\nprint -r -- "$CODEX_BIN"\n'

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            home = root / "home"
            user_codex = home / ".local" / "bin" / "codex"
            override_codex = root / "explicit-codex"
            report_dir = root / "reports"
            project_dir = root / "project"
            script = root / "resolve-codex.zsh"
            for executable in (user_codex, override_codex):
                executable.parent.mkdir(parents=True, exist_ok=True)
                executable.write_text(f"#!{zsh_bin}\nexit 0\n", encoding="utf-8")
                executable.chmod(0o700)
            project_dir.mkdir()
            script.write_text(config_script, encoding="utf-8")

            base_env = os.environ.copy()
            base_env.pop("JARVIS_CODEX_BIN", None)
            base_env.update(
                HOME=str(home),
                JARVIS_AGENT_ENV_FILE=str(root / "missing-agent.env"),
                JARVIS_AGENT_REPORT_DIR=str(report_dir),
                JARVIS_PROJECT_DIR=str(project_dir),
            )

            default_result = subprocess.run(
                [zsh_bin, str(script), "read-only ping"],
                env=base_env,
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertEqual(default_result.stdout.strip(), str(user_codex))

            override_result = subprocess.run(
                [zsh_bin, str(script), "read-only ping"],
                env={**base_env, "JARVIS_CODEX_BIN": str(override_codex)},
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertEqual(override_result.stdout.strip(), str(override_codex))

            user_codex.chmod(0o600)
            fallback_result = subprocess.run(
                [zsh_bin, str(script), "read-only ping"],
                env=base_env,
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                fallback_result.stdout.strip(),
                "/Applications/Codex.app/Contents/Resources/codex",
            )

    def test_ac3_script_has_fail_closed_single_role_ping_path_before_full_route(self):
        source = PIPELINE_PATH.read_text(encoding="utf-8")

        self.assertIn("JARVIS_AGENT_PING_ROLE", source)
        self.assertRegex(
            source,
            r"PING_ROLE=.*\$\{JARVIS_AGENT_PING_ROLE:-\}",
        )
        self.assertRegex(
            source,
            re.compile(
                r"case\s+\"?\$\{?PING_ROLE\}?\"?\s+in.*?"
                r"coordinator\|researcher\|builder\|designer\|infrastructure\|vault\|analyst"
                r".*?\*\).*?exit\s+2",
                re.DOTALL,
            ),
        )
        ping_start = source.index("JARVIS_AGENT_PING_ROLE")
        full_route_start = source.index('SUPERVISOR_SYSTEM="')
        self.assertLess(ping_start, full_route_start)
        ping_path = source[ping_start:full_route_start]
        self.assertRegex(ping_path, r"run_agent_role\s+\"?\$\{?PING_ROLE\}?\"?")
        self.assertRegex(ping_path.lower(), r"read[- ]only|не меняй")
        self.assertRegex(ping_path.lower(), r"pong|на связи")
        self.assertRegex(ping_path, r"append_result\s+\"done\"")
        self.assertRegex(ping_path, r"exit\s+0")
        self.assertNotIn("Supervisor -> Builder -> Tester", ping_path)


if __name__ == "__main__":
    unittest.main()
