import re
import unittest
from pathlib import Path

PAGE = (Path(__file__).resolve().parents[1] / "mac-mini-dashboard" / "index.html").read_text(encoding="utf-8")


class HqMap3dTest(unittest.TestCase):
    """Макс 2026-11-09: the personal corporation after both courses as one 3D map in «Архитектура».

    Second take the same evening («пока ничего не понятно»): one building of five floors read top to
    bottom, and the path of one task walked by a single light."""

    def setUp(self):
        start = PAGE.index("const HQ_FLOORS = [")
        self.code = PAGE[start:PAGE.index("})();", PAGE.index("(function hqScene3d() {"))]

    def test_map_is_the_first_mode_of_the_architecture_tab(self):
        self.assertIn('<button type="button" id="arch-mode-hq" aria-pressed="true">Штаб 3D</button>', PAGE)
        self.assertIn("section.classList.toggle('is-hq', mode === 'hq');", PAGE)
        self.assertIn("archSetMode('hq');", PAGE)

    def nodes(self):
        return re.findall(r"\{ id: '([a-z]+)', floor: '([a-z]+)', icon: '[^']+', name: '[^']+', short: '[^']+', state: '(on|plan)', what: '[^']{40,}', from: '[^']+' \}", self.code)

    def test_five_floors_read_top_to_bottom(self):
        floors = re.findall(r"\{ id: '([a-z]+)', title: '[^']+', line: '[^']+', tone: '#[0-9a-f]{6}' \}", self.code)
        self.assertEqual(floors, ["you", "hq", "dept", "product", "base"])

    def test_every_node_has_a_floor_a_plain_explanation_and_a_source(self):
        nodes = self.nodes()
        self.assertEqual(len(nodes), 22)
        self.assertEqual(len({node[0] for node in nodes}), len(nodes))
        self.assertTrue(all(node[1] in {"you", "hq", "dept", "product", "base"} for node in nodes))
        planned = {node[0] for node in nodes if node[2] == "plan"}
        self.assertEqual(planned, {"crm", "ai", "mon", "sun"})

    def test_the_story_walks_real_nodes_from_max_down_and_back(self):
        steps = re.findall(r"\{ at: '([a-z]+)', text: '[^']{20,}' \}", self.code)
        floor_of = {node[0]: node[1] for node in self.nodes()}
        self.assertEqual(len(steps), 7)
        self.assertEqual(steps[0], "me")
        self.assertTrue(all(step in floor_of for step in steps))
        self.assertEqual([floor_of[step] for step in steps], ["you", "you", "hq", "dept", "product", "base", "you"])
        self.assertIn('<ol class="hq-story" id="hq-story"></ol>', PAGE)

    def test_no_paths_or_service_labels_reach_the_page(self):
        for needle in ("com.pirajoke", "/Users/", "~/", ".secrets", "pirajoke/"):
            self.assertNotIn(needle, self.code)

    def test_scene_falls_back_to_the_cards_and_pauses_off_screen(self):
        self.assertIn("new URL('/dashboard-assets/three.module.min.js', window.location.href)", self.code)
        self.assertIn('<div class="watch-stage hq-stage" id="hq-stage" hidden>', PAGE)
        self.assertIn("stage.hidden = false;", self.code)
        self.assertIn("section.classList.contains('active') && section.classList.contains('is-hq')", self.code)
        self.assertIn("if (!reduced.matches)", self.code)
        self.assertIn("card.dataset.ccInfo = `hq-${node.id}`;", self.code)
        self.assertIn("button.dataset.ccInfo = `hq-${node.id}`;", self.code)

    def test_a_phone_gets_its_own_narrower_building_and_the_page_keeps_its_scroll(self):
        self.assertIn("const cell = narrow ? CELL_NARROW : CELL_WIDE;", self.code)
        self.assertIn("if (!event.ctrlKey && !event.metaKey) return;", self.code)


if __name__ == "__main__":
    unittest.main()
