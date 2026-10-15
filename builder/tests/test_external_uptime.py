from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / ".github" / "scripts" / "uptime_probe.py"
spec = importlib.util.spec_from_file_location("uptime_probe", SCRIPT)
UPTIME = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(UPTIME)


class UptimeProbeTest(unittest.TestCase):
    def test_missing_access_token_is_unconfigured_not_healthy(self):
        requests = []

        def request(url, headers, timeout):
            requests.append((url, headers, timeout))
            return 200, "application/json", b'{"ok": true}'

        result = UPTIME.probe_all({}, requester=request, sleep=lambda _: None)

        self.assertEqual(result["down"], [])
        self.assertEqual(result["unconfigured"], ["Command Center: Cloudflare Access service token missing"])
        self.assertEqual([item["state"] for item in result["checks"]], ["unconfigured", "healthy"])
        self.assertEqual(len(requests), 1)
        self.assertIn("mydictionary.meshly.fr", requests[0][0])

    def test_access_redirect_is_a_failure_not_a_false_green(self):
        requests = []

        def request(url, headers, timeout):
            requests.append((url, headers, timeout))
            if "command.meshly.fr" in url:
                return 302, "text/html", b"login"
            return 200, "application/json", b'{"ok": true}'

        env = {"CF_ACCESS_CLIENT_ID": "client-id", "CF_ACCESS_CLIENT_SECRET": "client-secret"}
        result = UPTIME.probe_all(env, requester=request, sleep=lambda _: None, attempts=1)

        self.assertEqual(result["unconfigured"], [])
        self.assertEqual(result["down"], ["Command Center: HTTP 302"])
        command_request = requests[0]
        self.assertEqual(
            command_request[1],
            {
                "CF-Access-Client-Id": "client-id",
                "CF-Access-Client-Secret": "client-secret",
            },
        )

    def test_authenticated_json_200_is_healthy(self):
        def request(url, headers, timeout):
            return 200, "application/json; charset=utf-8", b'{"ok": true}'

        env = {"CF_ACCESS_CLIENT_ID": "client-id", "CF_ACCESS_CLIENT_SECRET": "client-secret"}
        result = UPTIME.probe_all(env, requester=request, sleep=lambda _: None)

        self.assertEqual(result["down"], [])
        self.assertEqual(result["unconfigured"], [])
        self.assertEqual([item["state"] for item in result["checks"]], ["healthy", "healthy"])

    def test_command_center_200_must_still_be_json(self):
        def request(url, headers, timeout):
            if "command.meshly.fr" in url:
                return 200, "text/html", b"login"
            return 200, "application/json", b'{"ok": true}'

        env = {"CF_ACCESS_CLIENT_ID": "client-id", "CF_ACCESS_CLIENT_SECRET": "client-secret"}
        result = UPTIME.probe_all(env, requester=request, sleep=lambda _: None, attempts=1)

        self.assertEqual(result["down"], ["Command Center: invalid JSON response"])

    def test_github_output_separates_down_and_configuration(self):
        result = {
            "down": ["Command Center: HTTP 502"],
            "unconfigured": ["Command Center: Cloudflare Access service token missing"],
            "checks": [],
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "output"
            UPTIME.write_github_output(result, path)
            output = path.read_text()

        self.assertIn("down=Command Center: HTTP 502", output)
        self.assertIn("unconfigured=Command Center: Cloudflare Access service token missing", output)


if __name__ == "__main__":
    unittest.main()
