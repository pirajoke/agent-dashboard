"""Техника shows memory, disk and load as plain words, with the numbers behind «i» (Mark 2026-10-26)."""
import json
from pathlib import Path
import re
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "mac-mini-dashboard" / "index.html"
SERVER = ROOT / "dashboard-server-m4.py"


def js_function(source, name):
    start = source.index(f"function {name}(")
    depth = 0
    for index in range(source.index("{", start), len(source)):
        depth += {"{": 1, "}": -1}.get(source[index], 0)
        if depth == 0:
            return source[start:index + 1]
    raise AssertionError(f"unclosed {name}")


@unittest.skipUnless(shutil.which("node"), "node is needed to run the page code")
class MachineHealthWordsTests(unittest.TestCase):
    def words(self, system):
        source = HTML.read_text()
        script = "\n".join([
            js_function(source, "machinePercent"),
            js_function(source, "machineHealthItems"),
            f"console.log(JSON.stringify(machineHealthItems({json.dumps(system)}).map(i => [i.label, i.word, i.level])));",
        ])
        out = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True).stdout
        return json.loads(out)

    def test_calm_computer_reads_ok(self):
        self.assertEqual(self.words({"cpu_percent": 12, "memory_used_gb": 7, "memory_total_gb": 16,
                                     "disk_used_gb": 80, "disk_total_gb": 256}),
                         [["Память", "ок", "ok"], ["Диск", "ок", "ok"], ["Процессор", "спокойно", "ok"]])

    def test_full_memory_and_disk_are_called_out(self):
        self.assertEqual(self.words({"cpu_percent": 91, "memory_used_gb": 15, "memory_total_gb": 16,
                                     "disk_used_gb": 210, "disk_total_gb": 256}),
                         [["Память", "перегружена", "bad"], ["Диск", "заполняется", "warn"],
                          ["Процессор", "перегружен", "bad"]])

    def test_missing_numbers_say_so(self):
        self.assertEqual([w[1] for w in self.words({})], ["нет данных"] * 3)


class MachineHealthPageTests(unittest.TestCase):
    def test_each_computer_has_a_health_row_that_opens_the_numbers(self):
        source = HTML.read_text()
        for key in ("mini", "air", "pro"):
            self.assertIn(f'<div class="machine-health" id="{key}-health"', source)
        self.assertIn("button.dataset.ccInfo = `machine-${key}`", source)

    def test_slow_laptop_does_not_flash_no_connection(self):
        source = HTML.read_text()
        self.assertIn("(base === AIR_API || base === PRO_API) && path.endsWith('/all')", source)
        for key in ("air", "pro"):
            self.assertIn(f"if (machineRecentlySeen('{key}')) return;", source)
            self.assertIn(f"if (machineInFlight.{key}) return;", source)
        server = SERVER.read_text()
        timeout = int(re.search(r"REMOTE_HEALTH_TIMEOUT_SECONDS = (\d+)", server).group(1))
        self.assertGreaterEqual(timeout, 10)
        self.assertIn("urlopen(req, timeout=REMOTE_HEALTH_TIMEOUT_SECONDS)", server)


if __name__ == "__main__":
    unittest.main()
