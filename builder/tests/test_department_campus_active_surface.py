from __future__ import annotations

from html.parser import HTMLParser
import http.server
from pathlib import Path
import re
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch
import importlib.util


BUILDER_DIR = Path(__file__).resolve().parents[1]
SERVER_PATH = BUILDER_DIR / "dashboard-server-m4.py"
SURFACE_PATH = "/department-campus.html"

SERVER_SPEC = importlib.util.spec_from_file_location(
    "dashboard_server_active_department_campus",
    SERVER_PATH,
)
SERVER = importlib.util.module_from_spec(SERVER_SPEC)
assert SERVER_SPEC and SERVER_SPEC.loader
SERVER_SPEC.loader.exec_module(SERVER)


class _PixelAgentsFrameParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.sources: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        classes = (attributes.get("class") or "").split()
        if tag == "iframe" and "pixel-agents-frame" in classes:
            self.sources.append(attributes.get("src") or "")


class ActiveDepartmentCampusSurfaceTests(unittest.TestCase):
    def _public_request(self, method: str = "GET") -> tuple[int, str, str]:
        with patch.object(SERVER, "HOME", BUILDER_DIR):
            server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), SERVER.Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                request = urllib.request.Request(
                    f"http://127.0.0.1:{server.server_port}{SURFACE_PATH}",
                    method=method,
                    headers={"Host": "command.meshly.fr"},
                )
                try:
                    with urllib.request.urlopen(request, timeout=3) as response:
                        return (
                            response.status,
                            response.headers.get_content_type(),
                            response.read().decode("utf-8"),
                        )
                except urllib.error.HTTPError as exc:
                    return (
                        exc.code,
                        exc.headers.get_content_type(),
                        exc.read().decode("utf-8", errors="replace"),
                    )
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=3)

    def test_ac_active_1_agents_defaults_to_same_origin_department_campus(self):
        root_html = (BUILDER_DIR / "mac-mini-dashboard" / "index.html").read_text(
            encoding="utf-8"
        )
        parser = _PixelAgentsFrameParser()
        parser.feed(root_html)

        self.assertEqual(
            parser.sources,
            [SURFACE_PATH],
            "the production Agents iframe must default to the same-origin Department Campus",
        )
        self.assertNotIn("https://pixel-agents.meshly.fr", parser.sources)

    def test_ac_active_2_public_get_returns_standalone_campus_document(self):
        status, content_type, html = self._public_request()

        self.assertEqual(status, 200, f"public GET {SURFACE_PATH} returned HTTP {status}")
        self.assertEqual(content_type, "text/html")
        self.assertRegex(html.lstrip(), r"(?i)^<!doctype\s+html>")
        self.assertRegex(html, r"(?i)<html\b[^>]*>[\s\S]*</html>\s*$")
        self.assertEqual(html.count('id="department-campus"'), 1)
        self.assertRegex(
            html,
            r"fetch\(\s*['\"]\/api\/manager\/departments['\"]",
        )

    def test_ac_active_3_campus_surface_is_strictly_read_only(self):
        status, _content_type, html = self._public_request()

        self.assertEqual(status, 200, f"public GET {SURFACE_PATH} returned HTTP {status}")
        self.assertNotRegex(html, r"(?i)<(?:form|input|textarea|select)\b")
        self.assertNotRegex(html, r"(?i)\bmethod\s*:\s*['\"](?:POST|PUT|PATCH|DELETE)['\"]")
        self.assertNotRegex(
            html,
            r"data-(?:action|campus-action)=['\"]"
            r"(?:dispatch|merge|deploy|publish|delete|credential|payment)['\"]",
        )
        post_status, _post_content_type, post_body = self._public_request(method="POST")
        self.assertEqual(post_status, 403)
        self.assertIn("public_dashboard_read_only", post_body)


if __name__ == "__main__":
    unittest.main()
