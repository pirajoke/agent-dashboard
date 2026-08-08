from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import unittest

from dashboard_builder.agent_theater import build_agent_theater_html
from dashboard_builder.html_builder import build_html
from dashboard_builder.manager_events import (
    MANAGER_STATES,
    NEUTRAL_NEXT_STEP,
    PROJECT_STATIONS,
    SAFE_NEXT_STEPS,
    project_manager_event,
)

BUILDER_DIR = Path(__file__).resolve().parents[1]
ASSETS_DIR = BUILDER_DIR / "dashboard-assets"
NOW = datetime(2026, 8, 8, 12, 0, tzinfo=timezone.utc)


def event(**overrides):
    payload = {
        "event_type": "status",
        "project": "jarvis",
        "status": "running",
        "updated_at": "2026-08-08T11:58:00Z",
        "metadata": {"next_safe_step": "verify_evidence"},
    }
    payload.update(overrides)
    return payload


class ManagerEventProjectionTests(unittest.TestCase):
    def test_ac_1_maps_exactly_five_user_facing_states(self):
        self.assertEqual(
            MANAGER_STATES,
            ("в очереди", "работает", "готово", "нужно решение Марка", "ошибка"),
        )
        expected = {
            "pending": "в очереди",
            "running": "работает",
            "done": "готово",
            "needs_input": "нужно решение Марка",
            "failed": "ошибка",
        }
        for raw, label in expected.items():
            with self.subTest(raw=raw):
                self.assertEqual(project_manager_event(event(status=raw), now=NOW)["state"], label)

    def test_ac_2_maps_all_nine_projects_and_safe_aliases_to_distinct_stations(self):
        canonical = (
            "JARVIS", "MyDictionary", "Context News", "Financial OS", "AI Studio",
            "Accountable OS", "GitHub Hygiene", "Skills Library", "Unfinished Stuff",
        )
        self.assertEqual(tuple(PROJECT_STATIONS), canonical)
        self.assertEqual(len({station["id"] for station in PROJECT_STATIONS.values()}), 9)
        aliases = {
            "jarvis": "JARVIS",
            "mydictionnary": "MyDictionary",
            "context_news": "Context News",
            "financial_os": "Financial OS",
            "grachev-ai-studio": "AI Studio",
            "accountable_os": "Accountable OS",
            "github_hygiene": "GitHub Hygiene",
            "skills_library": "Skills Library",
            "unfinished_stuff": "Unfinished Stuff",
        }
        for alias, project in aliases.items():
            with self.subTest(alias=alias):
                projected = project_manager_event(event(project=alias), now=NOW)
                self.assertTrue(projected["active"])
                self.assertEqual(projected["station"], PROJECT_STATIONS[project])
                self.assertEqual(projected["details"]["project"], project)

    def test_ac_3_detail_projection_has_exactly_four_safe_fields(self):
        projected = project_manager_event(event(), now=NOW)
        self.assertEqual(tuple(projected["details"]), ("project", "time", "status", "next_step"))
        self.assertEqual(projected["details"]["project"], "JARVIS")
        self.assertEqual(projected["details"]["time"], "2026-08-08T11:58:00Z")
        self.assertEqual(projected["details"]["status"], "работает")
        self.assertEqual(projected["details"]["next_step"], SAFE_NEXT_STEPS["verify_evidence"])

    def test_ac_3_uses_safe_status_default_when_metadata_has_no_next_step(self):
        expected = {
            "pending": "wait_for_start",
            "running": "wait_for_result",
            "done": "verify_evidence",
            "needs_input": "mark_decision",
            "failed": "inspect_failure",
        }
        for status, code in expected.items():
            with self.subTest(status=status):
                projected = project_manager_event(event(status=status, metadata={}), now=NOW)
                self.assertEqual(projected["details"]["next_step"], SAFE_NEXT_STEPS[code])

    def test_ac_4_accepts_only_existing_handoff_or_status_event_types(self):
        self.assertTrue(project_manager_event(event(event_type="handoff"), now=NOW)["active"])
        self.assertTrue(project_manager_event(event(event_type="status"), now=NOW)["active"])
        self.assertFalse(project_manager_event(event(event_type="simulation"), now=NOW)["active"])

    def test_ac_5_html_and_css_expose_state_motion_hooks(self):
        html = build_agent_theater_html()
        css = (ASSETS_DIR / "style.css").read_text(encoding="utf-8")
        self.assertIn('id="manager-sprite"', html)
        self.assertIn('data-manager-state="idle"', html)
        self.assertIn('id="manager-details"', html)
        for state_class in ("queued", "working", "done", "decision", "error"):
            self.assertIn(f".manager-sprite.is-{state_class}", css)
        self.assertIn("@keyframes managerWalk", css)

    def test_ec_1_missing_malformed_and_stale_events_are_honestly_idle(self):
        stale = event(updated_at=(NOW - timedelta(hours=7)).isoformat())
        idle = {"active": False, "state": "idle", "station": None, "details": None}
        for payload in (None, {}, event(updated_at="not-a-date"), stale):
            with self.subTest(payload=payload):
                self.assertEqual(project_manager_event(payload, now=NOW), idle)

    def test_ec_2_unknown_project_does_not_invent_a_station(self):
        projected = project_manager_event(event(project="secret-client-project"), now=NOW)
        self.assertFalse(projected["active"])
        self.assertIsNone(projected["station"])
        self.assertIsNone(projected["details"])

    def test_ec_3_reduced_motion_disables_manager_transition_and_animation(self):
        css = (ASSETS_DIR / "style.css").read_text(encoding="utf-8")
        reduced = css[css.rfind("@media (prefers-reduced-motion: reduce)"):]
        self.assertIn(".manager-sprite", reduced)
        self.assertIn("animation: none", reduced)
        self.assertIn("transition: none", reduced)

    def test_err_1_raw_private_fields_never_enter_projection(self):
        payload = event(
            prompt="<private-prompt>",
            description="<private-description>",
            result="<internal-tool-output>",
            error="<credential-placeholder>",
            messages=[{"body": "<vault-content>"}],
            metadata={
                "next_safe_step": "verify_evidence",
                "repo_path": "<client-vault-path>",
                "tool_output": "<tool-output>",
            },
        )
        projected = project_manager_event(payload, now=NOW)
        rendered = repr(projected)
        self.assertEqual(tuple(projected), ("active", "state", "station", "details"))
        for forbidden in (
            "<private-description>", "<internal-tool-output>", "<credential-placeholder>",
            "<client-vault-path>", "<tool-output>",
        ):
            self.assertNotIn(forbidden, rendered)

    def test_err_2_unallowlisted_next_step_fails_closed(self):
        projected = project_manager_event(
            event(metadata={"next_safe_step": "<unallowlisted-private-action>"}), now=NOW
        )
        self.assertEqual(projected["details"]["next_step"], NEUTRAL_NEXT_STEP)
        self.assertNotIn("<unallowlisted-private-action>", repr(projected))


class ManagerEventVisualSmokeTests(unittest.TestCase):
    def test_visual_smoke_build_contains_manager_inside_stage_and_safe_detail_fields(self):
        html = build_html([], "2026-08-08 12:00:00 CEST")
        stage_start = html.index('id="theater-stage"')
        stage_end = html.index('<aside class="theater-panel">', stage_start)
        manager_index = html.index('id="manager-sprite"')
        self.assertLess(stage_start, manager_index)
        self.assertLess(manager_index, stage_end)
        for field in ("project", "time", "status", "next_step"):
            self.assertEqual(html.count(f'data-manager-field="{field}"'), 1)
        self.assertIn("/api/manager/events", html)
        self.assertIn("renderManagerEvent", html)
        for forbidden in ("prompt", "result", "error"):
            self.assertNotIn(f'data-manager-field="{forbidden}"', html)


if __name__ == "__main__":
    unittest.main()
