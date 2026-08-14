from __future__ import annotations

from datetime import datetime, timezone
import importlib
import importlib.util
from pathlib import Path
import re
import unittest
from unittest.mock import patch


BUILDER_DIR = Path(__file__).resolve().parents[1]
ASSETS_DIR = BUILDER_DIR / "dashboard-assets"
SERVER_PATH = BUILDER_DIR / "dashboard-server-m4.py"
PUBLIC_EVENT_FIELDS = {
    "event_id", "task_id", "department_id", "department_label", "project",
    "agent_id", "role", "status", "updated_at", "next_step",
    "evidence_count", "ephemeral", "zone_id",
}
OWNER_ONLY_EVENT_FIELDS = {"work_summary", "issue_number", "issue_url"}


class DepartmentCampusWorkSummaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        server_spec = importlib.util.spec_from_file_location(
            "dashboard_server_campus_work_summary", SERVER_PATH
        )
        if server_spec is None or server_spec.loader is None:
            raise AssertionError("RED: dashboard server module cannot be loaded")
        cls.server = importlib.util.module_from_spec(server_spec)
        server_spec.loader.exec_module(cls.server)
        cls.campus = importlib.import_module("dashboard_builder.department_campus")
        cls.html = cls.campus.build_department_campus_html()
        cls.script = (ASSETS_DIR / "script.js").read_text(encoding="utf-8")
        cls.css = (ASSETS_DIR / "style.css").read_text(encoding="utf-8")

    def _bridge_task(self, *, metadata: dict | None = None, **overrides) -> dict:
        now = datetime.now(timezone.utc).isoformat()
        task = {
            "id": "bridge-campus-34",
            "status": "running",
            "agent_role": "BUILDER",
            "project": "JARVIS",
            "created_at": now,
            "claimed_at": now,
            "completed_at": None,
            "description": "FORBIDDEN_DESCRIPTION_CAMPUS_34",
            "result": "FORBIDDEN_RESULT_CAMPUS_34",
            "error": "FORBIDDEN_LOG_CAMPUS_34",
            "messages": [{"body": "FORBIDDEN_MESSAGE_CAMPUS_34"}],
            "metadata": {
                "event": "dispatch",
                "objective": "  Добавить краткую   сводку\nи ссылку на Issue  ",
                "github_repo": "pirajoke/jarvis",
                "github_issue_number": 34,
                "github_issue_url": "https://github.com/pirajoke/jarvis/issues/34",
                "github_issue_body": "FORBIDDEN_ISSUE_BODY_CAMPUS_34",
                "prompt": "FORBIDDEN_PROMPT_CAMPUS_34",
                "body": "FORBIDDEN_BODY_CAMPUS_34",
                "logs": "FORBIDDEN_LOG_METADATA_CAMPUS_34",
                "local_path": "/Users/private/FORBIDDEN_PATH_CAMPUS_34",
                "token": "FORBIDDEN_TOKEN_CAMPUS_34",
            },
        }
        if metadata is not None:
            task["metadata"] = metadata
        task.update(overrides)
        return task

    def _pixel_event(self, **overrides) -> dict:
        zone = self.campus.DEPARTMENT_ZONES["infrastructure"]
        event = {
            "event_id": "evt-campus-summary-34",
            "task_id": "task-campus-summary-34",
            "department_id": "infrastructure",
            "department_label": zone["label"],
            "project": "JARVIS",
            "agent_id": "INFRASTRUCTURE",
            "role": zone["roles"][0],
            "status": "active",
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "next_step": "Review safe evidence",
            "evidence_count": 1,
            "ephemeral": True,
            "zone_id": zone["zone_id"],
            "work_summary": "Проверить owner-проекцию",
            "github_repo": "pirajoke/jarvis",
            "github_issue_number": 34,
            "github_issue_url": "https://github.com/pirajoke/jarvis/issues/34",
        }
        event.update(overrides)
        return event

    def _manager_snapshot(self, event: dict, **metadata_overrides) -> dict:
        metadata = {
            "event": "status",
            "source_agent": "MAIN MANAGER",
            "pixel_events": [event],
        }
        metadata.update(metadata_overrides)
        return {
            "id": "manager-snapshot-campus-34",
            "status": "running",
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "description": "FORBIDDEN_MANAGER_BODY_CAMPUS_34",
            "result": "FORBIDDEN_MANAGER_RESULT_CAMPUS_34",
            "messages": [{"body": "FORBIDDEN_MANAGER_MESSAGE_CAMPUS_34"}],
            "metadata": metadata,
        }

    def _endpoint_payload(self, tasks: list[dict], *, owner: bool) -> dict:
        response: dict = {}
        handler = self.server.Handler.__new__(self.server.Handler)
        handler.path = "/api/manager/departments"
        handler.headers = {"Host": "command.meshly.fr"}
        handler._dashboard_run_authorized = lambda: owner
        handler._json_response = lambda status, payload: response.update(
            status=status, payload=payload
        )
        with patch.object(
            self.server, "_bridge_request", return_value={"tasks": tasks}
        ):
            handler.do_GET()
        self.assertEqual(response.get("status"), 200)
        return response["payload"]

    def _owner_event(self, task: dict) -> dict:
        payload = self._endpoint_payload([task], owner=True)
        self.assertEqual(payload["state"], "active")
        self.assertEqual(len(payload["events"]), 1)
        return payload["events"][0]

    def _campus_script(self) -> str:
        start = self.script.index("// ── Department Campus ──")
        end = self.script.index("// ── End Department Campus ──", start)
        return self.script[start:end]

    def test_ac01_ac02_ec01_ec03_inspector_has_optional_summary_and_issue_link(self):
        self.assertEqual(self.html.count("Над чем работаем"), 1)
        self.assertRegex(
            self.html,
            r'data-campus-project-live-only[^>]*hidden[\s\S]{0,240}'
            r'data-campus-project-detail-field="work_summary"',
        )
        self.assertEqual(self.html.count("data-campus-project-issue-link"), 1)
        issue_link = re.search(
            r'<a\b(?=[^>]*data-campus-project-issue-link)([^>]*)>', self.html
        )
        self.assertIsNotNone(issue_link, "the inspector needs one semantic Issue link")
        attributes = issue_link.group(1)
        self.assertIn('data-campus-project-detail-field="issue_url"', attributes)
        self.assertIn('target="_blank"', attributes)
        rel = re.search(r'rel="([^"]+)"', attributes)
        self.assertIsNotNone(rel)
        self.assertIn("noreferrer", rel.group(1).split())
        self.assertNotRegex(attributes, r'\btabindex="-1"')
        self.assertRegex(
            self.html,
            r'data-campus-project-live-only[^>]*hidden[\s\S]{0,300}'
            r'data-campus-project-issue-link',
        )
        campus_script = self._campus_script()
        for field in ("work_summary", "issue_number", "issue_url"):
            self.assertIn(field, campus_script)
        self.assertIn("command-center.jarvis-run-token", campus_script)
        self.assertIn("X-Dashboard-Run-Token", campus_script)
        self.assertRegex(campus_script, r"fetch\([\s\S]{0,500}\bheaders\s*:")
        self.assertIn("Issue #", campus_script)
        self.assertRegex(campus_script, r"removeAttribute\(\s*['\"]href['\"]\s*\)")
        self.assertRegex(campus_script, r"\.hidden\s*=")
        self.assertIn("textContent", campus_script)
        self.assertNotRegex(campus_script, r"\.innerHTML\s*=")

    def test_ac03_err02_owner_bridge_uses_only_typed_objective_and_exact_allowlist(self):
        event = self._owner_event(self._bridge_task())
        self.assertEqual(event["work_summary"], "Добавить краткую сводку и ссылку на Issue")
        self.assertEqual(event["issue_number"], 34)
        self.assertEqual(
            event["issue_url"], "https://github.com/pirajoke/jarvis/issues/34"
        )
        self.assertEqual(set(event), PUBLIC_EVENT_FIELDS | OWNER_ONLY_EVENT_FIELDS)
        rendered = repr(event)
        for forbidden in (
            "FORBIDDEN_DESCRIPTION_CAMPUS_34", "FORBIDDEN_RESULT_CAMPUS_34",
            "FORBIDDEN_LOG_CAMPUS_34", "FORBIDDEN_MESSAGE_CAMPUS_34",
        ):
            self.assertNotIn(forbidden, rendered)

        metadata_without_objective = dict(self._bridge_task()["metadata"])
        metadata_without_objective.pop("objective")
        fallback = self._owner_event(self._bridge_task(
            metadata=metadata_without_objective,
            description="SAFE LOOKING DESCRIPTION MUST NOT BECOME SUMMARY",
            result="SAFE LOOKING RESULT MUST NOT BECOME SUMMARY",
        ))
        self.assertNotIn("work_summary", fallback)
        self.assertNotIn("SAFE LOOKING", repr(fallback))

    def test_ac04_err01_issue_metadata_must_be_exact_and_fails_closed_independently(self):
        base = dict(self._bridge_task()["metadata"])
        invalid_cases = (
            {"github_issue_number": True},
            {"github_issue_number": "34"},
            {"github_issue_number": 0},
            {"github_issue_number": 35},
            {"github_repo": "pirajoke/agent-dashboard"},
            {"github_repo": "PIRAJOKE/jarvis"},
            {"github_repo": ["pirajoke", "jarvis"]},
            {"github_issue_url": "http://github.com/pirajoke/jarvis/issues/34"},
            {"github_issue_url": "https://evil.example/pirajoke/jarvis/issues/34"},
            {"github_issue_url": "https://user@github.com/pirajoke/jarvis/issues/34"},
            {"github_issue_url": "https://github.com:443/pirajoke/jarvis/issues/34"},
            {"github_issue_url": "https://github.com/pirajoke/jarvis/issues/34?tab=1"},
            {"github_issue_url": "https://github.com/pirajoke/jarvis/issues/34#issuecomment-1"},
            {"github_issue_url": "https://github.com/pirajoke/jarvis/issues/35"},
            {"github_issue_url": "https://github.com/PIRAJOKE/jarvis/issues/34"},
            {"github_issue_url": "https://github.com/pirajoke/jarvis/pull/34"},
            {"github_issue_url": 34},
        )
        for invalid in invalid_cases:
            with self.subTest(invalid=invalid):
                event = self._owner_event(
                    self._bridge_task(metadata={**base, **invalid})
                )
                self.assertEqual(
                    event.get("work_summary"),
                    "Добавить краткую сводку и ссылку на Issue",
                    "invalid issue data must hide only the Issue row",
                )
                self.assertNotIn("issue_number", event)
                self.assertNotIn("issue_url", event)

        for missing in ("github_repo", "github_issue_number", "github_issue_url"):
            with self.subTest(missing=missing):
                metadata = dict(base)
                metadata.pop(missing)
                event = self._owner_event(self._bridge_task(metadata=metadata))
                self.assertNotIn("issue_number", event)
                self.assertNotIn("issue_url", event)

    def test_ac05_verified_manager_pixel_event_uses_identical_owner_field_validation(self):
        valid = self._owner_event(self._manager_snapshot(self._pixel_event()))
        self.assertEqual(valid["work_summary"], "Проверить owner-проекцию")
        self.assertEqual(valid["issue_number"], 34)
        self.assertEqual(
            valid["issue_url"], "https://github.com/pirajoke/jarvis/issues/34"
        )

        mismatched = self._pixel_event(
            github_issue_url="https://github.com/pirajoke/jarvis/issues/35"
        )
        rejected_issue = self._owner_event(self._manager_snapshot(mismatched))
        self.assertEqual(rejected_issue["work_summary"], "Проверить owner-проекцию")
        self.assertNotIn("issue_number", rejected_issue)
        self.assertNotIn("issue_url", rejected_issue)

        unverified = self._endpoint_payload(
            [self._manager_snapshot(self._pixel_event(), source_agent="OTHER AGENT")],
            owner=True,
        )
        self.assertEqual(unverified["events"], [])
        self.assertNotIn("Проверить owner-проекцию", repr(unverified))

    def test_ac06_err02_public_endpoint_strips_owner_fields_and_all_raw_content(self):
        public = self._endpoint_payload([self._bridge_task()], owner=False)
        self.assertEqual(public["state"], "active")
        self.assertEqual(len(public["events"]), 1)
        self.assertEqual(set(public["events"][0]), PUBLIC_EVENT_FIELDS)
        rendered = repr(public)
        for forbidden in (
            "work_summary", "issue_number", "issue_url", "github_repo",
            "github_issue_number", "github_issue_url", "Добавить краткую",
            "FORBIDDEN_",
        ):
            self.assertNotIn(forbidden, rendered)

    def test_ec01_err01_missing_malformed_or_unsafe_summary_hides_only_summary(self):
        base = dict(self._bridge_task()["metadata"])
        unsafe_objectives = (
            None,
            True,
            34,
            ["private"],
            {"body": "private"},
            "   \n\t ",
            "Open /Users/mark/.ssh/id_rsa",
            "token=CAMPUS_GENERIC_TOKEN_1234567890",
            "Authorization: Bearer CAMPUS_BEARER_1234567890",
            "ghp_CAMPUS012345678901234567890123456",
            "Safe\x00\x1b[31mCAMPUS_CONTROL",
        )
        for objective in unsafe_objectives:
            with self.subTest(objective=repr(objective)[:40]):
                event = self._owner_event(
                    self._bridge_task(metadata={**base, "objective": objective})
                )
                self.assertNotIn("work_summary", event)
                self.assertEqual(event["issue_number"], 34)
                self.assertEqual(
                    event["issue_url"],
                    "https://github.com/pirajoke/jarvis/issues/34",
                    "unsafe summary must hide only the summary row",
                )
                self.assertNotIn("CAMPUS_", repr(event))
                self.assertNotIn("/Users/", repr(event))

    def test_ec02_summary_is_whitespace_normalized_unicode_safe_and_bounded(self):
        objective = "  Улучшить\n\tсводку  " + ("👩\u200d💻" * 1000)
        metadata = {**self._bridge_task()["metadata"], "objective": objective}
        summary = self._owner_event(self._bridge_task(metadata=metadata))["work_summary"]
        self.assertTrue(summary.startswith("Улучшить сводку "))
        self.assertNotRegex(summary, r"\s{2,}|[\r\n\t]")
        self.assertLess(len(summary), len(" ".join(objective.split())))
        self.assertFalse(summary.endswith("\u200d"))
        summary.encode("utf-8")
        self.assertRegex(
            self.css,
            r"\.campus-details\s+dd\s*\{[^}]*overflow-wrap:\s*anywhere",
        )
        self.assertRegex(
            self.css,
            r"@media\s*\(max-width:\s*560px\)[\s\S]*?\.campus-project-detail",
        )

    def test_err03_existing_empty_cap_focus_escape_and_read_only_contracts_remain(self):
        now = datetime(2026, 8, 14, 12, 0, tzinfo=timezone.utc)
        zone = self.campus.DEPARTMENT_ZONES["development"]
        events = []
        for index in range(4):
            events.append({
                "event_id": f"evt-regression-{index}",
                "task_id": f"task-regression-{index}",
                "department_id": "development",
                "department_label": zone["label"],
                "project": "MY DICTIONARY",
                "agent_id": f"agent-regression-{index}",
                "role": zone["roles"][0],
                "status": "active",
                "updated_at": "2026-08-14T11:59:00Z",
                "next_step": "Review safe evidence",
                "evidence_count": 1,
                "ephemeral": True,
                "zone_id": zone["zone_id"],
            })
        capped = self.campus.department_campus_projection(events, now=now)
        empty = self.campus.department_campus_projection([], now=now)
        self.assertEqual(capped["visible_task_count"], 3)
        self.assertEqual(capped["omitted_task_count"], 1)
        self.assertEqual(empty["state"], "empty")
        self.assertEqual(empty["events"], [])

        campus_script = self._campus_script()
        self.assertIn("Escape", campus_script)
        self.assertRegex(
            campus_script,
            r"data-campus-project-folder[\s\S]{0,5000}Escape[\s\S]{0,800}\.focus\(\)",
        )
        self.assertNotRegex(
            self.html,
            r"(?i)<(?:form|input|textarea|select)\b|contenteditable\s*=",
        )
        self.assertNotRegex(
            campus_script,
            r"(?i)\bmethod\s*:\s*['\"](?:POST|PUT|PATCH|DELETE)['\"]",
        )


if __name__ == "__main__":
    unittest.main()
