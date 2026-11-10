import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

HTML = Path(__file__).resolve().parents[1] / "mac-mini-dashboard" / "index.html"
PAGE = HTML.read_text(encoding="utf-8")


class HqMap3dTest(unittest.TestCase):
    """Макс 2026-11-09: the personal corporation after both courses as one 3D map in «Архитектура».

    Second take the same evening («пока ничего не понятно»): one building of five floors read top to
    bottom, and the path of one task walked by a single light. Third take 2026-11-10: of three video
    variants he picked the flat diagram that grows floor by floor («2 супер»), so it is the first view."""

    def setUp(self):
        start = PAGE.index("const HQ_FLOORS = [")
        self.code = PAGE[start:PAGE.index("})();", PAGE.index("(function hqScene3d() {"))]

    def test_map_is_the_first_mode_of_the_architecture_tab(self):
        self.assertIn('<button type="button" id="arch-mode-hq" aria-pressed="true">Штаб</button>', PAGE)
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
        self.assertEqual(planned, {"crm", "mon", "sun"})

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
        self.assertIn("section.classList.contains('active') && section.classList.contains('is-hq') && hqView.isHouse()", self.code)
        self.assertIn("if (!reduced.matches)", self.code)
        self.assertIn("card.dataset.ccInfo = `hq-${node.id}`;", self.code)
        self.assertIn("button.dataset.ccInfo = `hq-${node.id}`;", self.code)

    def test_a_phone_gets_its_own_narrower_building_and_the_page_keeps_its_scroll(self):
        self.assertIn("const cell = narrow ? CELL_NARROW : CELL_WIDE;", self.code)
        self.assertIn("if (!event.ctrlKey && !event.metaKey) return;", self.code)

    def test_the_growing_diagram_is_the_first_view_and_the_house_is_offered_only_when_it_runs(self):
        self.assertIn('<div class="hq-map is-tree" id="hq-map">', PAGE)
        self.assertIn('id="hq-views" role="group" aria-label="Как показать штаб" hidden>', PAGE)
        self.assertIn('<button type="button" id="hq-view-tree" aria-pressed="true">Схема</button>', PAGE)
        self.assertIn("stage.hidden = false;\n    hqView.offerHouse();", self.code)
        self.assertIn(".hq-map.is-tree .hq-stage,", PAGE)

    def test_the_diagram_hangs_floors_from_real_nodes_and_draws_the_story_path(self):
        trunk = dict(re.findall(r"(\w+): '(\w+)'", self.code[self.code.index("const HQ_TRUNK = {"):self.code.index("};", self.code.index("const HQ_TRUNK = {"))]))
        floor_of = {node[0]: node[1] for node in self.nodes()}
        self.assertEqual(trunk, {"you": "me", "hq": "hq"})
        self.assertTrue(all(floor_of[node] == floor for floor, node in trunk.items()))
        self.assertIn("legs = HQ_STORY.slice(0, -1).map((from, index) => {", self.code)
        self.assertIn("button.dataset.ccInfo = `hq-${node.id}`;", self.code[self.code.index("(function hqTree() {"):])

    def test_the_diagram_waits_off_screen_respects_reduced_motion_and_stacks_on_a_phone(self):
        tree = self.code[self.code.index("(function hqTree() {"):self.code.index("// The scene: five glass floors")]
        self.assertIn("section.classList.contains('is-hq') && map.classList.contains('is-tree')", tree)
        self.assertIn("if (!visible()) { timer = setTimeout(tick, 800); return; }", tree)
        self.assertIn("if (reduced.matches) { showAll(); return; }", tree)
        self.assertIn("for (const squeeze of ['is-tight', 'is-tighter'])", tree)
        self.assertIn("tree.classList.toggle('is-stack', wrapped);", tree)
        self.assertIn("@media (prefers-reduced-motion: reduce) { .hq-tree-replay { display: none; } }", PAGE)


OPEN_SCRIPT = r"""
const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1400, height: 1000 } });
  const errors = []; page.on('pageerror', e => errors.push(e.message));
  await page.goto(process.argv[2] + '?tab=architecture');
  await page.evaluate(() => showSection('architecture'));
  const state = () => page.evaluate(() => ({
    floors: document.querySelectorAll('.hq-tree-floor').length,
    hidden: document.querySelectorAll('.hq-tree-floor.is-out').length,
    caption: document.getElementById('hq-tree-cap').textContent,
  }));
  await page.waitForTimeout(400);
  const open = await state();
  await page.click('#hq-tree-replay');
  await page.waitForTimeout(100);
  const replay = await state();
  await page.waitForTimeout(3200);
  const grown = await state();
  console.log(JSON.stringify({ open, replay, grown, errors }));
  await browser.close();
})().catch(e => { console.error(e); process.exit(1); });
"""


def _has_playwright():
    if not shutil.which("node"):
        return False
    return subprocess.run(["node", "-e", "require('playwright')"], capture_output=True).returncode == 0


@unittest.skipUnless(_has_playwright(), "playwright + chromium are needed to render the page")
class HqTreeOpenTest(unittest.TestCase):
    """Макс, 10.11: «сделай чтобы сразу появлялось». Waiting for five floors to grow was too slow."""

    def test_the_whole_diagram_is_there_on_open_and_grows_only_on_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "open.js"
            script.write_text(OPEN_SCRIPT)
            result = subprocess.run(["node", str(script), HTML.as_uri()], capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr)
        out = json.loads(result.stdout.strip().splitlines()[-1])
        self.assertEqual(out["errors"], [])
        self.assertEqual((out["open"]["floors"], out["open"]["hidden"]), (5, 0))
        self.assertTrue(out["open"]["caption"].startswith("1 из 7."), out["open"]["caption"])
        self.assertEqual(out["replay"]["hidden"], 5)
        self.assertLess(out["grown"]["hidden"], 5)


if __name__ == "__main__":
    unittest.main()
