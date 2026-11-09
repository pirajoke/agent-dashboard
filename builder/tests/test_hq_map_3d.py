import re
import unittest
from pathlib import Path

PAGE = (Path(__file__).resolve().parents[1] / "mac-mini-dashboard" / "index.html").read_text(encoding="utf-8")


class HqMap3dTest(unittest.TestCase):
    """Макс 2026-11-09: the personal corporation after both courses as one 3D map in «Архитектура»."""

    def setUp(self):
        start = PAGE.index("const HQ_GROUPS = [")
        self.code = PAGE[start:PAGE.index("})();", PAGE.index("(function hqScene3d() {"))]

    def test_map_is_the_first_mode_of_the_architecture_tab(self):
        self.assertIn('<button type="button" id="arch-mode-hq" aria-pressed="true">Штаб 3D</button>', PAGE)
        self.assertIn("section.classList.toggle('is-hq', mode === 'hq');", PAGE)
        self.assertIn("archSetMode('hq');", PAGE)

    def test_every_node_has_a_group_a_plain_explanation_and_a_source(self):
        groups = set(re.findall(r"\{ id: '([a-z]+)', title: '", self.code))
        nodes = re.findall(r"\{ id: '([a-z]+)', group: '([a-z]+)', name: '[^']+', (?:tag: '[^']+', )?short: '[^']+', tone: '#[0-9a-f]{6}', state: '(on|plan)',[^\n]* what: '[^']{40,}', from: '[^']+' \}", self.code)
        self.assertEqual(groups, {"core", "dept", "system", "beat"})
        self.assertEqual(len(nodes), 19)
        self.assertEqual(len({node[0] for node in nodes}), len(nodes))
        self.assertTrue(all(node[1] in groups for node in nodes))
        planned = {node[0] for node in nodes if node[2] == "plan"}
        self.assertEqual(planned, {"crm", "ai", "mon", "sun"})

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


if __name__ == "__main__":
    unittest.main()
