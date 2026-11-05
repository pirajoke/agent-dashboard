"""«Генеалогия» tab (Mark 2026-11-05): private family data, owner-only endpoint, page carries no data."""
from __future__ import annotations

import json
from pathlib import Path
import re
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dashboard_builder.genealogy import GenealogyUnavailable, load_genealogy  # noqa: E402

PAGE = ROOT / "mac-mini-dashboard" / "index.html"
SERVER = ROOT / "dashboard-server-m4.py"


class LoadGenealogyTest(unittest.TestCase):
    def write(self, data) -> Path:
        tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
        tmp.write(data if isinstance(data, str) else json.dumps(data))
        tmp.close()
        self.addCleanup(Path(tmp.name).unlink)
        return Path(tmp.name)

    def test_drops_dangling_links_bad_places_and_duplicates(self):
        path = self.write({
            "places": {"a": {"name": "A", "lat": 53.0, "lon": 30.0}, "bad": {"name": "B", "lat": 200, "lon": 0}},
            "people": [
                {"id": "p1", "name": "One", "parents": ["ghost"], "spouses": ["p2"],
                 "stops": [{"y": 1900, "p": "a"}, {"y": 1910, "p": "bad"}, {"y": 1920, "p": "nowhere"}]},
                {"id": "p2", "name": "Two", "parents": "x"},
                {"id": "p2", "name": "Duplicate"},
                {"name": "No id"},
                "junk",
            ],
            "branches": [{"key": "one", "name": "Line", "color": "#123456", "roots": ["p1", "ghost"]}, "junk"],
        })
        record = load_genealogy(path)
        self.assertEqual(record["state"], "ready")
        self.assertEqual([p["id"] for p in record["people"]], ["p1", "p2"])
        one, two = record["people"]
        self.assertEqual(one["parents"], [])
        self.assertEqual(one["spouses"], ["p2"])
        self.assertEqual([s["p"] for s in one["stops"]], ["a"])
        self.assertEqual(two["parents"], [])
        self.assertEqual(set(record["places"]), {"a"})
        self.assertEqual(record["branches"], [{"key": "one", "name": "Line", "color": "#123456", "roots": ["p1"]}])

    def test_malformed_files_are_unavailable(self):
        for data in ("not json", [], {"people": {}}, {"people": [], "places": []}):
            with self.subTest(data=data):
                with self.assertRaises(GenealogyUnavailable):
                    load_genealogy(self.write(data))

    def test_missing_file_is_not_found(self):
        with self.assertRaises(FileNotFoundError):
            load_genealogy(Path(tempfile.gettempdir()) / "no-such-genealogy.json")


class GenealogyWiringTest(unittest.TestCase):
    def test_endpoint_is_owner_only(self):
        server = SERVER.read_text(encoding="utf-8")
        block = server[server.index("if parsed.path == '/api/genealogy':"):][:900]
        owner = block.index("_decision_owner_authorized()")
        self.assertLess(owner, block.index("load_genealogy("), "the owner check must come before reading the file")
        self.assertIn("401", block[:block.index("load_genealogy(")])

    def test_page_reads_the_api_and_embeds_no_family_data(self):
        html = PAGE.read_text(encoding="utf-8")
        self.assertIn('id="section-genealogy"', html)
        self.assertIn("${DASHBOARD_API}/api/genealogy", html)
        self.assertIn("if (name === 'genealogy') setTimeout(genLoad, 0);", html)
        self.assertNotIn("genealogy.json", html)
        # Family surnames and places from the private file must not be in the public page.
        for word in ("Рудник", "Муравич", "Яндашевск", "Грачёвы", "Афанасьев", "Губята", "Мордюшенко"):
            self.assertIsNone(re.search(word, html), word)


if __name__ == "__main__":
    unittest.main()
