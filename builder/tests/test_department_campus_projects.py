from __future__ import annotations

from datetime import datetime, timedelta, timezone
import importlib
from pathlib import Path
import re
import unittest


NOW = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)
ASSETS_DIR = Path(__file__).resolve().parents[1] / "dashboard-assets"
EXPECTED_PROJECTS = (
    {"project": "MAIN MANAGER", "department_id": "hq", "agent_id": "COORDINATOR"},
    {"project": "AI STUDIO", "department_id": "sales", "agent_id": "RESEARCHER"},
    {"project": "MY DICTIONARY", "department_id": "development", "agent_id": "BUILDER"},
    {"project": "ACCOUNTABLE OS", "department_id": "development", "agent_id": "BUILDER"},
    {"project": "HEALTH OS", "department_id": "development", "agent_id": "BUILDER"},
    {"project": "CONTEXT NEWS", "department_id": "development", "agent_id": "BUILDER"},
    {"project": "PIXELVERSE DASHBOARD", "department_id": "design", "agent_id": "DESIGNER"},
    {"project": "JARVIS", "department_id": "infrastructure", "agent_id": "INFRASTRUCTURE"},
    {"project": "GITHUB HYGIENE", "department_id": "infrastructure", "agent_id": "INFRASTRUCTURE"},
    {"project": "SKILLS LIBRARY", "department_id": "internal", "agent_id": "VAULT"},
    {"project": "UNFINISHED STUFF", "department_id": "internal", "agent_id": "VAULT"},
    {"project": "FINANCIAL OS", "department_id": "finance", "agent_id": "ANALYST"},
)


class DepartmentCampusProjectTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.campus = importlib.import_module("dashboard_builder.department_campus")
        cls.html = cls.campus.build_department_campus_html()
        cls.css = (ASSETS_DIR / "style.css").read_text(encoding="utf-8")
        cls.script = (ASSETS_DIR / "script.js").read_text(encoding="utf-8")

    def _registry(self):
        if not hasattr(self.campus, "CAMPUS_PROJECTS"):
            self.fail("RED: missing public CAMPUS_PROJECTS registry")
        return self.campus.CAMPUS_PROJECTS

    def _validator(self):
        if not hasattr(self.campus, "validate_campus_project_registry"):
            self.fail("RED: missing public validate_campus_project_registry(projects)")
        return self.campus.validate_campus_project_registry

    def _event_matcher(self):
        if not hasattr(self.campus, "campus_project_for_event"):
            self.fail("RED: missing public campus_project_for_event(event)")
        return self.campus.campus_project_for_event

    def _event(self, project="MY DICTIONARY", department_id="development", agent_id="BUILDER", **overrides):
        zone = self.campus.DEPARTMENT_ZONES[department_id]
        event = {
            "event_id": "evt-project-1", "task_id": "task-project-1",
            "department_id": department_id, "department_label": zone["label"],
            "project": project, "agent_id": agent_id, "role": zone["roles"][0],
            "status": "active", "updated_at": "2026-08-10T11:59:00Z",
            "next_step": "Review safe evidence", "evidence_count": 2,
            "ephemeral": True, "zone_id": zone["zone_id"],
        }
        event.update(overrides)
        return event

    def _projection(self, events, *, heartbeats=None):
        heartbeat_records = heartbeats
        if heartbeat_records is None:
            heartbeat_records = []
            seen = set()
            for event in events if isinstance(events, list) else []:
                if not isinstance(event, dict) or event.get("status") not in {"active", "testing"}:
                    continue
                identity = (event.get("project"), event.get("agent_id"), event.get("task_id"))
                if identity in seen:
                    continue
                seen.add(identity)
                heartbeat_records.append({
                    "project": event.get("project"),
                    "agent_id": event.get("agent_id"),
                    "run_id": event.get("task_id"),
                    "session_id": f"session-project-{len(heartbeat_records) + 1}",
                    "state": "working",
                    "heartbeat_at": "2026-08-10T11:59:45Z",
                })
        try:
            return self.campus.department_campus_projection(
                events,
                heartbeats=heartbeat_records,
                now=NOW,
            )
        except TypeError as exc:
            self.fail(
                "RED: project projection must accept explicit heartbeats "
                f"({exc})"
            )

    def test_ac_1_ec_4_registry_is_the_exact_canonical_public_project_set(self):
        registry = self._registry()
        self.assertIsInstance(registry, tuple)
        self.assertEqual(registry, EXPECTED_PROJECTS)
        self.assertEqual(len({record["project"] for record in registry}), 12)
        for record in registry:
            self.assertEqual(tuple(record), ("project", "department_id", "agent_id"))

        source = [dict(record) for record in registry]
        validated = self._validator()(source)
        source.append(dict(registry[0]))
        self.assertIsInstance(validated, tuple)
        self.assertEqual(validated, registry)

    def test_ec_3_registry_validation_rejects_invalid_identity_boundaries(self):
        validator = self._validator()
        cases = []
        duplicate = [dict(record) for record in EXPECTED_PROJECTS] + [dict(EXPECTED_PROJECTS[0])]
        cases.append(duplicate)
        for patch in (
            {"department_id": "legal"}, {"agent_id": "SCANNER"},
            {"agent_id": "DESIGNER"}, {"source_path": "/private/vault"},
        ):
            candidate = [dict(record) for record in EXPECTED_PROJECTS]
            candidate[2].update(patch)
            cases.append(candidate)
        missing = [dict(record) for record in EXPECTED_PROJECTS]
        missing[2].pop("agent_id")
        cases.append(missing)

        for candidate in cases:
            with self.subTest(candidate=candidate[2]):
                with self.assertRaises(ValueError):
                    validator(candidate)

    def test_ac_1_ac_2_ec_2_folders_and_idle_roster_survive_non_live_payloads(self):
        folders = re.findall(r"<button\b[^>]*data-campus-project-folder[^>]*>", self.html)
        self.assertEqual(len(folders), 12)
        for record in EXPECTED_PROJECTS:
            zone = re.search(
                rf'<section\b[^>]*data-department-id="{record["department_id"]}"[\s\S]*?</section>',
                self.html,
            )
            self.assertIsNotNone(zone)
            self.assertEqual(zone.group(0).count(f'data-campus-project="{record["project"]}"'), 1)
            self.assertIn(f'data-campus-project-agent="{record["agent_id"]}"', zone.group(0))

        stale = self._event(updated_at=(NOW - timedelta(minutes=31)).isoformat())
        for payload in ([], [stale], None, [{"project": "MY DICTIONARY"}]):
            with self.subTest(payload=payload):
                self.assertEqual(self._projection(payload)["events"], [])
                self.assertEqual(len(folders), 12)
        self.assertEqual(self.html.count("ожидает задач"), 7)
        self.assertNotIn("data-campus-live-agent", self.html)

    def test_ac_3_err_2_only_an_exact_verified_project_agent_pair_can_activate(self):
        matcher = self._event_matcher()
        matching = self._projection([self._event()])
        self.assertEqual(
            [(item["project"], item["department_id"], item["agent_id"]) for item in matching["events"]],
            [("MY DICTIONARY", "development", "BUILDER")],
        )
        self.assertEqual(matcher(matching["events"][0]), EXPECTED_PROJECTS[2])
        rejected = (
            self._event("UNVERIFIED"), self._event(agent_id="SCANNER"),
            self._event(agent_id="RESEARCHER"),
            self._event("MY DICTIONARY", department_id="design", agent_id="BUILDER"),
        )
        for event in rejected:
            with self.subTest(event=event):
                projected = self._projection([event])
                public_event = projected["events"][0] if projected["events"] else event
                self.assertIsNone(matcher(public_event))
        self.assertIn("function projectFolderForEvent(event)", self.script)
        self.assertRegex(
            self.script,
            r"folder\.dataset\.campusProject\s*===\s*String\(event\.project",
        )
        self.assertRegex(
            self.script,
            r"folder\.dataset\.campusProjectAgent\s*===\s*String\(event\.agent_id",
        )
        self.assertRegex(
            self.script,
            r"folder\.dataset\.campusProjectDepartment\s*===\s*String\(event\.department_id",
        )
        self.assertIn("if (!folder) return", self.script)

    def test_ac_4_folders_share_one_keyboard_operable_detail_surface(self):
        details = re.findall(
            r"<([a-z]+)\b[^>]*\sdata-campus-project-detail(?=[\s=>])[^>]*",
            self.html,
        )
        self.assertEqual(len(details), 1)
        detail_id = re.search(r'data-campus-project-detail[^>]*\bid="([^"]+)"', self.html)
        self.assertIsNotNone(detail_id)
        folders = re.findall(r"<button\b[^>]*data-campus-project-folder[^>]*>", self.html)
        for folder in folders:
            self.assertIn('type="button"', folder)
            self.assertIn(f'aria-controls="{detail_id.group(1)}"', folder)
            self.assertIn('aria-haspopup="dialog"', folder)
        self.assertRegex(self.html, r"<button\b[^>]*data-campus-project-detail-close")
        self.assertIn("[data-campus-project-folder]", self.script)
        self.assertRegex(
            self.script,
            r"(?s)data-campus-project-folder.{0,5000}Escape.{0,800}\.focus\(\)",
        )

    def test_ac_5_err_1_detail_and_projection_are_strict_safe_allowlists(self):
        fields = re.findall(r'data-campus-project-detail-field="([^"]+)"', self.html)
        self.assertEqual(
            fields,
            [
                "project",
                "department_id",
                "agent_id",
                "status",
                "work_summary",
                "issue_url",
                "next_step",
                "evidence_count",
            ],
        )
        for field in ("work_summary", "issue_url", "next_step", "evidence_count"):
            self.assertRegex(
                self.html,
                rf'data-campus-project-live-only[^>]*[\s\S]{{0,180}}data-campus-project-detail-field="{field}"',
            )

        private = ("<prompt>", "<body>", "<tool-output>", "secret-token", "/Users/private/vault", "<raw-metadata>")
        event = self._event(prompt=private[0], body=private[1], tool_output=private[2], credentials=private[3], local_path=private[4], raw_metadata=private[5])
        public = repr(self._projection([event]))
        for value in private:
            self.assertNotIn(value, public)
            self.assertNotIn(value, self.html)
        self.assertNotRegex(self.html, r"data-campus-project-detail-field=\"(?:prompt|body|tool_output|credentials|local_path|raw_metadata)\"")

    def test_ac_6_ec_1_projects_are_responsive_pixel_ui_with_reduced_motion(self):
        self.assertRegex(self.css, r"\.campus-project-folder[^\{]*\{[^}]+\}")
        self.assertRegex(self.css, r"\.campus-project-folder[^\{]*:focus-visible")
        self.assertRegex(
            self.css,
            r"\.campus-zone-agents\s*\{[^}]*pointer-events:\s*none",
        )
        self.assertRegex(
            self.css,
            r"\.campus-agent\s*\{[^}]*pointer-events:\s*auto",
        )
        self.assertRegex(self.css, r"@media\s*\(max-width:\s*\d+px\)[\s\S]*?\.campus-project")
        reduced = self.css[self.css.rfind("@media (prefers-reduced-motion: reduce)"):]
        self.assertIn(".campus-project-folder", reduced)
        self.assertIn(".campus-resident", reduced)
        self.assertRegex(reduced, r"animation:\s*none\s*!important")
        self.assertRegex(reduced, r"transition:\s*none\s*!important")

    def test_err_3_project_surface_and_transport_are_strictly_read_only(self):
        self.assertNotRegex(self.html, r"(?i)<(?:form|input|textarea|select)\b|contenteditable\s*=")
        self.assertNotRegex(self.html, r"data-campus-project-(?:create|edit|save|delete|archive|dispatch)")
        start = self.script.index("// ── Department Campus ──")
        end = self.script.index("// ── End Department Campus ──", start)
        campus_script = self.script[start:end]
        self.assertIn("/api/manager/departments", campus_script)
        self.assertNotRegex(campus_script, r"(?i)\bmethod\s*:\s*['\"](?:POST|PUT|PATCH|DELETE)['\"]")
        self.assertNotRegex(campus_script, r"(?i)(?:create|edit|save|delete|archive|dispatch)Project\s*\(")


if __name__ == "__main__":
    unittest.main()
