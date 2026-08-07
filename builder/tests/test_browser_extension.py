import json
import struct
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
EXTENSION = ROOT / "browser-extension"


class BrowserExtensionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manifest = json.loads((EXTENSION / "manifest.json").read_text())

    def test_manifest_is_permissionless_manifest_v3(self) -> None:
        self.assertEqual(self.manifest["manifest_version"], 3)
        self.assertNotIn("permissions", self.manifest)
        self.assertNotIn("host_permissions", self.manifest)
        self.assertNotIn("background", self.manifest)

    def test_csp_is_strict_and_allows_only_public_frames(self) -> None:
        csp = self.manifest["content_security_policy"]["extension_pages"]
        self.assertIn("script-src 'self'", csp)
        self.assertIn("object-src 'self'", csp)
        self.assertNotIn("unsafe-eval", csp)
        self.assertIn("https://command.meshly.fr", csp)
        self.assertIn("https://pixel-agents.meshly.fr", csp)

    def test_popup_is_read_only_and_contains_safe_fallback(self) -> None:
        html = (EXTENSION / "popup.html").read_text()
        script = (EXTENSION / "popup.js").read_text()
        combined = f"{html}\n{script}".lower()

        self.assertIn("https://pixel-agents.meshly.fr/", html)
        self.assertIn("https://command.meshly.fr/?tab=agents", html)
        self.assertIn("read-only-shield", html)
        self.assertIn("officefallback", script.lower())

        forbidden = ("/api/bridge", "x-dashboard-run-token", "bearer ", "websocket")
        for value in forbidden:
            self.assertNotIn(value, combined)

    def test_required_icons_have_exact_png_dimensions(self) -> None:
        for size in (16, 32, 48, 128):
            icon = EXTENSION / "icons" / f"icon-{size}.png"
            self.assertTrue(icon.is_file(), icon)
            with icon.open("rb") as stream:
                self.assertEqual(stream.read(8), b"\x89PNG\r\n\x1a\n")
                length = struct.unpack(">I", stream.read(4))[0]
                self.assertEqual(stream.read(4), b"IHDR")
                self.assertEqual(length, 13)
                width, height = struct.unpack(">II", stream.read(8))
            self.assertEqual((width, height), (size, size))

    def test_reduced_motion_fallback_exists(self) -> None:
        css = (EXTENSION / "popup.css").read_text()
        self.assertIn("prefers-reduced-motion: reduce", css)


if __name__ == "__main__":
    unittest.main()
