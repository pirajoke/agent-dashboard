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

    def test_new_entry_keeps_its_time_and_same_day_entries_stay_newest_first(self):
        repair_log.change_entries(self.path, {"action": "add", "machine": "mini", "problem": "a", "fix": "b"}, now=NOW)
        later = datetime(2026, 11, 2, 14, 5, tzinfo=timezone.utc)
        record = repair_log.change_entries(self.path, {"action": "add", "machine": "mini", "problem": "c", "fix": "d"}, now=later)
        self.assertEqual([e["at"] for e in record["entries"]], ["2026-11-02T14:05:00Z", "2026-11-02T10:00:00Z"])
        self.assertEqual(repair_log.load_entries(self.path), record)
        backdated = repair_log.change_entries(self.path, {"action": "add", "machine": "pro", "date": "2026-10-30",
                                                          "problem": "e", "fix": "f"}, now=NOW)
        self.assertNotIn("at", backdated["entries"][-1])

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


import importlib.util
import io
from unittest.mock import patch

BUILDER = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("dashboard_repair_log_test", BUILDER / "dashboard-server-m4.py")
SERVER = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(SERVER)


class MedicEndpointTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "machine-repairs.json"
        self.calls = []

    def call(self, path, method, body=None, *, token="fixture-owner", host="command.meshly.fr", origin=None):
        handler = SERVER.Handler.__new__(SERVER.Handler)
        handler.path, handler.command = path, method
        data = json.dumps(body or {}).encode()
        handler.headers = {"Host": host, "Content-Length": str(len(data)), "Content-Type": "application/json"}
        if token is not None:
            handler.headers["X-Dashboard-Run-Token"] = token
        if origin is not None:
            handler.headers["Origin"] = origin
        handler.rfile = io.BytesIO(data)
        output = {}
        handler._json_response = lambda status, payload: output.update(status=status, payload=payload)
        handler.send_error = lambda status, *args: output.update(status=status)
        fake = lambda method, path, payload=None: self.calls.append((method, path)) or {"ok": True}
        with (patch.object(SERVER, "REPAIR_LOG_FILE", self.path),
              patch.dict(SERVER.MACHINE_FIX_TARGETS, {"mini": fake, "pro": fake, "air": fake}),
              patch.object(SERVER.time, "sleep", lambda _: None),
              patch.object(SERVER, "_dashboard_run_token", return_value="fixture-owner"),
              patch.object(SERVER.Handler, "_cloudflare_access_owner", return_value=False)):
            getattr(handler, f"do_{method}")()
        return output

    def test_owner_reads_and_adds_repairs_on_the_public_host(self):
        self.assertEqual(self.call("/api/machines/repairs", "GET")["payload"], {"state": "ready", "entries": []})
        saved = self.call("/api/machines/repairs", "POST", {"action": "add", "machine": "pro", "problem": "x", "fix": "y"})
        self.assertEqual((saved["status"], saved["payload"]["entries"][0]["machine"]), (200, "pro"))

    def test_owner_starts_and_restarts_a_service_on_the_public_host(self):
        done = self.call("/api/machines/fix", "POST", {"machine": "pro", "label": "com.mark.murmur", "action": "start"})
        self.assertEqual((done["status"], self.calls), (200, [("POST", "/api/service/com.mark.murmur/start")]))
        self.calls.clear()
        self.call("/api/machines/fix", "POST", {"machine": "mini", "label": "com.x.web", "action": "restart"})
        self.assertEqual(self.calls, [("POST", "/api/service/com.x.web/stop"), ("POST", "/api/service/com.x.web/start")])

    def test_fix_refuses_strangers_and_odd_input(self):
        self.assertEqual(self.call("/api/machines/fix", "POST", {"machine": "pro", "label": "a", "action": "start"}, token=None)["status"], 401)
        self.assertEqual(self.call("/api/machines/repairs", "GET", token=None)["status"], 401)
        for body in ({"machine": "pc", "label": "a", "action": "start"},
                     {"machine": "pro", "label": "../etc", "action": "start"},
                     {"machine": "pro", "label": "a/b", "action": "start"},
                     {"machine": "pro", "label": "a", "action": "stop"}):
            with self.subTest(body=body):
                self.assertEqual(self.call("/api/machines/fix", "POST", body)["status"], 400)
        self.assertEqual(self.calls, [])
