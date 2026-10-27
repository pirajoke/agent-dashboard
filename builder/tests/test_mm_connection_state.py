"""MAIN MANAGER tells an expired sign-in, a lost connection and a server error apart (Mark 2026-10-27)."""
from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
import unittest

HTML = Path(__file__).resolve().parents[1] / "mac-mini-dashboard/index.html"


class MainManagerConnectionStateTest(unittest.TestCase):
    def test_fetch_classifies_each_failure(self):
        source = HTML.read_text()
        helper = re.search(r"class MmFetchError extends Error \{.*?\n\}\n\n// Cloudflare Access.*?\n\}\n", source, re.S)
        self.assertIsNotNone(helper)
        javascript = helper.group(0) + """
const mmHeaders = () => ({});
const json = (status, body, type = 'application/json') => ({
  type: 'basic', status, ok: status >= 200 && status < 300,
  headers: { get: () => type }, json: async () => body,
});
const cases = {
  redirect: async () => ({ type: 'opaqueredirect', status: 0, ok: false, headers: { get: () => '' }, json: async () => { throw new Error(); } }),
  access_page: async () => json(403, null, 'text/html'),
  network: async () => { throw new TypeError('Failed to fetch'); },
  server: async () => json(500, { ok: false }),
  not_ok: async () => json(200, { ok: false }),
  html_200: async () => ({ ...json(200, null, 'text/html'), json: async () => { throw new SyntaxError(); } }),
  fine: async () => json(200, { ok: true, value: 1 }),
};
(async () => {
  const result = {};
  for (const [name, impl] of Object.entries(cases)) {
    globalThis.fetch = impl;
    try { result[name] = (await mmFetchJSON('/api/work/daily')).value; }
    catch (error) { result[name] = error.kind; }
  }
  process.stdout.write(JSON.stringify(result));
})();
"""
        output = subprocess.run(["node", "-e", javascript], check=True, capture_output=True, text=True).stdout
        self.assertEqual(json.loads(output), {
            "redirect": "signin", "access_page": "signin", "network": "offline",
            "server": "server", "not_ok": "server", "html_200": "server", "fine": 1,
        })

    def test_redirects_are_not_followed_and_health_does_not_blame_the_mac_mini(self):
        source = HTML.read_text()
        self.assertIn("redirect: 'manual'", source)
        self.assertNotIn("Не удалось получить проекты с сервера Command Center", source)
        self.assertRegex(source, r"if \(!data && mmConn\) \{[^}]*line\.hidden = true;")


if __name__ == "__main__":
    unittest.main()
