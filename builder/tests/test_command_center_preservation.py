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
        # 2026-10-26 on Mark's ask to watch memory and disk: a plain «ок / перегружена» row under each header.
        expected = {
            "section-mac-mini": "b15950fae61ce6d7916440de2efb111c1cac074f0fc8ec24421b63eb0f910d0a",
            "section-air": "5a559c820d6144f67008ba67874358f3b4a8ec27379f373cf549084580b6d274",
            "section-pro": "3b110d68de46f65d40beec30267351c1b86faa6877ecf693850d1be78ada6450",
        }
        source = HTML.read_text()
        for identity, digest in expected.items():
            with self.subTest(machine=identity):
                self.assertEqual(sha256(machine_panel(source, identity).encode()).hexdigest(), digest)

    def test_existing_machine_renderers_refresh_and_service_controls_are_unchanged(self):
        # Re-baselined 2026-10-20 with Mark's word for the grouped service list, and 2026-10-24 on his
        # «го» to the rebuild plan (list only, no counters, Russian status words), and 2026-10-26 for the
        # memory/disk/load words and the grace period that stops a slow laptop from flashing «Нет связи».
        source = HTML.read_text()
        start = source.index('// ─── Shared: render service table')
        end = source.index('// ─── AI Island')
        self.assertEqual(sha256(source[start:end].encode()).hexdigest(),
                         "7a509800672441a4ef9b2dcb5ed6e29be8adb4d4447c1aa15a5502ff9739771e")


if __name__ == "__main__":
    unittest.main()
