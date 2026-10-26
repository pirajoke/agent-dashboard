"""Command Center's own employer-replies watcher is retired: replies live in Job Radar (Mark 2026-10-25)."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from dashboard_builder import owner_todo

BUILDER = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("retire_job_mail", BUILDER / "retire_job_mail.py")
RETIRE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RETIRE)


class Response:
    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class RetireTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.root = self.base / "job-mail"
        self.root.mkdir()
        self.todo = self.base / "owner-todo.json"

    def test_grant_is_handed_back_and_deleted(self):
        (self.root / "token.json").write_text(json.dumps({"refresh_token": "r", "email": "x@example.com"}))
        (self.root / "replies.json").write_text("{}")
        calls = []
        self.assertEqual(RETIRE.revoke(self.root, opener=lambda request, timeout=None: calls.append(request.full_url) or Response()),
                         "revoked")
        self.assertEqual(calls, [RETIRE.REVOKE_URL])
        self.assertFalse((self.root / "token.json").exists())
        self.assertTrue((self.root / "replies.json").exists())
        self.assertEqual(RETIRE.revoke(self.root), "no_grant")  # Safe to run again.

    def test_only_the_watchers_open_items_go(self):
        for text in ("Ответить Caf: зовут на собеседование", "Ответить Orus: зовут на собеседование", "Ответить юристу"):
            owner_todo.change_items(self.todo, {"action": "add", "text": text})
        items = owner_todo.load_items(self.todo)["items"]
        by_text = {item["text"]: item["id"] for item in items}
        for text in ("Ответить Caf: зовут на собеседование", "Ответить Orus: зовут на собеседование"):
            owner_todo.set_triage(self.todo, by_text[text], False, RETIRE.WATCHER_NOTE)
        owner_todo.change_items(self.todo, {"action": "done", "id": by_text["Ответить Orus: зовут на собеседование"]})
        self.assertEqual(RETIRE.drop_items(self.todo), 1)
        left = sorted(item["text"] for item in owner_todo.load_items(self.todo)["items"] if item["text"].startswith("Ответить"))
        self.assertEqual(left, ["Ответить Orus: зовут на собеседование", "Ответить юристу"])  # Done history and Mark's own stay.

    def test_page_server_and_deploy_no_longer_carry_it(self):
        self.assertNotIn("mm-job-mail", (BUILDER / "mac-mini-dashboard" / "index.html").read_text())
        self.assertNotIn("/api/job-mail", (BUILDER / "dashboard-server-m4.py").read_text())
        deploy = (BUILDER / "deploy_to_scripts.sh").read_text()
        self.assertIn('launchctl bootout "gui/$(id -u)/$JOB_MAIL_LABEL"', deploy)
        self.assertIn('python3 "$SCRIPTS_DIR/retire_job_mail.py"', deploy)


if __name__ == "__main__":
    unittest.main()
