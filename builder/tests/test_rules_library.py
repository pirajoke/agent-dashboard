"""«Правила» tab (Макс 2026-11-23): read-only rule files, escaped Markdown, owner only."""
from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dashboard_builder import rules_library as RULES  # noqa: E402


def write(home: Path, rel: str, text: str) -> None:
    path = home / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class RulesLibraryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        write(self.home, "HQ/hq/jarvis-topics/_rules.md", "# Правила\n\n- один\n- два\n")
        write(self.home, "HQ/hq/jarvis-topics/finance.md", "# 💰 Финансы (обновлено 2026-11-23)\n\nтекст\n")
        write(self.home, "HQ/hq/jarvis-topics/finance.md.bak-20261123", "# old\n")
        write(self.home, "HQ/hq/jarvis-topics/projects.json", "{}")
        write(self.home, "HQ/hq/permissions/pending.md", "# secret-ish\n")
        write(self.home, "HQ/hq/AGENTS.md", "# Штаб\n")
        write(self.home, "AGENTS.md", "# Общие\n")
        (self.home / "HQ/hq/CLAUDE.md").symlink_to("AGENTS.md")
        RULES._cache.clear()

    def tearDown(self):
        self.tmp.cleanup()

    def test_lists_rule_files_grouped_and_skips_backups(self):
        data = RULES.collect(self.home)
        groups = {g["id"]: [f["title"] for f in g["files"]] for g in data["groups"]}
        self.assertEqual(groups["jarvis"], ["Правила Джарвиса", "Тема: 💰 Финансы"])
        self.assertEqual(groups["agents"], ["Общие правила (установлены на Mac mini)", "Правила штаба"])  # CLAUDE.md symlink is the same file
        paths = [f["path"] for g in data["groups"] for f in g["files"]]
        self.assertFalse(any(".bak" in p or "permissions" in p or p.endswith(".json") for p in paths))
        self.assertTrue(all(p.startswith("~/") for p in paths))

    def test_skills_registry_has_its_own_group(self):
        write(self.home, "HQ/hq/skills-registry.md", "# Реестр скиллов штаба\n\n| Скилл | Статус |\n|---|---|\n| `redaktura` | включён |\n")
        data = RULES.collect(self.home)
        skills = [g for g in data["groups"] if g["id"] == "skills"]
        self.assertEqual([f["title"] for f in skills[0]["files"]], ["Реестр скиллов"])
        self.assertIn("<code>redaktura</code>", skills[0]["files"][0]["html"])

    def test_public_sees_only_a_count(self):
        data = RULES.projection(self.home, owner=False)
        self.assertEqual(data, {"ok": True, "owner_view": False, "count": 4})
        self.assertTrue(RULES.projection(self.home, owner=True)["owner_view"])

    def test_cache_is_at_most_a_minute(self):
        RULES.projection(self.home, owner=True, now=1000.0)
        write(self.home, "HQ/hq/docs/max-words.md", "# Слова\n")
        self.assertEqual(RULES.projection(self.home, owner=False, now=1030.0)["count"], 4)
        self.assertEqual(RULES.projection(self.home, owner=False, now=1061.0)["count"], 5)

    def test_markdown_is_escaped(self):
        out = RULES.render_markdown("# T <b>\n\n**жирно** `<x>` [s](https://a.b/c)\n\n<script>alert(1)</script>\n\n| a | b |\n|---|---|\n| 1 | <i> |\n")
        self.assertIn("<h2>T &lt;b&gt;</h2>", out)
        self.assertIn("<strong>жирно</strong>", out)
        self.assertIn("<code>&lt;x&gt;</code>", out)
        self.assertIn('<a href="https://a.b/c"', out)
        self.assertNotIn("<script>", out)
        self.assertIn("<td>&lt;i&gt;</td>", out)

    def test_nested_lists(self):
        out = RULES.render_markdown("- a\n  - b\n- c\n\n1. x\n2. y\n")
        self.assertEqual(out.count("<ul>"), 2)
        self.assertEqual(out.count("</ul>"), 2)
        self.assertEqual(out.count("<ol>"), 1)
        self.assertEqual(out.count("</ol>"), 1)

    def test_symlink_out_of_hq_is_not_read(self):
        outside = self.home / "elsewhere" / "secret.md"
        outside.parent.mkdir()
        outside.write_text("# leak\n")
        (self.home / "HQ/hq/jarvis-topics/evil.md").symlink_to(outside)
        (self.home / "HQ/hq/jarvis-topics/perm.md").symlink_to(self.home / "HQ/hq/permissions/pending.md")
        html_all = " ".join(f["html"] for g in RULES.collect(self.home)["groups"] for f in g["files"])
        self.assertNotIn("leak", html_all)
        self.assertNotIn("secret-ish", html_all)

    def test_odd_input_does_not_break(self):
        self.assertIn('href="https://a.b/?x=1&amp;y=2"', RULES.render_markdown("[l](https://a.b/?x=1&y=2)"))
        self.assertIn("остаток", RULES.render_markdown("<!-- открыт\n\nостаток"))
        RULES.render_markdown("a \x000\x00 `b`")
        self.assertNotEqual(RULES._file_id(self.home, self.home / "_rules.md"), RULES._file_id(self.home, self.home / "rules.md"))

    def test_javascript_links_are_not_links(self):
        out = RULES.render_markdown("[x](javascript:alert(1))")
        self.assertNotIn("<a ", out)


if __name__ == "__main__":
    unittest.main()
