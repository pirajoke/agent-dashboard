"""«Журнал починок» for the Медик (Mark 2026-11-02)."""
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest

from dashboard_builder import repair_log

NOW = datetime(2026, 11, 2, 10, 0, tzinfo=timezone.utc)


class RepairLogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "machine-repairs.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_missing_file_is_an_empty_log(self):
        self.assertEqual(repair_log.load_entries(self.path), {"entries": []})

    def test_add_keeps_newest_first_and_survives_reload(self):
        repair_log.change_entries(self.path, {"action": "add", "machine": "pro", "date": "2026-10-30",
                                              "problem": "Mac тормозил", "fix": "Закрыли Google Drive и Plaud",
                                              "signs": ["cpu", "ram", "bogus"]}, now=NOW)
        record = repair_log.change_entries(self.path, {"action": "add", "machine": "mini",
                                                       "problem": "Диск заполнялся", "fix": "Удалили старые дампы",
                                                       "signs": ["disk"]}, now=NOW)
        self.assertEqual([e["date"] for e in record["entries"]], ["2026-11-02", "2026-10-30"])
        self.assertEqual(record["entries"][1]["signs"], ["cpu", "ram"])
        self.assertEqual(repair_log.load_entries(self.path), record)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_bad_input_is_refused_without_touching_the_file(self):
        for body in ({"action": "add", "machine": "pc", "problem": "x", "fix": "y"},
                     {"action": "add", "machine": "pro", "problem": "", "fix": "y"},
                     {"action": "add", "machine": "pro", "problem": "x", "fix": "y", "date": "вчера"},
                     {"action": "add", "machine": "pro", "problem": "x" * 301, "fix": "y"},
                     {"action": "drop"}):
            with self.subTest(body=body), self.assertRaises(ValueError):
                repair_log.change_entries(self.path, body, now=NOW)
        self.assertFalse(self.path.exists())

    def test_remove_by_id(self):
        record = repair_log.change_entries(self.path, {"action": "add", "machine": "pro", "problem": "x", "fix": "y"}, now=NOW)
        entry_id = record["entries"][0]["id"]
        self.assertEqual(repair_log.change_entries(self.path, {"action": "remove", "id": entry_id})["entries"], [])
        with self.assertRaises(LookupError):
            repair_log.change_entries(self.path, {"action": "remove", "id": entry_id})

    def test_broken_file_is_an_error_not_an_empty_log(self):
        self.path.write_text("{not json", encoding="utf-8")
        with self.assertRaises(repair_log.StoreUnavailable):
            repair_log.load_entries(self.path)
        with self.assertRaises(repair_log.StoreUnavailable):
            repair_log.change_entries(self.path, {"action": "add", "machine": "pro", "problem": "x", "fix": "y"})
        self.assertEqual(self.path.read_text(encoding="utf-8"), "{not json")

    def test_cli_appends_an_entry(self):
        code = repair_log.main(["add", "--machine", "pro", "--problem", "Тормозил", "--fix", "Закрыл Plaud",
                                "--sign", "cpu", "--date", "2026-10-31", "--file", str(self.path)])
        self.assertEqual(code, 0)
        entries = json.loads(self.path.read_text(encoding="utf-8"))["entries"]
        self.assertEqual((entries[0]["machine"], entries[0]["by"], entries[0]["signs"]), ("pro", "claude", ["cpu"]))


if __name__ == "__main__":
    unittest.main()
