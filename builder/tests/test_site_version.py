"""«Сайт обновлён …» and the refresh prompt (Mark 2026-10-22): /api/site-version."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

BUILDER = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("dashboard_site_version_test", BUILDER / "dashboard-server-m4.py")
SERVER = importlib.util.module_from_spec(spec)
spec.loader.exec_module(SERVER)
PAGE = (BUILDER / "mac-mini-dashboard" / "index.html").read_text()


class SiteVersionTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "state.json"

    def get(self, host="command.meshly.fr"):
        handler = SERVER.Handler.__new__(SERVER.Handler)
        handler.path, handler.command = "/api/site-version", "GET"
        handler.headers = {"Host": host}
        output = {}
        handler._json_response = lambda status, payload: output.update(status=status, payload=payload)
        with patch.object(SERVER, "AUTO_DEPLOY_STATE_FILE", self.path):
            handler.do_GET()
        return output

    def test_version_is_the_last_real_deploy_time(self):
        self.path.write_text(json.dumps({"deployed_sha": "abc1234def", "deployed_at": "2026-10-22T21:29:00Z",
                                         "failed_sha": "0" * 40, "waiting_reason": "ci_pending"}))
        result = self.get()
        self.assertEqual(result["status"], 200)
        self.assertEqual(result["payload"], {"state": "ready", "version": "2026-10-22T21:29:00Z",
                                             "deployed_at": "2026-10-22T21:29:00Z"})

    def test_data_only_commits_do_not_change_the_version(self):
        # auto_deploy moves deployed_sha for commits that only touch generated files; the time stays.
        self.path.write_text(json.dumps({"deployed_sha": "a" * 40, "deployed_at": "2026-10-22T21:29:00Z"}))
        first = self.get()["payload"]["version"]
        self.path.write_text(json.dumps({"deployed_sha": "b" * 40, "deployed_at": "2026-10-22T21:29:00Z"}))
        self.assertEqual(self.get()["payload"]["version"], first)

    def test_missing_or_broken_state_is_unknown_not_an_error(self):
        self.assertEqual(self.get()["payload"]["state"], "unknown")
        for raw in ("not json", json.dumps({"deployed_sha": "abc"}), json.dumps({"deployed_at": "yesterday"}),
                    json.dumps({"deployed_at": "2026-10-22T21:29:00"}), json.dumps([1])):
            self.path.write_text(raw)
            self.assertEqual(self.get()["payload"], {"state": "unknown", "version": None, "deployed_at": None})

    def test_page_offers_refresh_and_phone_icon(self):
        for needle in ('id="site-update"', "/api/site-version", 'rel="manifest"', 'rel="apple-touch-icon"'):
            self.assertIn(needle, PAGE)
        manifest = json.loads((BUILDER / "dashboard-assets" / "manifest.json").read_text())
        self.assertEqual(manifest["display"], "standalone")
        for icon in manifest["icons"]:
            self.assertTrue((BUILDER / "dashboard-assets" / Path(icon["src"]).name).is_file())


if __name__ == "__main__":
    unittest.main()
