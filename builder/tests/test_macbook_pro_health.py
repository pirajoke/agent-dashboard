from __future__ import annotations

import importlib.util
import re
import tempfile
import unittest
from pathlib import Path


BUILDER_DIR = Path(__file__).resolve().parents[1]
HEALTH_PATH = BUILDER_DIR / "macbook" / "macbook-pro-health.py"


def load_health_module():
    spec = importlib.util.spec_from_file_location("macbook_pro_health", HEALTH_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ControlAllowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.health = load_health_module()

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.missing = Path(self.tmp.name) / "missing"

    def test_loopback_only_by_default(self) -> None:
        allowed = self.health.load_control_allow({}, self.missing)
        self.assertEqual(allowed, {"127.0.0.1", "::1"})

    def test_env_entries_are_added(self) -> None:
        allowed = self.health.load_control_allow(
            {"MACBOOK_CONTROL_ALLOW": " 10.0.0.5 , ,10.0.0.6", "HEALTH_CONTROL_ALLOW": "10.0.0.7"},
            self.missing,
        )
        self.assertEqual(allowed, {"127.0.0.1", "::1", "10.0.0.5", "10.0.0.6", "10.0.0.7"})

    def test_file_lines_are_added(self) -> None:
        allow_file = Path(self.tmp.name) / "allow"
        allow_file.write_text("10.0.0.8\n\n# comment\n10.0.0.9  # mini\n", encoding="utf-8")
        allowed = self.health.load_control_allow({}, allow_file)
        self.assertEqual(allowed, {"127.0.0.1", "::1", "10.0.0.8", "10.0.0.9"})

    def test_env_and_file_combine(self) -> None:
        allow_file = Path(self.tmp.name) / "allow"
        allow_file.write_text("10.0.0.8\n", encoding="utf-8")
        allowed = self.health.load_control_allow({"MACBOOK_CONTROL_ALLOW": "10.0.0.5"}, allow_file)
        self.assertEqual(allowed, {"127.0.0.1", "::1", "10.0.0.5", "10.0.0.8"})

    def test_no_tailnet_address_in_source(self) -> None:
        source = HEALTH_PATH.read_text(encoding="utf-8")
        self.assertIsNone(re.search(r"\b100\.\d+\.\d+\.\d+\b", source))


if __name__ == "__main__":
    unittest.main()
