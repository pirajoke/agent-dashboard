"""«Где лежит работа»: GitHub, Linear and Notion on «Платформы» (Mark 2026-10-29)."""
from __future__ import annotations

from pathlib import Path
import unittest
import urllib.error

from dashboard_builder import work_tools

HTML = (Path(__file__).resolve().parents[1] / "mac-mini-dashboard" / "index.html").read_text(encoding="utf-8")


def fetchers(github=None, linear=None, notion=None):
    def wrap(value):
        def fetch():
            if isinstance(value, Exception):
                raise value
            return value
        return fetch
    return {"github": wrap(github), "linear": wrap(linear), "notion": wrap(notion)}


class WorkToolsProjectionTest(unittest.TestCase):
    def setUp(self):
        work_tools.reset_cache()

    def test_everyone_gets_links_but_only_the_owner_gets_live_lists(self):
        calls = []
        public = work_tools.work_tools_projection(owner=False, fetchers={"github": lambda: calls.append(1)})
        self.assertEqual(public["state"], "owner_required")
        self.assertEqual([t["id"] for t in public["tools"]], ["github", "linear", "notion"])
        self.assertTrue(all("live" not in t for t in public["tools"]))
        self.assertEqual(calls, [], "an anonymous visitor must not trigger calls to GitHub, Linear or Notion")

    def test_owner_sees_titles_and_links_per_tool(self):
        pr = {"title": "Новая карточка", "url": "https://github.com/pirajoke/agent-dashboard/pull/1"}
        result = work_tools.work_tools_projection(owner=True, fetchers=fetchers(github=[pr], linear=[], notion=None))
        live = {t["id"]: t["live"] for t in result["tools"]}
        self.assertEqual(live["github"]["state"], "ready")
        self.assertEqual(live["github"]["items"], [pr])
        self.assertEqual(live["linear"], {"title": "В работе", "state": "ready", "items": []})
        self.assertEqual(live["notion"]["state"], "not_configured")

    def test_a_failing_source_is_shown_as_unavailable_not_empty(self):
        result = work_tools.work_tools_projection(owner=True, fetchers=fetchers(
            github=urllib.error.URLError("offline"), linear=[], notion=[]))
        github = next(t for t in result["tools"] if t["id"] == "github")
        self.assertEqual(github["live"]["state"], "unavailable")
        self.assertEqual(github["live"]["items"], [])

    def test_live_lists_are_cached_between_visits(self):
        calls = []
        source = {"github": lambda: calls.append(1) or [], "linear": lambda: None, "notion": lambda: None}
        work_tools.work_tools_projection(owner=True, fetchers=source, now=1000.0)
        work_tools.work_tools_projection(owner=True, fetchers=source, now=1000.0 + work_tools.CACHE_SECONDS - 1)
        self.assertEqual(len(calls), 1)
        work_tools.work_tools_projection(owner=True, fetchers=source, now=1000.0 + work_tools.CACHE_SECONDS + 1)
        self.assertEqual(len(calls), 2)

    def test_items_keep_only_https_links_on_the_tool_own_site(self):
        self.assertIsNone(work_tools._item("x", "http://github.com/a", "github.com"))
        self.assertIsNone(work_tools._item("x", "https://evil.example/github.com", "github.com"))
        self.assertIsNone(work_tools._item("", "https://github.com/a", "github.com"))
        self.assertEqual(work_tools._item("  a\n b ", "https://www.notion.so/p", "notion.so"),
                         {"title": "a b", "url": "https://www.notion.so/p"})
        self.assertEqual(len(work_tools._item("x" * 500, "https://linear.app/i", "linear.app")["title"]), work_tools.TITLE_LIMIT)


class WorkToolsPageTest(unittest.TestCase):
    def test_cards_link_straight_to_each_tool_without_the_api(self):
        section = HTML.split('<section class="work-tools"', 1)[1].split("</section>", 1)[0]
        for tool in work_tools.TOOLS:
            self.assertIn(f'data-work-tool="{tool["id"]}"', section)
            self.assertIn(f'href="{tool["url"]}"', section)
            self.assertIn(f'>{tool["name"]}</a>', section)
        self.assertIn('target="_blank" rel="noopener noreferrer"', section)

    def test_page_loads_live_lists_when_platforms_opens(self):
        self.assertIn("/api/work-tools", HTML)
        self.assertIn("setTimeout(ccLoadWorkTools, 0)", HTML)


if __name__ == "__main__":
    unittest.main()
