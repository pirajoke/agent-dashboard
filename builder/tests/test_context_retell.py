import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

BUILDER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BUILDER))

import context_retell as RETELL  # noqa: E402
from dashboard_builder.context_library import context_library_projection  # noqa: E402

FAKE_CLAUDE = '''#!/usr/bin/env python3
import json, os, re, sys
prompt = sys.stdin.read()
with open(os.environ["FAKE_CLAUDE_LOG"], "a", encoding="utf-8") as log:
    log.write(json.dumps(sys.argv[1:]) + "\\n")
if os.environ.get("FAKE_CLAUDE_MODE") == "error":
    print(json.dumps({"is_error": True, "result": "boom"})); sys.exit(1)
ids = re.findall(r'"id": "([a-f0-9]{32})"', prompt)
answer = {i: {"title": "Имена папок вернули", "text": "Агент вернул старые названия папок. Делать ничего не нужно."} for i in ids}
print(json.dumps({"result": "Вот ответ: " + json.dumps(answer, ensure_ascii=False)}))
'''

ENGLISH = """# DOCXX - Russia names restored

Recorded: 2026-10-25T00:44:30+02:00

## Summary
Restored 161 Drive names in the Russia subtree.

## State
- Branch: _not provided_
"""


def record(rid, body=ENGLISH, title="DOCXX - Russia names restored", kind="update", sha="s1", modified="2026-10-25T00:00:00Z"):
    return {"id": rid, "kind": kind, "source": "project-update" if kind == "update" else "plaud", "title": title,
            "date": "2026-10-25", "modified_at": modified, "project": "DOCXX", "relative_path": "x.md",
            "source_id": rid, "sha256": sha, "obsidian_url": "obsidian://open?vault=V&file=x", "body": body}


class ContextRetellTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.catalog = root / "context-library" / "catalog.json"
        self.catalog.parent.mkdir()
        self.cli = root / "claude"
        self.cli.write_text(FAKE_CLAUDE, encoding="utf-8")
        self.cli.chmod(0o755)
        self.log = root / "calls.log"
        self.env = patch.dict(os.environ, {"FAKE_CLAUDE_LOG": str(self.log), "FAKE_CLAUDE_MODE": "ok"})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def write_catalog(self, records):
        self.catalog.write_text(json.dumps({"schema": 1, "state": "ready", "generated_at": "2026-10-25T00:00:00Z",
                                            "records": records, "sources": [], "issues": []}), encoding="utf-8")

    def run_main(self, *extra):
        return RETELL.main(["--catalog", str(self.catalog), "--claude", str(self.cli), *extra])

    def calls(self):
        return self.log.read_text().splitlines() if self.log.exists() else []

    def test_summary_section_is_what_gets_retold(self):
        self.assertEqual(RETELL.summary_text(ENGLISH, "DOCXX - Russia names restored"),
                         "Restored 161 Drive names in the Russia subtree.")
        self.assertEqual(RETELL.summary_text("Recorded: now\n\nJust one paragraph.", "t"), "Just one paragraph.")

    def test_russian_updates_and_meetings_are_left_alone(self):
        self.write_catalog([
            record("a" * 32),
            record("b" * 32, body="## Итог\nСделали новую страницу.", title="Новая страница"),
            record("c" * 32, kind="transcript"),
        ])
        due = RETELL.due_records(json.loads(self.catalog.read_text()), {})
        self.assertEqual([r["id"] for r in due], ["a" * 32])

    def test_run_writes_retelling_once_and_again_after_an_edit(self):
        self.write_catalog([record("a" * 32)])
        self.assertEqual(self.run_main(), 0)
        retold = json.loads((self.catalog.parent / "retold.json").read_text())
        item = retold["items"]["a" * 32]
        self.assertEqual((item["title"], item["sha256"]), ("Имена папок вернули", "s1"))
        self.assertEqual(len(self.calls()), 1)
        args = json.loads(self.calls()[0])
        self.assertIn("--strict-mcp-config", args)
        self.assertEqual(args[args.index("--tools") + 1], "")

        self.run_main()
        self.assertEqual(len(self.calls()), 1)  # unchanged text is not asked again

        self.write_catalog([record("a" * 32, sha="s2")])
        self.run_main()
        self.assertEqual(len(self.calls()), 2)

    def test_errors_are_reported_without_writing_items(self):
        os.environ["FAKE_CLAUDE_MODE"] = "error"
        self.write_catalog([record("a" * 32)])
        self.assertEqual(self.run_main(), 1)
        retold = json.loads((self.catalog.parent / "retold.json").read_text())
        self.assertEqual(retold["items"], {})
        self.assertFalse(retold["status"]["ok"])
        self.assertEqual(retold["status"]["pending"], 1)

    def test_runs_are_bounded(self):
        self.write_catalog([record(f"{i:032x}", modified=f"2026-10-{i + 1:02d}T00:00:00Z") for i in range(30)])
        self.run_main("--batches", "1")
        retold = json.loads((self.catalog.parent / "retold.json").read_text())
        self.assertEqual(len(retold["items"]), RETELL.BATCH)
        self.assertIn(f"{29:032x}", retold["items"])  # newest first
        self.assertEqual(retold["status"]["pending"], 30 - RETELL.BATCH)

    def test_api_adds_plain_text_only_while_it_matches(self):
        self.write_catalog([record("a" * 32)])
        self.run_main()
        page = context_library_projection(self.catalog, owner=True, now="2026-10-25T00:10:00Z")
        self.assertEqual(page["records"][0]["plain"]["title"], "Имена папок вернули")
        detail = context_library_projection(self.catalog, owner=True, record_id="a" * 32, now="2026-10-25T00:10:00Z")
        self.assertIn("Делать ничего не нужно", detail["record"]["plain"]["text"])

        self.write_catalog([record("a" * 32, sha="s2")])
        page = context_library_projection(self.catalog, owner=True, now="2026-10-25T00:10:00Z")
        self.assertNotIn("plain", page["records"][0])
        self.assertEqual(context_library_projection(self.catalog, owner=False)["records"], [])

    def test_deploy_installs_the_job(self):
        deploy = (BUILDER / "deploy_to_scripts.sh").read_text()
        self.assertIn('cp "$SRC_DIR/context_retell.py"', deploy)
        plist = (BUILDER / "launchd" / "com.pirajoke.context-retell.plist.template").read_text()
        self.assertIn("__SCRIPTS_DIR__/context_retell.py", plist)


if __name__ == "__main__":
    unittest.main()
