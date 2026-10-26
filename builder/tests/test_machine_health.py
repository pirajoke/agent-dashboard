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
    if source[max(0, start - 6):start] == "async ":
        start -= 6
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

    def test_memory_is_judged_by_pressure_when_the_computer_reports_it(self):
        # The real MacBook Pro on 2026-10-26: 46 of 48 GB physically in use, but 71% pressure-free.
        base = {"cpu_percent": 28, "memory_used_gb": 13.9, "memory_total_gb": 48, "disk_used_gb": 495, "disk_total_gb": 1858}
        self.assertEqual(self.words({**base, "memory_pressure_free_percent": 71})[0], ["Память", "ок", "ok"])
        self.assertEqual(self.words({**base, "memory_pressure_free_percent": 8})[0], ["Память", "перегружена", "bad"])

    def test_missing_numbers_say_so(self):
        self.assertEqual([w[1] for w in self.words({})], ["нет данных"] * 3)


class MachineHealthPageTests(unittest.TestCase):
    def test_each_computer_has_a_health_row_that_opens_the_numbers(self):
        source = HTML.read_text()
        for key in ("mini", "air", "pro"):
            self.assertIn(f'<div class="machine-health" id="{key}-health"', source)
        self.assertIn("button.dataset.ccInfo = `machine-${key}`", source)

    def test_proxy_waits_long_enough_for_a_laptop(self):
        server = SERVER.read_text()
        timeout = int(re.search(r"REMOTE_HEALTH_TIMEOUT_SECONDS = (\d+)", server).group(1))
        self.assertGreaterEqual(timeout, 10)
        self.assertIn("urlopen(req, timeout=REMOTE_HEALTH_TIMEOUT_SECONDS)", server)


# A small fake DOM: enough for the MacBook Pro refresh and the health tiles.
FAKE_DOM = r"""
class El {
  constructor(tag) { this.tagName = tag; this.children = []; this.dataset = {}; this.style = {}; this.attrs = {}; this.className = ''; this._text = ''; }
  get textContent() { return this._text + this.children.map(c => c.textContent).join(''); }
  set textContent(v) { this._text = String(v); this.children = []; }
  setAttribute(k, v) { this.attrs[k] = v; }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = nodes; }
  all() { return this.children.flatMap(c => [c, ...c.all()]); }
  querySelector(sel) {
    let m = sel.match(/^\[data-health="(.+)"\]$/);
    if (m) return this.all().find(e => e.dataset.health === m[1]) || null;
    m = sel.match(/^\.([\w-]+)(?: > span)?$/);
    const found = this.all().find(e => e.className.split(' ').includes(m[1])) || null;
    return found && sel.includes('>') ? found.children[0] : found;
  }
}
const nodes = {};
const document = { getElementById: id => (nodes[id] ||= new El('div')), createElement: tag => new El(tag) };
let now = 1e12; Date.now = () => now;
let answers = []; let pending = null;
function fetchJSON() { const next = answers.shift(); return next === 'hang' ? new Promise(r => { pending = r; }) : Promise.resolve(next); }
const visibleRuntimeServices = s => s; const renderSvcTable = () => {}; const renderHeaderDate = () => {};
const PRO_API = '/api/pro'; const PRO_API_PATH_PREFIX = '';
const ccInfoSources = {};
"""


@unittest.skipUnless(shutil.which("node"), "node is needed to run the page code")
class MachineRefreshBehaviourTests(unittest.TestCase):
    def run_page(self, steps):
        source = HTML.read_text()
        consts = re.search(r"const MACHINE_GRACE_MS = .*?;\nconst machineLastSeen = \{\};\nconst machineInFlight = \{\};", source, re.S).group(0)
        script = "\n".join([
            FAKE_DOM, "const machineUptime = {}; const machineSystem = {}; const machineMemoryFree = {};", consts,
            *(js_function(source, name) for name in ("machineMemoryLow", "machineStatusText", "machinePercent", "machineHealthItems", "renderMachineHealth",
                                                      "machineRecentlySeen", "renderGauges", "refreshPro")),
            "const sys = {hostname: 'MBP', cpu_percent: 10, memory_used_gb: 15, memory_total_gb: 16, disk_used_gb: 50, disk_total_gb: 500};",
            "const words = () => document.getElementById('pro-health').children.map(b => b.querySelector('.machine-health-word').textContent);",
            "const log = []; const snap = () => log.push([document.getElementById('pro-status').textContent, words()]);",
            "(async () => {", steps, "console.log(JSON.stringify(log)); })();",
        ])
        out = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True).stdout
        return json.loads(out)

    def test_one_missed_answer_keeps_the_picture_until_the_grace_period_ends(self):
        log = self.run_page("""
          answers = [{system: sys, services: []}, null, null];
          await refreshPro(); snap();
          now += 60 * 1000; await refreshPro(); snap();
          now += 3 * 60 * 1000; await refreshPro(); snap();
        """)
        self.assertEqual(log[0], ["Работает · мало памяти", ["перегружена", "ок", "спокойно"]])
        self.assertEqual(log[1], log[0])
        self.assertEqual(log[2], ["Нет связи", []])

    def test_a_slow_answer_is_not_asked_for_twice(self):
        log = self.run_page("""
          answers = ['hang'];
          const first = refreshPro();
          answers = [null]; await refreshPro(); snap();
          pending({system: sys, services: []}); await first; snap();
        """)
        self.assertEqual(log[0][0], "")  # the second call waited instead of reporting «Нет связи»
        self.assertTrue(log[1][0].startswith("Работает"))

    def test_tiles_are_updated_in_place_so_focus_survives(self):
        log = self.run_page("""
          answers = [{system: sys, services: []}, {system: {...sys, memory_used_gb: 4}, services: []}];
          await refreshPro(); const before = nodes['pro-health'].children[0];
          await refreshPro(); log.push(before === nodes['pro-health'].children[0]); snap();
        """)
        self.assertTrue(log[0])
        self.assertEqual(log[1][1][0], "ок")

if __name__ == "__main__":
    unittest.main()
