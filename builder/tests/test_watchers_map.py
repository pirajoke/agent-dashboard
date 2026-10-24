import re
import unittest
from pathlib import Path

PAGE = (Path(__file__).resolve().parents[1] / "mac-mini-dashboard" / "index.html").read_text(encoding="utf-8")


class WatchersMapTest(unittest.TestCase):
    """Mark 2026-10-24: one map of every helper that runs by itself and what it watches."""

    def setUp(self):
        start = PAGE.index("const WATCH_GROUPS = [")
        self.code = PAGE[start:PAGE.index("})();", PAGE.index("(function ccWatch3d() {"))]

    def test_view_sits_next_to_the_campus_and_opens_from_a_link(self):
        self.assertIn("onclick=\"showAgentsView('watchers')\">Кто за чем следит</button>", PAGE)
        self.assertIn("['decisions', 'campus', 'watchers'].includes(view)", PAGE)
        self.assertIn("get('view') === 'watchers'", PAGE)

    def test_every_helper_belongs_to_a_group_and_says_what_it_watches(self):
        groups = set(re.findall(r"\{ id: '([a-z]+)', title: '", self.code))
        helpers = re.findall(r"\{ id: '([a-z]+)', group: '([a-z]+)', name: '([^']+)', watches: '([^']+)', does: '[^']+', why: '[^']+', when: '[^']+'", self.code)
        self.assertEqual(len(groups), 6)
        self.assertGreater(len(helpers), 20)
        self.assertEqual(len({h[0] for h in helpers}), len(helpers))
        self.assertTrue(all(h[1] in groups for h in helpers))

    def test_no_paths_or_service_labels_reach_the_page(self):
        self.assertNotIn("com.pirajoke", self.code)
        self.assertNotIn("/Users/", self.code)
        self.assertNotIn("~/", self.code)

    def test_scene_falls_back_to_the_list_and_pauses_off_screen(self):
        self.assertIn("new URL('/dashboard-assets/three.module.min.js', window.location.href)", self.code)
        self.assertIn('<div class="watch-stage" id="watch-stage" hidden>', PAGE)
        self.assertIn("stage.hidden = false;", self.code)
        self.assertIn("section.classList.contains('active') && !view.hidden", self.code)
        self.assertIn("if (!reduced.matches)", self.code)


if __name__ == "__main__":
    unittest.main()
