"""Contract tests for the read-only 3D mirror of the Department Campus."""
from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path
import re
import unittest


BUILDER_DIR = Path(__file__).resolve().parents[1]
ASSETS_DIR = BUILDER_DIR / "dashboard-assets"
SERVER_PATH = BUILDER_DIR / "dashboard-server-m4.py"
SCENE_START = "// ── Campus 3D Scene ──"
SCENE_END = "// ── End Campus 3D Scene ──"


def _block(source: str, start: str, end: str) -> str:
    begin = source.index(start)
    return source[begin:source.index(end, begin + len(start))]


class CampusThreeDimensionalSceneTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script = (ASSETS_DIR / "script.js").read_text(encoding="utf-8")
        cls.css = (ASSETS_DIR / "style.css").read_text(encoding="utf-8")
        cls.scene = _block(cls.script, SCENE_START, SCENE_END)
        cls.campus_script = _block(
            cls.script, "// ── Department Campus ──", "// ── End Department Campus ──"
        )
        cls.campus = importlib.import_module("dashboard_builder.department_campus")
        cls.html = cls.campus.build_department_campus_html()
        spec = importlib.util.spec_from_file_location("dashboard_server_campus_3d", SERVER_PATH)
        cls.server = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.server)

    def test_ac_1_stage_and_toggle_are_progressive_and_hidden_by_default(self):
        stage = re.search(r"<div class=\"campus-stage-3d\"[^>]*>", self.html).group(0)
        self.assertIn('aria-hidden="true"', stage)
        self.assertIn(" hidden", stage)
        toggle = re.search(r"<button\b[^>]*data-campus-view-toggle[^>]*>", self.html).group(0)
        self.assertIn('type="button"', toggle)
        self.assertIn('aria-pressed="false"', toggle)
        self.assertIn(" hidden", toggle)
        self.assertIn("webglSupported", self.scene)
        self.assertRegex(self.scene, r"\.catch\(\(\) => \{[\s\S]{0,300}toggle\.hidden = true")

    def test_ac_2_renderer_is_vendored_same_origin_and_allowlisted(self):
        vendored = ASSETS_DIR / "three.module.min.js"
        self.assertTrue(vendored.is_file())
        header = vendored.read_text(encoding="utf-8")[:200]
        self.assertIn("SPDX-License-Identifier: MIT", header)
        self.assertIn("'/dashboard-assets/three.module.min.js'", self.scene)
        self.assertNotRegex(self.scene, r"https?://")
        self.assertIn("/dashboard-assets/three.module.min.js", self.server.PUBLIC_FILE_PATHS)
        deploy = (BUILDER_DIR / "deploy_to_scripts.sh").read_text(encoding="utf-8")
        self.assertIn("three.module.min.js", deploy)
        rebuild = (BUILDER_DIR / "dashboard-rebuild.sh").read_text(encoding="utf-8")
        self.assertIn('"$PUBLISH_WT/dashboard-assets/three.module.min.js"', rebuild)

    def test_ac_3_scene_has_no_network_write_or_model_paths(self):
        for pattern in (
            r"\bfetch\s*\(",
            r"XMLHttpRequest",
            r"WebSocket",
            r"EventSource",
            r"sendBeacon",
            r"\bPOST\b",
            r"\bdispatch\w*\b",
            r"\bmodel\w*\b",
            r"innerHTML",
        ):
            with self.subTest(pattern=pattern):
                self.assertNotRegex(self.scene, pattern)
        self.assertIn("MutationObserver", self.scene)
        self.assertIn("[data-campus-live-agent]", self.scene)

    def test_ac_4_only_verified_new_journeys_walk(self):
        self.assertRegex(
            self.scene,
            r"campusMoving === 'true' && !reducedMotion\.matches",
        )
        self.assertRegex(self.scene, r"if \(changed && moving[^)]*\)\s*\{\s*startJourney")
        # The 2D campus only flags new active/testing journeys as moving.
        self.assertIn("const movingStatuses = ['active', 'testing'];", self.campus_script)

    def test_ac_5_handoff_visits_main_manager_and_done_is_placed(self):
        self.assertRegex(self.scene, r"roomPath\(actor\.room, 'hq'\)")
        self.assertIn("pause: MEETING_SECONDS, taskId", self.scene)
        self.assertIn("'github-station'", self.scene)

    def test_ac_6_routes_are_capped_at_three_tasks(self):
        self.assertIn("primaryByTask.size < 3", self.scene)
        # An existing task may still switch to a higher-precedence event.
        self.assertIn("current ? rank < current.rank : primaryByTask.size < 3", self.scene)

    def test_ac_7_idle_states_return_residents_home_without_routes(self):
        self.assertIn("placeActor(actor, actor.home, actor.homeFacing);", self.scene)
        self.assertIn("ожидает задач", self.scene)
        self.assertIn("if (state === 'loading') return;", self.scene)

    def test_ac_8_frames_render_on_demand_and_respect_reduced_motion(self):
        self.assertIn("matchMedia('(prefers-reduced-motion: reduce)')", self.scene)
        self.assertRegex(
            self.scene,
            r"if \(animating && active && !document\.hidden\) \{[\s\S]{0,120}requestAnimationFrame",
        )
        self.assertRegex(self.scene, r"if \(reducedMotion\.matches\) \{[\s\S]{0,200}placeActor")
        self.assertNotIn("setAnimationLoop", self.scene)
        self.assertNotIn("setInterval", self.scene)
        # The semantic 2D campus block keeps its zero-animation-frame contract.
        self.assertNotIn("requestAnimationFrame", self.campus_script)
        reduced = self.css[self.css.index(".campus-stage-3d,\n    .campus-stage-3d *"):]
        self.assertIn("animation: none", reduced[:200])
        self.assertIn("transition: none", reduced[:200])

    def test_ac_9_map_stays_focusable_and_focus_is_mirrored(self):
        rule = re.search(r"\.department-campus\.is-3d-view \.campus-map \{([^}]*)\}", self.css).group(1)
        self.assertIn("clip-path: inset(50%)", rule)
        self.assertNotIn("display: none", rule)
        self.assertNotIn("visibility: hidden", rule)
        self.assertIn("addEventListener('focusin'", self.scene)
        self.assertIn("data-campus-3d-focus", self.html)
        self.assertRegex(self.scene, r"target\.click\(\)")

    def test_ac_10_status_chips_pair_glyphs_with_canonical_text(self):
        for glyph in ("'▶'", "'◎'", "'✓'", "'✕'"):
            self.assertIn(glyph, self.scene)
        self.assertIn("describeStatus(status, statusText)", self.scene)

    def test_ac_11_view_preference_and_department_iframe(self):
        self.assertIn("command-center.campus.view", self.scene)
        self.assertRegex(self.scene, r"get\('view'\) === 'department'\) return;")

    def test_ac_12_live_agent_buttons_expose_only_public_fields(self):
        create = _block(
            self.campus_script, "function createCampusAgent", "function renderCampusTaskLanes"
        )
        fields = set(re.findall(r"button\.dataset\.(campus\w+) = ", create))
        self.assertEqual(
            fields,
            {
                "campusLiveAgent",
                "campusAgentTrigger",
                "campusAgentId",
                "campusDepartmentId",
                "campusTaskId",
                "campusStatus",
                "campusProject",
            },
        )
        self.assertNotRegex(create, r"dataset\.\w*(?:Summary|Issue|Evidence|Next)")

    def test_standalone_document_ships_both_blocks_once(self):
        document = self.server._department_campus_document()
        self.assertEqual(document.count(SCENE_START), 1)
        self.assertEqual(document.count("// ── Department Campus ──"), 1)
        self.assertEqual(document.count('id="department-campus"'), 1)
        self.assertLess(
            document.index("// ── Department Campus ──"), document.index(SCENE_START)
        )
        self.assertIn(".campus-stage-3d", document)


if __name__ == "__main__":
    unittest.main()
