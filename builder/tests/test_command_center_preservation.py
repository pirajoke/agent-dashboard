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
        # Baseline: the owner-approved repository revision 8530103; the Mac mini services card
        # changed 2026-10-20 on Mark's word (grouped list, archive), the gauges did not. Re-baselined
        # 2026-10-24 on Mark's «го» to the rebuild plan: no metadata, gauges moved behind «i», Russian labels.
        expected = {
            "section-mac-mini": "fe9d5a398418f80d1f70e662e889395eb69334c0d1c314d3709fcb733628e9b1",
            "section-air": "68a62bd0dc1b0b0d94bc397c863d3fe0db2104406b53e751cc5f1b56a7c19339",
            "section-pro": "4d92d8caa10af2596c25b2131d6ff4e7acc00218b3ff6cd6e74af7de20b3aeb7",
        }
        source = HTML.read_text()
        for identity, digest in expected.items():
            with self.subTest(machine=identity):
                self.assertEqual(sha256(machine_panel(source, identity).encode()).hexdigest(), digest)

    def test_existing_machine_renderers_refresh_and_service_controls_are_unchanged(self):
        # Re-baselined 2026-10-20 with Mark's word for the grouped service list, and 2026-10-24 on his
        # «го» to the rebuild plan (list only, no counters, Russian status words).
        source = HTML.read_text()
        start = source.index('// ─── Shared: render service table')
        end = source.index('// ─── AI Island')
        self.assertEqual(sha256(source[start:end].encode()).hexdigest(),
                         "50c6fc2f38fa62c276c9060a275aeb38741ea0ca11de5fccb40566710aa5b2b3")


if __name__ == "__main__":
    unittest.main()
