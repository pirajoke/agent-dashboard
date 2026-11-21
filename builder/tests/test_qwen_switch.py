"""Переключатель Qwen в «Технике» → MacBook Pro (Mark 2026-11-18 «сделай переключатель для qwen в команд центре»)."""
import importlib.util
import io
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import urllib.error
from unittest.mock import patch

BUILDER = Path(__file__).resolve().parents[1]
HTML = BUILDER / "mac-mini-dashboard" / "index.html"
_spec = importlib.util.spec_from_file_location("dashboard_qwen_switch_test", BUILDER / "dashboard-server-m4.py")
SERVER = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(SERVER)


def js_function(source, name):
    start = source.index(f"function {name}(")
    depth = 0
    for index in range(source.index("{", start), len(source)):
        depth += {"{": 1, "}": -1}.get(source[index], 0)
        if depth == 0:
            return source[start:index + 1]
    raise AssertionError(f"unclosed {name}")


class QwenSwitchEndpointTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.payloads = []
        self.machine = lambda method, path, payload=None: self.calls.append((method, path)) or self.payloads.append(payload) or {"ok": True}
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.log = Path(temp.name) / "machine-commands.jsonl"

    def audit(self):
        if not self.log.exists():
            return []
        return [json.loads(line) for line in self.log.read_text(encoding="utf-8").splitlines()]

    def call(self, body, *, token="fixture-owner", origin=None):
        handler = SERVER.Handler.__new__(SERVER.Handler)
        handler.path, handler.command = "/api/machines/ollama", "POST"
        data = json.dumps(body).encode()
        handler.headers = {"Host": "command.meshly.fr", "Content-Length": str(len(data)), "Content-Type": "application/json"}
        if token is not None:
            handler.headers["X-Dashboard-Run-Token"] = token
        if origin is not None:
            handler.headers["Origin"] = origin
        handler.rfile = io.BytesIO(data)
        output = {}
        handler._json_response = lambda status, payload: output.update(status=status, payload=payload)
        handler.send_error = lambda status, *args: output.update(status=status)
        with (patch.dict(SERVER.MACHINE_FIX_TARGETS, {"pro": self.machine}),
              patch.object(SERVER, "MACHINE_COMMAND_LOG", self.log),
              patch.object(SERVER, "_dashboard_run_token", return_value="fixture-owner"),
              patch.object(SERVER.Handler, "_cloudflare_access_owner", return_value=False)):
            handler.do_POST()
        return output

    def test_owner_switches_qwen_on_and_off_through_the_macbook(self):
        on = self.call({"action": "start"})
        off = self.call({"action": "stop"})
        self.assertEqual((on["status"], off["status"]), (200, 200))
        self.assertEqual(self.calls, [("POST", "/api/ollama/start"), ("POST", "/api/ollama/stop")])
        # Each command carries its own request id to the MacBook and leaves «sent» then «done» in the log.
        ids = [payload["request_id"] for payload in self.payloads]
        self.assertEqual(ids, [on["payload"]["request_id"], off["payload"]["request_id"]])
        self.assertNotEqual(ids[0], ids[1])
        self.assertEqual([(e["request_id"], e["command"], e["outcome"]) for e in self.audit()],
                         [(ids[0], "ollama.start", "sent"), (ids[0], "ollama.start", "done"),
                          (ids[1], "ollama.stop", "sent"), (ids[1], "ollama.stop", "done")])
        self.assertEqual(self.log.stat().st_mode & 0o777, 0o600)

    def test_timeout_is_recorded_as_unknown_and_a_brew_failure_as_failed(self):
        def slow(method, path, payload=None):
            raise TimeoutError("timed out")

        self.machine = slow
        unknown = self.call({"action": "start"})
        self.assertEqual((unknown["status"], unknown["payload"]["error"]), (504, "delivery_unknown"))
        self.machine = lambda method, path, payload=None: {"ok": False, "output": "Error: brew"}
        failed = self.call({"action": "stop"})
        self.assertEqual((failed["status"], failed["payload"]["state"]), (502, "failed"))
        self.assertEqual([e["outcome"] for e in self.audit()], ["sent", "unknown", "sent", "failed"])

    def test_strangers_other_sites_and_odd_actions_change_nothing(self):
        self.assertEqual(self.call({"action": "start"}, token=None)["status"], 401)
        self.assertEqual(self.call({"action": "start"}, origin="https://evil.example")["status"], 403)
        for body in ({"action": "restart"}, {"action": "../stop"}, {}):
            with self.subTest(body=body):
                self.assertEqual(self.call(body)["status"], 400)
        self.assertEqual(self.calls, [])

    def test_sleeping_or_old_macbook_is_reported_not_hidden(self):
        def asleep(method, path, payload=None):
            raise ConnectionRefusedError("no route")

        def old_script(method, path, payload=None):
            raise urllib.error.HTTPError(path, 404, "Not Found", {}, None)

        for machine, error in ((asleep, "machine_unreachable"), (old_script, "machine_refused")):
            self.machine = machine
            with self.subTest(error=error):
                result = self.call({"action": "start"})
                self.assertEqual((result["status"], result["payload"]["error"]), (502, error))


@unittest.skipUnless(shutil.which("node"), "node is needed to run the page code")
class QwenSwitchViewTests(unittest.TestCase):
    def view(self, status, pending=None, error=""):
        source = HTML.read_text()
        script = "\n".join([
            js_function(source, "gbRu"),
            js_function(source, "qwenSwitchView"),
            f"console.log(JSON.stringify(qwenSwitchView({json.dumps(status)}, {json.dumps(pending)}, {json.dumps(error)})));",
        ])
        return json.loads(subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True).stdout)

    def test_card_stays_hidden_until_the_macbook_reports_ollama(self):
        self.assertIsNone(self.view(None))
        self.assertIsNone(self.view({"installed": False}))

    def test_off_says_memory_is_free_and_names_the_disk_space(self):
        view = self.view({"installed": True, "running": False, "loaded": [], "disk_gb": 17.3})
        self.assertEqual((view["checked"], view["state"]), (False, "выключена"))
        self.assertIn("Память не занимает", view["note"])
        self.assertIn("17,3 ГБ", view["note"])

    def test_on_and_waiting_versus_model_in_memory(self):
        idle = self.view({"installed": True, "running": True, "loaded": []})
        busy = self.view({"installed": True, "running": True, "loaded": [{"name": "qwen3.8:27b", "size_gb": 18.2}]})
        self.assertEqual((idle["checked"], idle["state"]), (True, "включена"))
        self.assertEqual(busy["state"], "работает")
        self.assertIn("qwen3.8:27b в памяти: 18,2 ГБ", busy["note"])

    def test_switching_shows_progress_and_a_failure_in_words(self):
        pending = self.view({"installed": True, "running": False}, "start")
        self.assertEqual((pending["checked"], pending["busy"], pending["state"]), (True, True, "включаю…"))
        failed = self.view({"installed": True, "running": False}, None, "Не получилось: MacBook не ответил.")
        self.assertEqual((failed["error"], failed["note"]), (True, "Не получилось: MacBook не ответил."))


if __name__ == "__main__":
    unittest.main()
