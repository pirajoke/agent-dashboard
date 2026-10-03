"""Frozen guards for the approved existing computer panels and telemetry."""
from hashlib import sha256
from pathlib import Path
import re
import unittest

HTML = Path(__file__).resolve().parents[1] / "mac-mini-dashboard" / "index.html"


def machine_panel(source, identity):
    start = source.index(f'<div id="{identity}"')
    depth = 0
    for token in re.finditer(r'<div\b[^>]*>|</div\s*>', source[start:]):
        depth += -1 if token.group().startswith('</') else 1
        if depth == 0:
            return source[start:start + token.end()]
    raise AssertionError("unclosed computer panel")


class ExistingMachinePreservationTests(unittest.TestCase):
    def test_original_machine_panels_are_preserved_verbatim(self):
        # Baseline: the owner-approved repository revision 8530103.
        expected = {
            "section-mac-mini": "c95dbb6725726ece419053c1e1ab0b8f0237491be2866ce8dd70dcd3ab77335d",
            "section-air": "8d48176f86489953a4c7411a40e9ec889406893dbadcb98a331ad794c1c06fb9",
            "section-pro": "590f947793e1082a23e3ba4d71f135e7639ab8d514a6ba3c895ab31b1b55a717",
        }
        source = HTML.read_text()
        for identity, digest in expected.items():
            with self.subTest(machine=identity):
                self.assertEqual(sha256(machine_panel(source, identity).encode()).hexdigest(), digest)

    def test_existing_machine_renderers_refresh_and_service_controls_are_unchanged(self):
        source = HTML.read_text()
        start = source.index('// ─── Shared: render service table')
        end = source.index('// ─── AI Island')
        self.assertEqual(sha256(source[start:end].encode()).hexdigest(),
                         "d2fab6ddbb538e2f0397ad666a91b48334ac67915a2c0772e634fd2545251dd3")


if __name__ == "__main__":
    unittest.main()
