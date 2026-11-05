import json
import shutil
import subprocess
import unittest
from pathlib import Path

PAGE = (Path(__file__).resolve().parents[1] / "mac-mini-dashboard" / "index.html").read_text(encoding="utf-8")


class DocumentsRoute3DTest(unittest.TestCase):
    """Mark 2026-10-23: the document route as a 3D scene he can turn around."""

    def setUp(self):
        self.scene = PAGE[PAGE.index("(function ccDocxx3d() {"):PAGE.index("})();", PAGE.index("(function ccDocxx3d() {"))]

    def test_scene_uses_the_vendored_renderer_and_falls_back_to_the_flat_route(self):
        self.assertIn("new URL('/dashboard-assets/three.module.min.js', window.location.href)", self.scene)
        self.assertNotIn("fetch(", self.scene)
        self.assertIn('<div class="docxx-stage" id="docxx-stage" hidden>', PAGE)
        self.assertIn("stage.hidden = false;", self.scene)

    def run_scene(self, webgl):
        # Runs the real start-up code against a tiny page stand-in and reports what the visitor would see.
        node = shutil.which("node")
        if not node:
            self.skipTest("Node runtime is not installed")
        setup = '''
const nodes = {};
const el = id => (nodes[id] = { id, hidden: false, textContent: '', className: '', classes: new Set(), parent: null,
  classList: { add(c) { this.o.classes.add(c); }, remove(c) { this.o.classes.delete(c); }, contains(c) { return this.o.classes.has(c); } },
  after(other) { other.parent = 'after-stage'; if (other.id) nodes[other.id] = other; }, prepend() {} });
const stage = el('docxx-stage'); stage.hidden = true; stage.classList.o = stage;
const section = el('section-documents'); section.classList.o = section;
globalThis.window = { location: { protocol: 'https:', href: 'https://command.example/' }, WebGLRenderingContext: function () {},
  matchMedia: () => ({ matches: false }) };
globalThis.console.warn = () => {};
globalThis.document = {
  getElementById: id => nodes[id] || null,
  createElement: tag => tag === 'canvas' ? { getContext: () => (WEBGL ? {} : null) } : { id: '', textContent: '', className: '' },
};
'''
        script = f"const WEBGL = {json.dumps(webgl)};\n{setup}\n{self.scene}}})();\n" + '''
setTimeout(() => {
  const note = nodes['docxx-3d-note'];
  console.log(JSON.stringify({ note: note ? note.textContent : null, shown: note ? note.parent : null,
    stageHidden: stage.hidden, has3d: section.classList.contains('has-3d') }));
}, 200);
'''
        run = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=15)
        self.assertEqual(run.returncode, 0, run.stderr)
        return json.loads(run.stdout.strip().splitlines()[-1])

    def test_no_webgl_says_why_and_keeps_the_flat_route(self):
        seen = self.run_scene(webgl=False)
        self.assertEqual(seen["note"], "3D-вид не открылся (браузер не даёт WebGL). Показана простая схема.")
        self.assertEqual(seen["shown"], "after-stage")
        self.assertTrue(seen["stageHidden"])
        self.assertFalse(seen["has3d"])

    def test_library_that_does_not_load_says_why_and_keeps_the_flat_route(self):
        seen = self.run_scene(webgl=True)
        self.assertEqual(seen["note"], "3D-вид не открылся (не загрузилась библиотека 3D). Показана простая схема.")
        self.assertEqual(seen["shown"], "after-stage")
        self.assertTrue(seen["stageHidden"])
        self.assertFalse(seen["has3d"])

    def test_papers_move_only_during_a_busy_pass_and_respect_reduced_motion(self):
        self.assertIn("dataset.active === 'true'", self.scene)
        self.assertIn("const moving = busy && !reduced.matches;", self.scene)
        self.assertIn("item.paper.visible = busy;", self.scene)

    def test_rendering_pauses_while_the_tab_is_not_on_screen(self):
        self.assertIn("!document.hidden && section.classList.contains('active')", self.scene)

    def test_labels_are_buttons_that_open_the_same_explanation(self):
        self.assertIn("document.createElement('button')", self.scene)
        self.assertIn("ccDocxxExplain(step);", self.scene)
        # The flat buttons stay on the page as the list form of the scene.
        self.assertIn('data-docxx-step="icloud"', PAGE)


if __name__ == "__main__":
    unittest.main()
