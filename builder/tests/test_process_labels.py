from __future__ import annotations

from pathlib import Path
import sys
import unittest


BUILDER_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BUILDER_DIR))

from dashboard_builder.fraction import _mcp_label, _short_cmd  # noqa: E402


class ProcessLabelTest(unittest.TestCase):
    """The page is published to GitHub Pages: process labels must not carry local folders."""

    def test_unknown_mcp_servers_are_named_without_their_install_path(self):
        cases = {
            "node /Users/me/.npm/_npx/6583/node_modules/.bin/mcp-pdf-server --stdio": "MCP: mcp-pdf-server",
            "node /Users/me/.npm/_npx/a324/node_modules/.bin/mcp-server-filesystem /Users/me/Downloads":
                "MCP: mcp-server-filesystem",
            "/Users/me/.nvm/versions/node/v24/bin/node /Users/me/mur-mur/packages/mcp-server/dist/src/index.js":
                "MCP: mcp-server",
        }
        for command, label in cases.items():
            self.assertEqual(_mcp_label(command), label)
            self.assertNotIn("/Users/", _mcp_label(command))

    def test_other_node_processes_keep_only_file_names(self):
        self.assertEqual(_short_cmd("node /Users/me/app/server.js --port 3000"), "node server.js --port 3000")
        self.assertNotIn("/Users/", _mcp_label("node /Users/me/tool/dist/run.js --mcp"))


if __name__ == "__main__":
    unittest.main()
