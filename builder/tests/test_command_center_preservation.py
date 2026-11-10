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
        # 2026-10-28 on Mark's «унифицированный дизайн»: «Обновить» is the same outlined button as elsewhere.
        # 2026-11-02 on Mark's «визуализируй это в технике когда я нажимаю на мак про»: MacBook Pro gets
        # «Уход и защита» (watchdog, daily check, weekly restart, firewall, updates); «Обновить» reloads it too.
        # 2026-11-08 on Mark's «температуру компьютера в технике … чтобы мог трекать»: Mac mini and
        # MacBook Pro get «Температура» (now, 24 h chart, peak per day for the week).
        expected = {
            "section-mac-mini": "1010d6e1dd9fef0469cdb73472686a5f81b122dceb8312ae9800d1e8bb538c32",
            "section-air": "744a4d48469d44a53f2b354be488131d4298312b8ade8e681c9861e2cb8ecef3",
            "section-pro": "a2293f973f0d712f37d2866e0ecdf537b3440b11956d95b4a1dde7bf62d30220",
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
        # 2026-10-28 on Mark's «унифицированный дизайн»: every service described in Russian.
        # 2026-11-02 on Mark's «визуализируй это в технике когда я нажимаю на мак про»: MacBook Pro care block.
        # 2026-11-08 on Mark's «температуру компьютера в технике»: the temperature block for Mac mini and MacBook Pro.
        # 2026-11-10 on the Docker Guardian task: scheduled jobs between clean runs read «Ждёт запуска», not an error.
        source = HTML.read_text()
        start = source.index('// ─── Shared: render service table')
        end = source.index('// ─── AI Island')
        self.assertEqual(sha256(source[start:end].encode()).hexdigest(),
                         "972fe9bb4509f23996fd094f8ed0bbe620e554181bf017bc13d5197b2d0041d7")


if __name__ == "__main__":
    unittest.main()
