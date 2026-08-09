from __future__ import annotations

from datetime import datetime, timedelta, timezone
import importlib
from pathlib import Path
import re
import subprocess
import threading
import unicodedata
import unittest
from unittest.mock import patch
import urllib.request


NOW = datetime(2026, 8, 8, 12, 0, tzinfo=timezone.utc)
BUILDER_DIR = Path(__file__).resolve().parents[1]
ASSETS_DIR = BUILDER_DIR / "dashboard-assets"
CANONICAL_DEPARTMENTS = (
    "hq",
    "sales",
    "development",
    "design",
    "infrastructure",
    "internal",
    "finance",
)
TOP_LEVEL_FIELDS = (
    "state",
    "generated_at",
    "visible_task_count",
    "omitted_task_count",
    "events",
    "privacy",
)
# The locked spec explicitly names these 13 fields. No unlisted fourteenth field
# may be inferred merely from the prose's inconsistent field count.
PUBLIC_EVENT_FIELDS = (
    "event_id",
    "task_id",
    "department_id",
    "department_label",
    "project",
    "agent_id",
    "role",
    "status",
    "updated_at",
    "next_step",
    "evidence_count",
    "ephemeral",
    "zone_id",
)


class DepartmentCampusContractTests(unittest.TestCase):
    def setUp(self):
        try:
            self.campus = importlib.import_module("dashboard_builder.department_campus")
        except Exception as exc:  # discovery must enumerate the complete RED suite
            self.fail(
                "RED: missing public dashboard_builder.department_campus contract "
                f"({type(exc).__name__}: {exc})"
            )

        required = (
            "DEPARTMENT_ZONES",
            "department_campus_projection",
            "build_department_campus_html",
        )
        missing = [name for name in required if not hasattr(self.campus, name)]
        if missing:
            self.fail(f"RED: missing department campus exports: {', '.join(missing)}")

    def _zones(self):
        zones = self.campus.DEPARTMENT_ZONES
        self.assertIsInstance(zones, dict, "DEPARTMENT_ZONES must be an id-keyed registry")
        return zones

    def _event(self, department_id="development", **overrides):
        zone = self._zones()[department_id]
        roles = zone.get("roles", ())
        self.assertTrue(roles, f"{department_id} must declare at least one public role")
        payload = {
            "event_id": "evt-001",
            "task_id": "task-001",
            "department_id": department_id,
            "department_label": zone["label"],
            "project": "Public Project",
            "agent_id": "agent-001",
            "role": roles[0],
            "status": "active",
            "updated_at": "2026-08-08T11:55:00Z",
            "next_step": "Review safe evidence",
            "evidence_count": 2,
            "ephemeral": True,
            "zone_id": zone["zone_id"],
        }
        payload.update(overrides)
        return payload

    def _project(self, events, **kwargs):
        return self.campus.department_campus_projection(events, now=NOW, **kwargs)

    def _css(self):
        return (ASSETS_DIR / "style.css").read_text(encoding="utf-8")

    def _script(self):
        return (ASSETS_DIR / "script.js").read_text(encoding="utf-8")

    def _campus_script(self):
        script = self._script()
        start_marker = "// ── Department Campus ──"
        end_marker = "// ── End Department Campus ──"
        self.assertIn(start_marker, script)
        self.assertIn(end_marker, script)
        start = script.index(start_marker)
        end = script.index(end_marker, start + len(start_marker))
        return script[start:end]

    def test_ac_1_registry_has_exactly_seven_canonical_zones_and_finance_boundary(self):
        zones = self._zones()
        self.assertEqual(tuple(zones), CANONICAL_DEPARTMENTS)
        self.assertEqual(len(zones), 7)
        self.assertEqual(len({zone["zone_id"] for zone in zones.values()}), 7)
        for department_id, zone in zones.items():
            with self.subTest(department_id=department_id):
                self.assertIsInstance(zone.get("label"), str)
                self.assertTrue(zone["label"].strip())
                self.assertTrue(zone.get("roles"))
                self.assertEqual(bool(zone.get("owner_permission_boundary")), department_id == "finance")

        unknown = self._event(department_id="sales")
        unknown["department_id"] = "legal"
        projected = self._project([unknown])
        self.assertEqual(projected["events"], [])
        self.assertEqual(tuple(self._zones()), CANONICAL_DEPARTMENTS)

    def test_ac_2_read_only_surface_exposes_no_owner_or_mutation_controls(self):
        html = self.campus.build_department_campus_html()
        script = self._script()
        self.assertNotRegex(html, r"<(?:input|textarea|select|form)\b")
        self.assertNotRegex(html, r"\bmethod=[\"']?post\b")
        self.assertNotRegex(
            html,
            r"data-(?:action|campus-action)=[\"'](?:dispatch|merge|deploy|credential|pair|"
            r"payment|publish|delete)",
        )
        self.assertIn("/api/manager/departments", script)
        self.assertRegex(script, r"fetch\([^)]*/api/manager/departments")
        self.assertNotRegex(script, r"fetch\([^)]*/api/manager/departments[^)]*\bPOST\b")

    def test_ac_4_status_text_and_motion_allowlist_are_explicit_and_accessible(self):
        expected = {
            "queued": "в очереди",
            "active": "работает",
            "testing": "проверяет",
            "waiting": "ждёт решения",
            "done": "готово",
            "failed": "ошибка",
        }
        html = self.campus.build_department_campus_html()
        script = self._script()
        for raw, visible in expected.items():
            with self.subTest(status=raw):
                projected = self._project([self._event(status=raw)])
                self.assertEqual(projected["events"][0]["status"], raw)
                self.assertIn(visible, html + script)
        self.assertIn("active", script)
        self.assertIn("testing", script)
        for nonmoving in ("queued", "waiting", "done", "failed"):
            self.assertIn(nonmoving, script)
        self.assertIn("aria-live", html)

    def test_ac_5_ec_2_lane_limit_is_clamped_to_zero_through_three_with_honest_counts(self):
        events = [
            self._event(
                event_id=f"evt-{index}",
                task_id=f"task-{index}",
                agent_id=f"agent-{index}",
            )
            for index in range(5)
        ]
        support = self._event(
            department_id="design",
            event_id="evt-support",
            task_id="task-0",
            agent_id="agent-support",
        )
        for requested, visible, omitted in ((-4, 0, 5), (0, 0, 5), (2, 2, 3), (99, 3, 2)):
            with self.subTest(max_tasks=requested):
                projected = self._project(events + [support], max_tasks=requested)
                self.assertEqual(projected["visible_task_count"], visible)
                self.assertEqual(projected["omitted_task_count"], omitted)
                self.assertLessEqual(len({item["task_id"] for item in projected["events"]}), visible)
        capped = self._project(events + [support], max_tasks=99)
        self.assertIn("agent-support", {item["agent_id"] for item in capped["events"]})

    def test_ac_6_ec_4_registry_mismatches_are_rejected_and_support_stays_in_own_zone(self):
        valid_support = self._event(department_id="design", agent_id="support-agent")
        projected = self._project([valid_support])
        self.assertEqual(projected["events"][0]["department_id"], "design")
        self.assertEqual(projected["events"][0]["zone_id"], self._zones()["design"]["zone_id"])

        for field, bad_value in (
            ("department_id", "unknown"),
            ("department_label", "Wrong Department"),
            ("zone_id", "hq"),
            ("role", "unregistered-role"),
        ):
            with self.subTest(field=field):
                event = self._event()
                event[field] = bad_value
                self.assertEqual(self._project([event])["events"], [])

    def test_ac_7_ec_1_empty_stale_unavailable_states_have_no_synthetic_specialists(self):
        empty = self._project([])
        self.assertEqual(tuple(empty), TOP_LEVEL_FIELDS)
        self.assertEqual(empty["state"], "empty")
        self.assertEqual(empty["visible_task_count"], 0)
        self.assertEqual(empty["omitted_task_count"], 0)
        self.assertEqual(empty["events"], [])
        self.assertEqual(empty["privacy"], "public_projection")

        stale_event = self._event(updated_at=(NOW - timedelta(minutes=31)).isoformat())
        stale = self._project([stale_event])
        self.assertEqual(stale["state"], "stale")
        self.assertEqual(stale["events"], [])

        unavailable = self._project(None)
        self.assertEqual(unavailable["state"], "unavailable")
        self.assertEqual(unavailable["events"], [])

        html = self.campus.build_department_campus_html()
        self.assertEqual(html.count('data-campus-static-manager="true"'), 1)

    def test_ac_8_err_4_public_event_and_detail_shapes_are_strict_allowlists(self):
        payload = self._event(
            prompt="<private-prompt>",
            result="<tool-output>",
            error="<credential>",
            messages=[{"body": "<private-message>"}],
            evidence=[{"body": "<evidence-text>"}],
            metadata={"path": "/Users/private/vault", "token": "secret-token"},
        )
        projected = self._project([payload])
        self.assertEqual(tuple(projected), TOP_LEVEL_FIELDS)
        self.assertEqual(tuple(projected["events"][0]), PUBLIC_EVENT_FIELDS)
        rendered = repr(projected)
        for forbidden in (
            "<private-prompt>",
            "<tool-output>",
            "<credential>",
            "<private-message>",
            "<evidence-text>",
            "/Users/private/vault",
            "secret-token",
        ):
            self.assertNotIn(forbidden, rendered)

        html = self.campus.build_department_campus_html()
        script = self._campus_script()
        detail_fields = re.findall(r'data-campus-detail-field=["\']([^"\']+)', html)
        self.assertEqual(
            detail_fields,
            [
                "task_id",
                "department",
                "project",
                "role",
                "status",
                "updated_at",
                "next_step",
                "result",
                "evidence_count",
            ],
        )
        self.assertIn("textContent", script)
        self.assertNotRegex(script, r"innerHTML\s*=\s*(?:event|agent|details|value)")

    def test_ac_9_agent_triggers_have_keyboard_touch_and_focus_return_contract(self):
        html = self.campus.build_department_campus_html()
        script = self._script()
        css = self._css()
        self.assertRegex(script, r"createElement\([\"']button[\"']\)")
        self.assertIn("data-campus-agent-trigger", script)
        self.assertIn("aria-label", script)
        self.assertIn("aria-controls", script)
        self.assertIn("aria-expanded", script)
        self.assertRegex(html, r"<button\b[^>]*data-campus-detail-close")
        self.assertIn("Escape", script)
        self.assertIn("focus()", script)
        self.assertRegex(css, r"min-width:\s*44px")
        self.assertRegex(css, r"min-height:\s*44px")
        self.assertNotIn("mouseenter", script)

    def test_ac_9_enter_and_space_explicitly_open_the_same_drawer_and_escape_returns_focus(self):
        script = self._campus_script()

        self.assertRegex(
            script,
            r"\b[A-Za-z_$][A-Za-z0-9_$]*\.key[\s\S]{0,80}[\"']Enter[\"']",
        )
        self.assertRegex(
            script,
            r"\b[A-Za-z_$][A-Za-z0-9_$]*\.key[\s\S]{0,80}"
            r"[\"'](?: |Space|Spacebar)[\"']",
        )
        self.assertRegex(
            script,
            r"(?:Enter|Spacebar|[\"'] [\"'])[\s\S]{0,500}"
            r"(?:openCampusDetails\(|\.click\(\))",
        )
        self.assertRegex(
            script,
            r"Escape[\s\S]{0,300}closeCampusDetails\(\s*true\s*\)",
        )
        self.assertIn("preventDefault()", script)

    def test_ac_10_reduced_motion_disables_animation_transitions_and_frame_loop(self):
        css = self._css()
        script = self._script()
        reduced_start = css.rfind("@media (prefers-reduced-motion: reduce)")
        self.assertGreaterEqual(reduced_start, 0)
        reduced = css[reduced_start:]
        self.assertIn("animation: none", reduced)
        self.assertIn("transition: none", reduced)
        if "requestAnimationFrame" in script:
            self.assertRegex(script, r"matchMedia\([^)]*prefers-reduced-motion: reduce")

    def test_ac_11_ec_7_all_ui_states_clear_agents_and_keep_seven_zones(self):
        html = self.campus.build_department_campus_html()
        script = self._script()
        for message in (
            "Нет активных задач",
            "Нет свежих данных",
            "Данные временно недоступны",
        ):
            self.assertIn(message, html + script)
        self.assertIn("aria-live", html)
        self.assertIn("replaceChildren", script)
        for department_id in CANONICAL_DEPARTMENTS:
            self.assertEqual(html.count(f'data-department-id="{department_id}"'), 1)

    def test_ac_12_ec_3_ec_9_freshness_and_dedup_choose_newest_with_stable_ties(self):
        boundary = self._event(updated_at=(NOW - timedelta(minutes=30)).isoformat())
        self.assertEqual(self._project([boundary])["state"], "active")

        duplicate = self._event()
        self.assertEqual(len(self._project([duplicate, dict(duplicate)])["events"]), 1)

        older = self._event(project="Older", updated_at="2026-08-08T11:50:00Z")
        newer = self._event(event_id="evt-new", project="Newer", updated_at="2026-08-08T11:59:00Z")
        self.assertEqual(self._project([older, newer])["events"][0]["project"], "Newer")

        first = self._event(event_id="evt-first", project="First")
        tied = self._event(event_id="evt-tied", project="Second")
        self.assertEqual(self._project([first, tied])["events"][0]["project"], "First")

    def test_ac_13_projection_and_idle_render_start_no_external_work(self):
        with (
            patch.object(subprocess, "run") as run,
            patch.object(subprocess, "Popen") as popen,
            patch.object(threading.Thread, "start") as thread_start,
            patch.object(urllib.request, "urlopen") as urlopen,
        ):
            empty = self._project([])
            html = self.campus.build_department_campus_html()
            script = self._script()
        self.assertEqual(empty["state"], "empty")
        self.assertIn("department-campus", html)
        start_marker = "// ── Department Campus ──"
        end_marker = "// ── End Department Campus ──"
        self.assertIn(start_marker, script)
        self.assertIn(end_marker, script)
        campus_start = script.index(start_marker)
        campus_end = script.index(end_marker, campus_start + len(start_marker))
        campus_script = script[campus_start:campus_end]
        self.assertNotIn("requestAnimationFrame", campus_script)
        self.assertNotRegex(campus_script, r"\bPOST\b")
        self.assertNotRegex(campus_script, r"\bdispatch\w*\b")
        self.assertNotRegex(campus_script, r"\bmodel\w*\b")
        self.assertNotRegex(campus_script, r"\bbackground\w*\b")
        run.assert_not_called()
        popen.assert_not_called()
        thread_start.assert_not_called()
        urlopen.assert_not_called()

    def test_ec_5_evidence_count_normalizes_bool_negative_and_malformed_to_zero(self):
        for raw in (True, False, -1, -99, "4", "bad", None, 2.5, [], {}):
            with self.subTest(evidence_count=raw):
                event = self._event(evidence_count=raw)
                self.assertEqual(self._project([event])["events"][0]["evidence_count"], 0)
        self.assertEqual(self._project([self._event(evidence_count=4)])["events"][0]["evidence_count"], 4)

    def test_ec_6_err_6_invalid_status_time_or_ephemeral_flag_never_moves_or_displays(self):
        invalid = (
            self._event(status=None),
            self._event(status="unknown"),
            self._event(updated_at="not-a-time"),
            self._event(updated_at=(NOW + timedelta(seconds=1)).isoformat()),
            self._event(ephemeral=False),
            self._event(ephemeral=1),
        )
        for event in invalid:
            with self.subTest(event=event):
                self.assertEqual(self._project([event])["events"], [])

    def test_ec_8_err_3_safe_text_is_bounded_and_secret_or_identity_shapes_fail_closed(self):
        long_unicode = "Проект-" + ("🚀" * 1000)
        projected = self._project([self._event(project=long_unicode)])
        self.assertEqual(len(projected["events"]), 1)
        safe_project = projected["events"][0]["project"]
        self.assertLess(len(safe_project), len(long_unicode))
        safe_project.encode("utf-8")

        unsafe = self._event(
            event_id="evt-secret",
            project="file:///Users/mark/private?token=secret-value",
            next_step="Open /Users/mark/.ssh/id_rsa",
        )
        rendered = repr(self._project([unsafe]))
        self.assertNotIn("/Users/mark", rendered)
        self.assertNotIn("secret-value", rendered)

        high_risk_identity = self._event(agent_id="../../private/token.txt")
        self.assertEqual(self._project([high_risk_identity])["events"], [])

    def test_ac_8_ec_8_private_uris_paths_credentials_and_keys_never_reach_public_text(self):
        high_risk = {
            "sftp": "sftp://operator@private.invalid/CAMPUS_SFTP",
            "postgresql": "postgresql://user:pass@private.invalid/CAMPUS_DB",
            "mysql": "mysql://user:pass@private.invalid/CAMPUS_MYSQL",
            "general_private_uri": "redis://private.invalid/CAMPUS_REDIS",
            "unix_opt": "/opt/private/CAMPUS_UNIX.txt",
            "windows_drive": r"C:\Users\Mark\private\CAMPUS_WINDOWS.txt",
            "unc": r"\\server\share\CAMPUS_UNC.txt",
            "network_relative": "//server/share/CAMPUS_NETWORK.txt",
            "aws_secret": "aws_secret_access_key=CAMPUS_AWS_SECRET_1234567890",
            "client_secret": "client_secret=CAMPUS_CLIENT_SECRET_1234567890",
            "refresh_token": "refresh_token=CAMPUS_REFRESH_TOKEN_1234567890",
            "webhook_secret": "webhook_secret=CAMPUS_WEBHOOK_SECRET_1234567890",
            "session_token": "sessionToken=CAMPUS_SESSION_TOKEN_1234567890",
            "bearer": "Authorization: Bearer CAMPUS_BEARER_1234567890",
            "basic": "Authorization: Basic CAMPUS_BASIC_1234567890",
            "pem": (
                "-----BEGIN PRIVATE KEY----- CAMPUS_PEM_MATERIAL "
                "-----END PRIVATE KEY-----"
            ),
            "stripe": "sk" + "_live_CAMPUS012345678901234567890123",
            "openai": "sk-proj-CAMPUS012345678901234567890123",
            "github": "ghp_CAMPUS012345678901234567890123456",
            "slack": "xoxb-CAMPUS012345678901234567890123456",
            "google": "AIzaCAMPUS012345678901234567890123456",
            "aws_access": "AKIACAMPUSPROBE1234X",
        }

        for field in ("project", "next_step"):
            for shape, value in high_risk.items():
                with self.subTest(field=field, shape=shape):
                    projected = self._project([self._event(**{field: value})])
                    rendered = repr(projected)
                    self.assertNotIn(value, rendered)
                    self.assertNotIn("CAMPUS_", rendered)

        safe_prose = "Document OAuth token rotation policy with the team"
        for field in ("project", "next_step"):
            with self.subTest(field=field, shape="safe_prose"):
                projected = self._project([self._event(**{field: safe_prose})])
                self.assertEqual(projected["events"][0][field], safe_prose)

    def test_ac_8_embedded_relative_and_schemeless_sensitive_text_is_neutral(self):
        sensitive_values = (
            "Open(/Users/mark/private/secret.txt)",
            r"Use(C:\Users\Mark\private\secret.txt)",
            "Open ../private/secret.txt",
            "Open ~/private/secret.txt",
            "token=CAMPUS_GENERIC_TOKEN_1234567890",
            "secret=CAMPUS_GENERIC_SECRET_1234567890",
            "internal.example/private?token=CAMPUS_URL_TOKEN",
        )
        neutral = "Недоступно в публичной сводке"
        for field in ("project", "next_step"):
            for value in sensitive_values:
                with self.subTest(field=field, value=value[:18]):
                    projected = self._project([self._event(**{field: value})])
                    self.assertEqual(len(projected["events"]), 1)
                    self.assertEqual(projected["events"][0][field], neutral)
                    rendered = repr(projected)
                    for marker in (
                        "/Users/mark",
                        "CAMPUS_GENERIC",
                        "CAMPUS_URL_TOKEN",
                        "../private",
                        "~/private",
                        r"C:\Users\Mark",
                    ):
                        self.assertNotIn(marker, rendered)

        safe = "Open the documentation and review token rotation policy"
        projected = self._project([
            self._event(project=safe, next_step=safe),
        ])
        self.assertEqual(projected["events"][0]["project"], safe)
        self.assertEqual(projected["events"][0]["next_step"], safe)

    def test_ac_8_generic_secret_shaped_identity_is_rejected(self):
        for field, value in (
            ("task_id", "token-CAMPUS_GENERIC_TOKEN_1234567890"),
            ("agent_id", "secret-CAMPUS_GENERIC_SECRET_1234567890"),
        ):
            with self.subTest(field=field):
                projected = self._project([self._event(**{field: value})])
                self.assertEqual(projected["events"], [])
                self.assertNotIn("CAMPUS_GENERIC", repr(projected))

    def test_ac_8_hidden_paths_json_jwt_are_neutral_while_public_help_and_safe_ids_survive(self):
        sensitive_values = (
            "Open .ssh/id_rsa",
            "Open config/credentials.json",
            "Visit internal.example/private/dashboard",
            "Visit localhost:7777/private/dashboard",
            r"Open(\\server\share\private.txt)",
            '{"token":"CAMPUS_JSON_TOKEN_1234567890"}',
            "eyJhbGciOiJIUzI1NiJ9.CAMPUS_JWT_PAYLOAD.CAMPUS_JWT_SIGNATURE",
        )
        neutral = "Недоступно в публичной сводке"
        for field in ("project", "next_step"):
            for value in sensitive_values:
                with self.subTest(field=field, value=value[:18]):
                    projected = self._project([self._event(**{field: value})])
                    self.assertEqual(len(projected["events"]), 1)
                    self.assertEqual(projected["events"][0][field], neutral)
                    self.assertNotIn(value, repr(projected))
                    self.assertNotIn("CAMPUS_", repr(projected))

        safe_prose = "Run /help for public documentation"
        with self.subTest(safe_case="public-help-prose"):
            safe_text_event = self._project([
                self._event(project=safe_prose, next_step=safe_prose),
            ])["events"][0]
            self.assertEqual(safe_text_event["project"], safe_prose)
            self.assertEqual(safe_text_event["next_step"], safe_prose)

        with self.subTest(safe_case="ordinary-token-secret-words-in-identifiers"):
            safe_identity_projection = self._project([
                self._event(
                    task_id="design-token-audit",
                    agent_id="secret-santa-task",
                ),
            ])
            self.assertEqual(len(safe_identity_projection["events"]), 1)
            safe_event = safe_identity_projection["events"][0]
            self.assertEqual(safe_event["task_id"], "design-token-audit")
            self.assertEqual(safe_event["agent_id"], "secret-santa-task")

    def test_ac_8_release_matrix_redacts_private_mounts_hosts_auth_and_email(self):
        sensitive_values = (
            ("/Volumes/Client/project/roadmap.md", "Volumes/Client"),
            ("/workspace/project/.env", "/workspace/project"),
            ("Visit 10.0.0.7:8080/dashboard", "10.0.0.7"),
            ("Visit internal-host.local/dashboard", "internal-host.local"),
            (
                "Use Bearer CAMPUS_GENERIC_BEARER_1234567890",
                "CAMPUS_GENERIC_BEARER",
            ),
            ("Email owner-private@example.com", "owner-private@example.com"),
        )
        neutral = "Недоступно в публичной сводке"

        for field in ("project", "next_step"):
            for value, marker in sensitive_values:
                with self.subTest(field=field, marker=marker):
                    projected = self._project([self._event(**{field: value})])
                    self.assertEqual(len(projected["events"]), 1)
                    self.assertEqual(projected["events"][0][field], neutral)
                    self.assertNotIn(value, repr(projected))
                    self.assertNotIn(marker, repr(projected))

    def test_ac_8_err_3_common_api_key_shapes_drop_public_identity_fields(self):
        credentials = (
            "sk" + "_live_CAMPUS012345678901234567890123",
            "sk-proj-CAMPUS012345678901234567890123",
            "ghp_CAMPUS012345678901234567890123456",
            "xoxb-CAMPUS012345678901234567890123456",
            "AIzaCAMPUS012345678901234567890123456",
            "AKIACAMPUSPROBE1234X",
        )
        for field in ("event_id", "task_id", "agent_id"):
            for credential in credentials:
                with self.subTest(field=field, credential=credential[:8]):
                    projected = self._project([
                        self._event(**{field: credential}),
                    ])
                    self.assertEqual(projected["events"], [])
                    self.assertNotIn("CAMPUS", repr(projected))

    def test_ac_8_ec_8_control_and_bidi_characters_are_neutralized(self):
        unsafe = "Safe text\x00\x1b[31m\u202eCAMPUS_BIDI\u2066"
        forbidden = ("\x00", "\x1b", "\u202e", "\u2066")
        for field in ("project", "next_step"):
            with self.subTest(field=field):
                projected = self._project([self._event(**{field: unsafe})])
                rendered = repr(projected)
                for character in forbidden:
                    self.assertNotIn(character, projected["events"][0][field])

    def test_ec_8_unicode_bound_does_not_end_inside_a_zwj_grapheme(self):
        long_unicode = "Проект-" + ("👩\u200d💻" * 1000)
        projected = self._project([self._event(project=long_unicode)])
        safe_project = projected["events"][0]["project"]

        self.assertLess(len(safe_project), len(long_unicode))
        safe_project.encode("utf-8")
        self.assertFalse(safe_project.endswith("\u200d"))
        self.assertFalse(unicodedata.combining(safe_project[-1]))
        self.assertTrue(safe_project.endswith("💻"))

    def test_ac_14_ec_10_generated_dashboard_integrates_one_responsive_campus(self):
        try:
            build_html = importlib.import_module("dashboard_builder.html_builder").build_html
        except Exception as exc:
            self.fail(f"RED: dashboard build integration unavailable ({type(exc).__name__}: {exc})")
        html = build_html([], "2026-08-08 12:00:00 UTC")
        script = self._script()
        css = self._css()
        self.assertEqual(html.count('id="department-campus"'), 1)
        self.assertIn("/api/manager/departments", script)
        self.assertIn("initDepartmentCampus", script)
        self.assertIn("renderDepartmentCampus", script)
        self.assertRegex(css, r"@media[^{}]*max-width")
        self.assertIn("minmax(0", css)
        self.assertRegex(css, r"(?:max-width:\s*100%|overflow-x:\s*(?:clip|hidden))")

    def test_ac_15_ec_11_ec_12_direction_b_shell_has_boulevard_lanes_and_two_waypoints(self):
        html = self.campus.build_department_campus_html()
        css = self._css()
        script = self._campus_script()

        self.assertEqual(html.count('class="campus-boulevard"'), 1)
        self.assertEqual(html.count("data-campus-task-lanes"), 1)
        self.assertEqual(html.count("data-campus-route-layer"), 1)
        self.assertEqual(html.count('data-campus-waypoint="test-lab"'), 1)
        self.assertEqual(html.count('data-campus-waypoint="github-station"'), 1)
        self.assertIn("Test Lab", html)
        self.assertIn("GitHub Station", html)
        self.assertEqual(len(re.findall(r'data-department-id="[^"]+"', html)), 7)
        self.assertNotRegex(
            html,
            r'data-campus-waypoint=[^>]+data-department-id|'
            r'data-department-id=[^>]+data-campus-waypoint',
        )

        for hook in (
            "campus-boulevard",
            "data-campus-task-lanes",
            "data-campus-route-layer",
            "data-campus-waypoint",
        ):
            self.assertIn(hook, html + css + script)
        self.assertIn("event.task_id", script)
        self.assertRegex(script, r"(?:slice\(\s*0\s*,\s*3\s*\)|length\s*<\s*3)")
        self.assertRegex(script, r"textContent\s*=\s*[^;]*task_id")

    def test_ac_15_status_only_routes_to_department_test_lab_or_github(self):
        script = self._campus_script()
        css = self._css()

        self.assertIn("data-campus-destination", script)
        self.assertIn("data-campus-moving", script)
        for token in (
            "active",
            "testing",
            "done",
            "queued",
            "waiting",
            "failed",
            "department",
            "test-lab",
            "github-station",
        ):
            self.assertIn(token, script)
        self.assertRegex(script, r"active[\s\S]{0,240}department")
        self.assertRegex(script, r"testing[\s\S]{0,240}test-lab")
        self.assertRegex(script, r"done[\s\S]{0,240}github-station")
        self.assertRegex(script, r"active[\s\S]{0,160}testing[\s\S]{0,240}moving")
        self.assertRegex(css, r"data-campus-moving[^{}]*true")

        self.assertIn("prefers-reduced-motion: reduce", css)
        self.assertIn("prefers-reduced-motion: reduce", script)
        self.assertIn("matchMedia", script)
        reduced = css[css.rfind("@media (prefers-reduced-motion: reduce)"):]
        self.assertIn("animation: none", reduced)
        self.assertIn("transition: none", reduced)

    def test_ac_15_journey_uses_hq_and_destination_geometry_with_web_animations(self):
        script = self._campus_script()

        self.assertIn("data-campus-static-manager", script)
        self.assertIn("campus-boulevard", script)
        self.assertIn("data-campus-destination", script)
        self.assertIn("getBoundingClientRect(", script)
        self.assertIn(".animate(", script)
        self.assertRegex(script, r"(?:transform|translate)[\s\S]{0,500}(?:duration|easing)")
        self.assertRegex(script, r"active[\s\S]{0,160}testing[\s\S]{0,240}moving")
        self.assertRegex(
            script,
            r"(?:reducedMotion\.matches|dataset\.reducedMotion)[\s\S]{0,300}"
            r"(?:return|\.animate\()",
        )

    def test_ac_5_ac_15_support_agents_share_one_route_per_task_lane(self):
        events = [
            self._event(
                event_id="evt-primary",
                task_id="task-shared",
                agent_id="agent-primary",
                status="active",
            ),
            self._event(
                department_id="design",
                event_id="evt-support",
                task_id="task-shared",
                agent_id="agent-support",
                status="active",
            ),
            self._event(
                event_id="evt-second",
                task_id="task-second",
                agent_id="agent-second",
                status="testing",
            ),
        ]
        projected = self._project(events)
        self.assertEqual(
            list(dict.fromkeys(event["task_id"] for event in projected["events"])),
            ["task-shared", "task-second"],
        )
        self.assertEqual(projected["visible_task_count"], 2)

        script = self._campus_script()
        self.assertIn("data-campus-route-task-id", script)
        self.assertRegex(script, r"(?:new\s+Map|new\s+Set)\(")
        self.assertRegex(
            script,
            r"(?:\.has|\.set|\.add)\(\s*event\.task_id",
        )
        self.assertRegex(script, r"(?:slice\(\s*0\s*,\s*3\s*\)|length\s*<\s*3)")

    def test_ac_15_mixed_status_task_route_uses_testing_precedence_and_one_lane(self):
        events = [
            self._event(
                event_id="evt-shared-done",
                task_id="task-shared",
                agent_id="agent-done",
                status="done",
            ),
            self._event(
                event_id="evt-shared-active",
                task_id="task-shared",
                agent_id="agent-active",
                status="active",
            ),
            self._event(
                department_id="design",
                event_id="evt-shared-testing",
                task_id="task-shared",
                agent_id="agent-testing",
                status="testing",
            ),
            self._event(
                event_id="evt-two", task_id="task-two", agent_id="agent-two",
            ),
            self._event(
                event_id="evt-three", task_id="task-three", agent_id="agent-three",
            ),
            self._event(
                event_id="evt-four", task_id="task-four", agent_id="agent-four",
            ),
        ]
        projected = self._project(events, max_tasks=99)
        self.assertEqual(projected["visible_task_count"], 3)
        self.assertEqual(projected["omitted_task_count"], 1)
        self.assertEqual(
            list(dict.fromkeys(event["task_id"] for event in projected["events"])),
            ["task-shared", "task-two", "task-three"],
        )

        script = self._campus_script()
        self.assertIn("data-campus-route-status", script)
        self.assertRegex(
            script,
            r"(?:priority|precedence)[\s\S]{0,400}(?:find|sort|reduce)",
        )
        self.assertRegex(script, r"testing[\s\S]{0,120}active")
        self.assertRegex(
            script,
            r"data-campus-route-status[\s\S]{0,240}(?:routeEvent|movingEvent)\.status",
        )

    def test_ac_15_waypoint_agent_containers_wrap_without_horizontal_escape(self):
        css = self._css()
        waypoint_rule = re.search(
            r"(?:\.campus-waypoint-agents|\[data-campus-waypoint-agents\])"
            r"[^\{]*\{([^}]+)\}",
            css,
        )
        self.assertIsNotNone(waypoint_rule)
        declarations = waypoint_rule.group(1)
        self.assertRegex(declarations, r"flex-wrap:\s*wrap")
        self.assertRegex(declarations, r"(?:max-width:\s*100%|min-width:\s*0)")
        self.assertRegex(declarations, r"overflow-x:\s*(?:auto|hidden|clip)")

    def test_ac_8_detail_drawer_has_exactly_nine_safe_status_derived_fields(self):
        html = self.campus.build_department_campus_html()
        script = self._campus_script()
        rows = re.findall(
            r"<dt>([^<]+)</dt><dd data-campus-detail-field=[\"']([^\"']+)",
            html,
        )
        self.assertEqual(
            rows,
            [
                ("Task", "task_id"),
                ("Department", "department"),
                ("Project", "project"),
                ("Role", "role"),
                ("Status", "status"),
                ("Updated", "updated_at"),
                ("Next safe step", "next_step"),
                ("Result", "result"),
                ("Evidence", "evidence_count"),
            ],
        )
        self.assertRegex(
            script,
            r"detailFields\.task_id\.textContent\s*=\s*event\.task_id",
        )
        result_assignment = re.search(
            r"detailFields\.result\.textContent\s*=\s*([^;]+);",
            script,
        )
        self.assertIsNotNone(result_assignment)
        self.assertIn("status", result_assignment.group(1))
        self.assertNotIn("event.result", script)
        self.assertNotIn("result", PUBLIC_EVENT_FIELDS)

    def test_ac_16_one_idempotent_visible_only_15_second_get_refresh(self):
        script = self._campus_script()

        self.assertEqual(script.count("setInterval("), 1)
        self.assertRegex(script, r"setInterval\([\s\S]{0,300}\b15000\b")
        self.assertIn("document.hidden", script)
        self.assertIn("visibilitychange", script)
        self.assertIn("/api/manager/departments", script)
        self.assertNotRegex(script, r"\bPOST\b|\bdispatch\w*\b|\bmodel\w*\b")
        self.assertIn("replaceChildren", script)
        self.assertIn("stale", script)
        self.assertIn("unavailable", script)
        idempotent_guard = re.search(
            r"(?:dataset\.[A-Za-z0-9_]*(?:initialized|Initialized|refreshBound|RefreshBound)|"
            r"if\s*\([^)]*(?:refreshTimer|intervalId)[^)]*\)\s*(?:return|\{?\s*clearInterval)|"
            r"clearInterval\s*\()",
            script,
        )
        self.assertIsNotNone(idempotent_guard)

    def test_ac_16_unchanged_refresh_does_not_replay_journey_and_error_clears_routes(self):
        script = self._campus_script()

        self.assertRegex(script, r"new\s+(?:Set|Map)\(")
        self.assertRegex(
            script,
            r"task_id[\s\S]{0,160}agent_id[\s\S]{0,160}status",
        )
        self.assertRegex(
            script,
            r"\.has\([^)]*\)[\s\S]{0,300}\.add\(",
        )
        self.assertRegex(
            script,
            r"(?:stale|unavailable)[\s\S]{0,500}(?:replaceChildren|clearCampus)",
        )
        self.assertIn("data-campus-route-layer", script)
        self.assertIn("data-campus-task-lanes", script)

    def test_ac_16_hidden_inflight_response_is_discarded_and_visibility_runs_fresh_get(self):
        script = self._campus_script()

        stale_response_guard = re.search(
            r"(?:AbortController|abort\(\)|[A-Za-z0-9_$]*(?:epoch|Epoch|generation|Generation))",
            script,
        )
        self.assertIsNotNone(stale_response_guard)
        self.assertRegex(
            script,
            r"visibilitychange[\s\S]{0,700}!\s*document\.hidden"
            r"[\s\S]{0,350}refreshDepartmentCampus\(",
        )
        self.assertRegex(
            script,
            r"document\.hidden[\s\S]{0,500}(?:return|abort\(\))",
        )
        self.assertEqual(script.count("setInterval("), 1)
        self.assertNotRegex(script, r"\bPOST\b|\bdispatch\w*\b|\bmodel\w*\b")

    def test_ac_16_journey_replay_memory_resets_only_after_honest_empty(self):
        script = self._campus_script()

        self.assertIn("journeySignatures", script)
        self.assertRegex(
            script,
            r"state\s*===\s*[\"']empty[\"'][\s\S]{0,300}"
            r"journeySignatures\.clear\(\)",
        )

    def test_ac_16_replay_signature_is_collision_free_for_colon_bearing_ids(self):
        script = self._campus_script()

        signature = re.search(
            r"JSON\.stringify\(\s*\[\s*event\.task_id\s*,\s*"
            r"event\.agent_id\s*,\s*event\.status\s*\]\s*\)",
            script,
        )
        self.assertIsNotNone(signature)

        first = ["a:b", "c", "active"]
        second = ["a", "b:c", "active"]
        self.assertNotEqual(first, second)
        self.assertEqual(":".join(first), ":".join(second))


if __name__ == "__main__":
    unittest.main()
