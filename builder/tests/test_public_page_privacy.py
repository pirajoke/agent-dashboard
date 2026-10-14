from __future__ import annotations

from pathlib import Path
import sys
import unittest


BUILDER_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BUILDER_DIR))

from dashboard_builder.html_builder import build_html  # noqa: E402

PUBLIC_SNAPSHOT = BUILDER_DIR.parent / "index.html"

ACTIVE = {
    "name": "POS-DANIEL",
    "status": "Active",
    "open_todos": 3,
    "closed_todos": 1,
    "agents": ["BUILDER"],
    "next_action": "Позвонить Даниилу про договор",
    "freshness_days": 2,
}
DONE = {
    "name": "THESIS-SKEMA",
    "status": "done",
    "open_todos": 0,
    "closed_todos": 5,
    "agents": [],
    "next_action": "—",
    "freshness_days": 40,
}
VAULT_PATH_MARKERS = ("obsidian://", "Tech-Base/TODO.md", "20-Projects/")


class PublicPagePrivacyTest(unittest.TestCase):
    """The built page is published on GitHub Pages (AGENTS.md §10): Obsidian projects stay private."""

    def test_projects_section_publishes_counts_only(self):
        html = build_html([ACTIVE, DONE], "2026-10-14 12:00:00 UTC")

        for private in ("POS-DANIEL", "THESIS-SKEMA", "Позвонить Даниилу", *VAULT_PATH_MARKERS):
            self.assertNotIn(private, html)
        self.assertIn('<div class="section-count">1 active</div>', html)
        self.assertIn("В работе 1, завершено 1.", html)

    def test_published_snapshot_has_no_vault_paths(self):
        snapshot = PUBLIC_SNAPSHOT.read_text(encoding="utf-8")

        for marker in VAULT_PATH_MARKERS:
            self.assertNotIn(marker, snapshot)


if __name__ == "__main__":
    unittest.main()
