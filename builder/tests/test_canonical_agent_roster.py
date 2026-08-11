from __future__ import annotations

import importlib.util
import re
import sys
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


BUILDER_DIR = Path(__file__).resolve().parents[1]
HTML_PATH = BUILDER_DIR / "mac-mini-dashboard" / "index.html"
SERVER_PATH = BUILDER_DIR / "dashboard-server-m4.py"
PIPELINE_PATH = BUILDER_DIR / "jarvis-agent-pipeline"

if str(BUILDER_DIR) not in sys.path:
    sys.path.insert(0, str(BUILDER_DIR))


CANONICAL_ROSTER = (
    ("COORDINATOR", "Главный координатор", "Центр управления", "coordinator"),
    ("RESEARCHER", "Исследователь", "Sales", "researcher"),
    ("BUILDER", "Разработчик", "Development", "builder"),
    ("DESIGNER", "Дизайнер", "Design", "designer"),
    (
        "INFRASTRUCTURE",
        "Инженер инфраструктуры",
        "Infrastructure",
        "infrastructure",
    ),
    ("VAULT", "Хранитель знаний", "Internal", "vault"),
    ("ANALYST", "Аналитик", "Finance", "analyst"),
)
CANONICAL_AGENT_IDS = tuple(record[0] for record in CANONICAL_ROSTER)
CANONICAL_PING_ROLES = tuple(record[3] for record in CANONICAL_ROSTER)
LEGACY_ALIASES = (
    "supervisor",
    "tester",
    "editor",
    "planner",
    "devops",
    "bridge",
    "comms",
)
PUBLIC_STATUS_COPY = {
    "queued": "в очереди",
    "active": "работает",
    "testing": "проверяет",
    "waiting": "ждёт решения",
    "done": "готово",
    "failed": "ошибка",
}
PRIVATE_EVENT_FIELDS = {
    "task",
    "task_id",
    "project",
    "role",
    "prompt",
    "body",
    "tool_output",
    "credentials",
    "path",
    "private_url",
    "provider_output",
    "result",
    "result_summary",
    "next_step",
}


def _load_server():
    spec = importlib.util.spec_from_file_location(
        f"dashboard_server_m4_canonical_roster_{id(object())}", SERVER_PATH
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
        re.finditer(
            rf"{re.escape(selector)}\s*\{{(?P<body>[^}}]*)\}}",
            css,
            re.DOTALL,
        )
    )
    return matches[-1].group("body") if matches else ""


def _first_rule(css: str, selector: str) -> str:
    match = re.search(
        rf"{re.escape(selector)}\s*\{{(?P<body>[^}}]*)\}}",
        css,
        re.DOTALL,
    )
    return match.group("body") if match else ""


def _shell_function_source(source: str, name: str) -> str:
    match = re.search(rf"(?m)^{re.escape(name)}\s*\(\)\s*\{{\s*$", source)
    if match is None:
        return ""
    end = re.search(r"(?m)^\}\s*$", source[match.end() :])
    return source[match.start() : match.end() + end.end()] if end else source[match.start() :]


class _RosterCardParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.cards: list[dict[str, object]] = []
        self._card: dict[str, object] | None = None
        self._div_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {key: value or "" for key, value in attrs}
        classes = set(attributes.get("class", "").split())
        if self._card is None:
            if tag == "div" and "jarvis-pipeline-role" in classes:
                self._card = {"attrs": attributes, "children": [], "text": []}
                self._div_depth = 1
            return

        if tag == "div":
            self._div_depth += 1
        children = self._card["children"]
        assert isinstance(children, list)
        children.append((tag, attributes))

    def handle_endtag(self, tag: str) -> None:
        if self._card is None or tag != "div":
            return
        self._div_depth -= 1
        if self._div_depth == 0:
            text = self._card["text"]
            assert isinstance(text, list)
            self._card["text"] = " ".join(" ".join(text).split())
            self.cards.append(self._card)
            self._card = None

    def handle_data(self, data: str) -> None:
        if self._card is None or not data.strip():
            return
        text = self._card["text"]
        assert isinstance(text, list)
        text.append(data.strip())


class CanonicalAgentRosterMarkupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.html = HTML_PATH.read_text(encoding="utf-8")
        parser = _RosterCardParser()
        parser.feed(cls.html)
        cls.cards = parser.cards

    def test_ac1_exact_verified_team_is_persistent_localized_and_idle(self):
        self.assertEqual(
            tuple(card["attrs"].get("data-jarvis-agent-id") for card in self.cards),
            CANONICAL_AGENT_IDS,
            "the compact roster must contain exactly the seven campus residents once",
        )
        self.assertEqual(len(self.cards), 7)

        for card, (agent_id, name, department, role) in zip(self.cards, CANONICAL_ROSTER):
            with self.subTest(agent_id=agent_id):
                attrs = card["attrs"]
                text = str(card["text"])
                self.assertEqual(attrs.get("data-jarvis-agent-id"), agent_id)
                self.assertEqual(attrs.get("data-role"), role)
                self.assertEqual(attrs.get("data-jarvis-agent-department"), department)
                self.assertIn(name, text)
                self.assertIn(department, text)
                self.assertIn("ожидает задач", text)

                children = card["children"]
                buttons = [attrs for tag, attrs in children if tag == "button"]
                self.assertEqual(len(buttons), 1)
                self.assertEqual(buttons[0].get("type"), "button")
                self.assertEqual(buttons[0].get("data-jarvis-ping-role"), role)
                self.assertEqual(
                    buttons[0].get("aria-describedby"), f"jarvis-{role}-status"
                )

        permanent_text = " ".join(str(card["text"]) for card in self.cards)
        self.assertNotIn("Supervisor", permanent_text)
        self.assertNotIn("Tester", permanent_text)

    def test_ac2_exact_manager_projection_drives_only_safe_status_copy(self):
        html = self.html
        self.assertTrue(
            "/api/manager/departments" in html,
            "roster must read the privacy-safe department projection",
        )
        self.assertTrue(
            "JARVIS_DEPARTMENTS_API" in html,
            "department projection endpoint needs a dedicated read-only client constant",
        )
        self.assertRegex(
            html,
            r"fetch\(\s*JARVIS_DEPARTMENTS_API[\s\S]{0,240}cache\s*:\s*['\"]no-store['\"]",
        )

        render = _function_source(html, "renderJarvisAgentRoster")
        self.assertTrue(render, "the roster needs one fail-closed projection renderer")
        self.assertIn("event.agent_id", render)
        self.assertIn("event.status", render)
        self.assertNotRegex(render, r"event\.(?:role|alias|name)\b")
        for status, visible in PUBLIC_STATUS_COPY.items():
            with self.subTest(status=status):
                self.assertIn(status, render)
                self.assertIn(visible, render)

        referenced_fields = set(re.findall(r"\bevent\.([A-Za-z_$][A-Za-z0-9_$]*)", render))
        self.assertTrue(referenced_fields)
        self.assertFalse(
            referenced_fields & PRIVATE_EVENT_FIELDS,
            "the roster may consume identity and status only, never private task content",
        )
        self.assertNotIn("innerHTML", render)

    def test_ac2_ec1_unknown_duplicate_malformed_stale_and_unavailable_fail_closed(self):
        render = _function_source(self.html, "renderJarvisAgentRoster")
        self.assertTrue(render)
        self.assertRegex(render, r"resetJarvisAgentRoster\s*\(")
        reset_index = render.index("resetJarvisAgentRoster")
        active_guard = re.search(
            r"(?:data|payload)(?:\?\.|\.)state\s*!==?\s*['\"]active['\"]",
            render,
        )
        self.assertIsNotNone(
            active_guard,
            "empty/stale/unavailable/malformed payloads must leave all seven cards idle",
        )
        self.assertLess(reset_index, active_guard.start())
        self.assertRegex(render, r"Array\.isArray\([^)]*\.events\)")
        self.assertRegex(render, r"new\s+Set\s*\(")
        self.assertRegex(render, r"\.has\(\s*agentId\s*\)")
        self.assertRegex(render, r"\.add\(\s*agentId\s*\)")
        self.assertRegex(render, r"(?:card|agentCard)\s*=[\s\S]{0,200}?agentId")
        self.assertRegex(render, r"if\s*\(\s*!\s*(?:card|agentCard)\s*\)\s*(?:continue|return)")
        self.assertRegex(render, r"(?:allowed|public|status)[A-Za-z_$]*\.has\(\s*status\s*\)")

        reset = _function_source(self.html, "resetJarvisAgentRoster")
        self.assertIn("ожидает задач", reset)
        self.assertRegex(reset, r"idle|pending")

    def test_ac3_every_card_has_one_44px_native_ping_and_exact_client_allowlist(self):
        roles = tuple(
            child_attrs["data-jarvis-ping-role"]
            for card in self.cards
            for child_tag, child_attrs in card["children"]
            if child_tag == "button" and "data-jarvis-ping-role" in child_attrs
        )
        self.assertEqual(roles, CANONICAL_PING_ROLES)

        button_rule = _last_rule(self.html, ".jarvis-ping-button")
        min_height = re.search(r"min-height\s*:\s*(\d+)px", button_rule)
        min_width = re.search(r"min-width\s*:\s*(\d+)px", button_rule)
        self.assertIsNotNone(min_height)
        self.assertIsNotNone(min_width)
        self.assertGreaterEqual(int(min_height.group(1)), 44)
        self.assertGreaterEqual(int(min_width.group(1)), 44)

        ping = _function_source(self.html, "pingJarvisAgent")
        client_allowlist = re.search(
            r"\[(?P<roles>(?:\s*['\"][a-z]+['\"]\s*,?)+)\]\.includes\(role\)",
            ping,
        )
        self.assertIsNotNone(client_allowlist)
        self.assertEqual(
            tuple(re.findall(r"['\"]([a-z]+)['\"]", client_allowlist.group("roles"))),
            CANONICAL_PING_ROLES,
        )
        for legacy in LEGACY_ALIASES:
            self.assertNotIn(f"'{legacy}'", client_allowlist.group("roles"))

        accepted = ping.find("response.ok")
        checking = ping.find("'checking'")
        if checking < 0:
            checking = ping.find('"checking"')
        self.assertGreaterEqual(accepted, 0)
        self.assertGreater(checking, accepted)
        poll = _function_source(self.html, "pollJarvisAgentPing")
        self.assertRegex(
            poll,
            r"data\.run_id\s*!==?\s*runId\s*\|\|\s*data\.role\s*!==?\s*role",
        )
        self.assertRegex(
            poll,
            re.compile(r"(?:done|completed)[\s\S]{0,240}?['\"]online['\"]"),
        )

    def test_ac4_desktop_4_plus_3_intermediate_3_and_mobile_2_column_geometry(self):
        desktop = _first_rule(self.html, ".jarvis-pipeline-role-strip")
        self.assertRegex(
            desktop,
            r"grid-template-columns\s*:\s*repeat\(4,\s*minmax\(0,\s*1fr\)\)",
            "wide desktop must wrap seven cards as 4+3 so Russian copy has a readable lane",
        )
        self.assertRegex(desktop, r"min-width\s*:\s*0")

        self.assertRegex(
            self.html,
            re.compile(
                r"@media\s*\(max-width:\s*(?:1200|1100|1024|900|880|840|800|760)px\)"
                r"[\s\S]{0,1800}?\.jarvis-pipeline-role-strip\s*\{[^}]*"
                r"grid-template-columns\s*:\s*repeat\(3,\s*minmax\(0,\s*1fr\)\)",
                re.DOTALL,
            ),
        )

        mobile_start = self.html.rfind("@media (max-width: 640px)")
        self.assertGreaterEqual(mobile_start, 0)
        mobile_end = self.html.find("@media", mobile_start + 1)
        mobile = self.html[mobile_start : mobile_end if mobile_end >= 0 else len(self.html)]
        self.assertRegex(
            mobile,
            r"\.jarvis-pipeline-role-strip\s*\{[^}]*grid-template-columns\s*:"
            r"\s*repeat\(2,\s*minmax\(0,\s*1fr\)\)",
        )
        self.assertNotRegex(
            self.html,
            r"\.jarvis-(?:pipeline-role-strip|pipeline-role)[^{]*\{[^}]*"
            r"overflow-x\s*:\s*(?:auto|scroll)",
        )
        self.assertRegex(
            self.html,
            r"\.jarvis-pipeline-role\s*\{[^}]*min-width\s*:\s*0",
        )

        name_rule = _last_rule(self.html, ".jarvis-pipeline-compact .jarvis-flow-step-name")
        self.assertRegex(name_rule, r"white-space\s*:\s*normal")
        self.assertRegex(name_rule, r"(?:overflow-wrap\s*:\s*anywhere|word-break\s*:\s*break-word)")
        self.assertNotRegex(name_rule, r"text-overflow\s*:\s*ellipsis")

    def test_ac4_mobile_card_preserves_copy_lane_and_moves_ping_to_full_second_row(self):
        mobile_start = self.html.rfind("@media (max-width: 640px)")
        self.assertGreaterEqual(mobile_start, 0)
        mobile_end = self.html.find("@media", mobile_start + 1)
        mobile = self.html[mobile_start : mobile_end if mobile_end >= 0 else len(self.html)]

        card = re.search(
            r"\.jarvis-pipeline-role\s*\{(?P<body>[^}]*)\}",
            mobile,
            re.DOTALL,
        )
        button = re.search(
            r"\.jarvis-ping-button\s*\{(?P<body>[^}]*)\}",
            mobile,
            re.DOTALL,
        )
        roomy_first_row = bool(
            card
            and re.search(
                r"grid-template-columns\s*:\s*(?:38px|auto|min-content)\s+"
                r"minmax\(0,\s*1fr\)\s*;",
                card.group("body"),
            )
            and "52px" not in card.group("body")
        )
        full_second_row = bool(
            button
            and re.search(
                r"grid-column\s*:\s*(?:1\s*/\s*-1|1\s*/\s*span\s+2|span\s+2)",
                button.group("body"),
            )
        )
        self.assertTrue(
            roomy_first_row and full_second_row,
            "mobile cards need a readable sprite+copy row and a full-width ping row",
        )

    def test_ac4_keyboard_disabled_error_and_reduced_motion_remain_explicit(self):
        self.assertRegex(self.html, r"\.jarvis-ping-button:focus-visible\s*\{")
        self.assertRegex(self.html, r"\.jarvis-ping-button:disabled\s*\{")
        self.assertRegex(
            self.html,
            r"@media\s*\(prefers-reduced-motion:\s*reduce\)[\s\S]*?"
            r"\.jarvis-ping-button[\s\S]*?animation\s*:\s*none\s*!important",
        )
        for visible in ("проверяем…", "на связи", "не отвечает · ошибка"):
            self.assertIn(visible, self.html)

    def test_ac5_github_history_contract_is_unchanged_safe_and_concise(self):
        self.assertNotRegex(
            self.html,
            r'<details\s+class="jarvis-history-panel"[^>]*\sopen(?:\s|>)',
        )
        history = _function_source(self.html, "renderJarvisHistory")
        self.assertRegex(history, r"items\.slice\(0,\s*5\)")
        self.assertIn("safeGitHubHistoryUrl(item.url)", history)
        self.assertIn("result_summary", history)
        self.assertIn("freshness", history)
        self.assertNotIn("report_tail", history)

        safe_url = _function_source(self.html, "safeGitHubHistoryUrl")
        self.assertRegex(safe_url, r"\.protocol\s*===\s*['\"]https:['\"]")
        self.assertRegex(safe_url, r"\.hostname\s*===\s*['\"]github\.com['\"]")
        self.assertIn('rel="noopener noreferrer"', history)


class CanonicalAgentPingBoundaryTests(unittest.TestCase):
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

    def test_ac3_err1_server_allowlist_is_exactly_the_seven_canonical_roles(self):
        server = _load_server()
        self.assertEqual(tuple(sorted(server.JARVIS_PING_ROLES)), tuple(sorted(CANONICAL_PING_ROLES)))
        self.assertTrue(set(LEGACY_ALIASES).isdisjoint(server.JARVIS_PING_ROLES))

    def test_ac3_safe_status_response_is_role_exact_and_path_free(self):
        server = _load_server()
        with tempfile.TemporaryDirectory() as tmp:
            report_dir = Path(tmp)
            run_id = "ping-infrastructure-20260812-000000-abc123"
            report_path = report_dir / f"{run_id}.md"
            report_path.write_text("# private report", encoding="utf-8")
            handler = server.Handler.__new__(server.Handler)
            response: dict[str, object] = {}
            handler._require_dashboard_run_auth = MagicMock(return_value=True)
            handler._json_response = lambda status, payload: response.update(
                status=status, payload=payload
            )
            raw = {
                "status": "done",
                "result_summary": "PONG",
                "updated_at": "2026-08-12T00:00:00Z",
                "report_path": str(report_path),
                "report_tail": "secret provider output /Users/private/vault",
                "steps": [{"prompt": "private"}],
            }
            with (
                patch.object(server, "JARVIS_PIPELINE_REPORT_DIR", report_dir),
                patch.object(server, "_pipeline_report_payload", return_value=raw),
                patch.object(server, "_jarvis_ping_role", return_value="infrastructure"),
            ):
                handler._handle_jarvis_pipeline_status(SimpleNamespace(query=f"run_id={run_id}"))

        self.assertEqual(response["status"], 200)
        payload = response["payload"]
        self.assertEqual(
            tuple(payload),
            ("exists", "run_id", "role", "status", "result_summary", "updated_at"),
        )
        self.assertEqual(payload["role"], "infrastructure")
        self.assertNotIn(tmp, repr(payload))
        self.assertNotRegex(repr(payload), r"/(?:Users|private|tmp)/")

    def test_ac3_err2_shell_allowlist_and_selected_pong_path_are_exact(self):
        source = PIPELINE_PATH.read_text(encoding="utf-8")
        allowlist = re.search(
            r'case\s+"\$PING_ROLE"\s+in\s*\n\s*(?P<roles>[a-z|]+)\|?""\)\s*;;',
            source,
        )
        self.assertIsNotNone(allowlist)
        self.assertEqual(tuple(allowlist.group("roles").strip("|").split("|")), CANONICAL_PING_ROLES)
        for legacy in LEGACY_ALIASES:
            self.assertNotIn(legacy, allowlist.group("roles").split("|"))

        ping_start = source.index('if [[ -n "$PING_ROLE" ]]')
        ping_end = source.index('if [[ "$TASK_HAS_SECRET"', ping_start)
        ping_path = source[ping_start:ping_end]
        self.assertRegex(ping_path, r'run_agent_role\s+"\$PING_ROLE"')
        self.assertIn("ping_output_valid", ping_path)
        self.assertRegex(ping_path, r"append_result\s+\"done\"")
        self.assertRegex(ping_path, r"exit\s+0")
        self.assertNotIn("SUPERVISOR_OUTPUT=", ping_path)
        self.assertNotIn("TESTER_OUTPUT=", ping_path)

        validator = _shell_function_source(source, "ping_output_valid")
        self.assertRegex(validator, r"PONG")
        self.assertIn("role_output_failed", validator)
        self.assertRegex(ping_path.lower(), r"read[- ]only|не меняй")
        for _, title, _, role in CANONICAL_ROSTER:
            with self.subTest(role=role):
                self.assertRegex(
                    ping_path,
                    rf"{role}\)\s*PING_TITLE=\"{re.escape(title)}\"",
                )


if __name__ == "__main__":
    unittest.main()
