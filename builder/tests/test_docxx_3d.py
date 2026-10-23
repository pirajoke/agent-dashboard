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
        self.assertIn(".catch(() =>", self.scene)

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
