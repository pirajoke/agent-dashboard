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
        # 2026-10-26 on Mark's «дочистить Технику»: «MacBook Pro» instead of the host name, Russian labels.
        expected = {
            "section-mac-mini": "e31627372ecea7f14d30eda0fe67f194a95cb2a0bb5e4a4b46824cea16ed9303",
            "section-air": "22061e3e7422088d1cd99449b610e31718c8a1d824ba2313adf886d1ee90eeb8",
            "section-pro": "789db4bfd092a4eb74263bcbbc3ea251b4c150b7fcc17b0a9e5508dd71be3897",
        }
        source = HTML.read_text()
        for identity, digest in expected.items():
            with self.subTest(machine=identity):
                self.assertEqual(sha256(machine_panel(source, identity).encode()).hexdigest(), digest)

    def test_existing_machine_renderers_refresh_and_service_controls_are_unchanged(self):
        # Re-baselined 2026-10-20 with Mark's word for the grouped service list, and 2026-10-24 on his
        # «го» to the rebuild plan (list only, no counters, Russian status words), and 2026-10-26 on his
        # ask to watch memory and disk (longer laptop timeout, «мало памяти» status, memory/disk/load words,
        # grace period so a slow laptop does not flash «Нет связи»), and the values on those tiles, and on
        # «дочистить Технику»: plain machine names, words instead of counters, services switched off on purpose.
        source = HTML.read_text()
        start = source.index('// ─── Shared: render service table')
        end = source.index('// ─── AI Island')
        self.assertEqual(sha256(source[start:end].encode()).hexdigest(),
                         "f264041c41a5cd81ceb4698c21486934e259147b1302d3c031fcb0750b4782eb")


if __name__ == "__main__":
    unittest.main()
