"""Техника → Mac mini shows «Здоровье каркаса» (Макс 2026-11-23)."""
import json
import shutil
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dashboard_builder.frame_health import frame_health_projection

ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "mac-mini-dashboard" / "index.html"
SERVER = ROOT / "dashboard-server-m4.py"
NOW = datetime(2026, 11, 23, 19, 0, tzinfo=timezone.utc)

SAMPLE = {
    "at": "2026-11-23T18:30:00+00:00", "ticks_max": 24, "ticks": 24,
    "beads": {"new": 5, "closed": 3, "open": 31, "closed_ids": ["hj-1", "hj-2", "hj-3"]},
    "plans": 4, "night_ok": True, "fix_closed": 2, "failed_services": ["com.pirajoke.x"],
    "review": {"green": 3, "yellow": 1, "red": 0}, "green_streak": 0, "warn": False,
    "autoloop": {"total": 2, "scheduled": 1},
}


class ProjectionTests(unittest.TestCase):
    def write(self, text):
        path = Path(tempfile.mkdtemp()) / "frame-health.json"
        path.write_text(text)
        return path

    def test_fresh_file_is_projected_without_bead_ids(self):
        out = frame_health_projection(self.write(json.dumps(SAMPLE)), owner=True, now=NOW)
        self.assertEqual(out["state"], "fresh")
        self.assertEqual(out["age_seconds"], 1800)
        self.assertEqual(out["beads"], {"new": 5, "closed": 3, "open": 31})
        self.assertEqual(out["autoloop"], {"total": 2, "scheduled": 1})
        self.assertEqual(out["failed_services"], ["com.pirajoke.x"])

    def test_public_viewer_gets_nothing(self):
        out = frame_health_projection(self.write(json.dumps(SAMPLE)), owner=False, now=NOW)
        self.assertEqual(out, {"ok": True, "state": "owner_only"})

    def test_two_missed_ticks_are_stale(self):
        out = frame_health_projection(self.write(json.dumps(SAMPLE)), owner=True, now=NOW + timedelta(hours=3))
        self.assertEqual(out["state"], "stale")

    def test_missing_broken_and_timeless_files(self):
        self.assertEqual(frame_health_projection(Path("/nonexistent/f.json"), owner=True)["state"], "not_installed")
        self.assertEqual(frame_health_projection(self.write("{oops"), owner=True)["state"], "unreadable")
        self.assertEqual(frame_health_projection(self.write("[]"), owner=True)["state"], "unreadable")
        self.assertEqual(frame_health_projection(self.write("{}"), owner=True, now=NOW)["state"], "stale")


class WiringTests(unittest.TestCase):
    def test_server_route_checks_owner(self):
        source = SERVER.read_text()
        start = source.index("if parsed.path == '/api/frame/health':")
        block = source[start:source.index("return", start)]
        self.assertIn("owner=self._dashboard_run_authorized()", block)
        self.assertIn("FRAME_HEALTH_FILE", block)

    def test_mini_refresh_loads_the_tile(self):
        source = HTML.read_text()
        start = source.index("async function refreshMini() {")
        self.assertIn("refreshFrameHealth();", source[start:start + 200])


RENDER_SCRIPT = r"""
const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch();
  const out = {};
  for (const [name, width] of [['desktop', 1200], ['phone', 390]]) {
    const page = await browser.newPage({ viewport: { width, height: 900 } });
    const errors = [];
    page.on('pageerror', e => errors.push(String(e)));
    await page.route('**/*', route => route.request().url().startsWith('file:') ? route.continue() : route.abort());
    await page.goto(process.argv[2], { waitUntil: 'domcontentloaded' });
    out[name] = await page.evaluate((sample) => {
      const el = document.getElementById('mini-frame');
      let n = el; while (n && n !== document.body) { n.hidden = false; n.style.display = 'block'; n = n.parentElement; }
      const read = () => ({
        hidden: el.hidden, note: document.getElementById('mini-frame-note').textContent,
        when: document.getElementById('mini-frame-when').textContent,
        rows: [...el.querySelectorAll('.machine-care-row')].map(r => [r.className, r.querySelector('.machine-care-label').textContent, r.querySelector('.machine-care-word').textContent]),
        sums: [...el.querySelectorAll('.machine-care-group-sum')].map(s => s.textContent),
        overflow: el.getBoundingClientRect().right > document.documentElement.clientWidth + 1,
      });
      const result = {};
      renderFrameHealth({ ...sample, state: 'fresh', generated_at: new Date(Date.now() - 60000).toISOString() });
      result.fresh = read();
      renderFrameHealth({ state: 'stale', generated_at: new Date(Date.now() - 4 * 3600000).toISOString() });
      result.stale = read();
      renderFrameHealth({ state: 'owner_only' });
      result.owner = read();
      renderFrameHealth(null);
      result.offline = read();
      return result;
    }, JSON.parse(process.argv[3]));
    out[name].errors = errors.filter(e => !/fetch|network|Failed to load/i.test(e));
    await page.close();
  }
  await browser.close();
  console.log(JSON.stringify(out));
})().catch(e => { console.error(e); process.exit(1); });
"""


def _has_playwright():
    if not shutil.which("node"):
        return False
    return subprocess.run(["node", "-e", "require('playwright')"], capture_output=True).returncode == 0


@unittest.skipUnless(_has_playwright(), "playwright + chromium are needed to render the page")
class RenderTests(unittest.TestCase):
    def test_tile_renders_every_state_on_desktop_and_phone(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "render.js"
            script.write_text(RENDER_SCRIPT)
            result = subprocess.run(["node", str(script), HTML.as_uri(), json.dumps(SAMPLE)],
                                    capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr)
        out = json.loads(result.stdout.strip().splitlines()[-1])
        for name in ("desktop", "phone"):
            view = out[name]
            self.assertEqual(view["errors"], [], name)
            fresh = view["fresh"]
            self.assertFalse(fresh["hidden"])
            self.assertIn("обновлено", fresh["when"])
            labels = {row[1]: row for row in fresh["rows"]}
            self.assertEqual(len(labels), 8)
            self.assertIn("is-ok", labels["Такт раз в час"][0])
            self.assertEqual(labels["agent-autoloop"][2], "по расписанию: 1")
            self.assertIn("is-warn", labels["Службы Mac mini"][0])
            self.assertEqual(fresh["sums"], ["всё в порядке", "всё в порядке", "требует внимания: 1"])
            self.assertFalse(fresh["overflow"], name)
            stale = view["stale"]
            self.assertIn("устарело", stale["when"])
            self.assertEqual(stale["sums"], ["нет данных: 3", "нет данных: 3", "нет данных: 2"])
            self.assertIn("только владельцу", view["owner"]["note"])
            self.assertEqual(view["owner"]["rows"], [])
            self.assertIn("Нет связи", view["offline"]["note"])


if __name__ == "__main__":
    unittest.main()
