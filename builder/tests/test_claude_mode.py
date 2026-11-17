"""Claude Code permission mode switch on Архитектура (Mark 2026-11-17)."""
from __future__ import annotations

import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

BUILDER = Path(__file__).resolve().parents[1]


def _load(name, file):
    spec = importlib.util.spec_from_file_location(name, BUILDER / file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SWITCH = _load("claude_mode_switch_test", "claude_mode_switch.py")
SERVER = _load("dashboard_claude_mode_test", "dashboard-server-m4.py")
PAGE = (BUILDER / "mac-mini-dashboard" / "index.html").read_text()

SETTINGS = {
    "permissions": {"allow": ["Bash(git status)"], "deny": ["Bash(sudo *)"], "defaultMode": "auto"},
    "autoMode": {"environment": ["$defaults"]},
    "theme": "dark",
}


class SwitchTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.home = Path(temp.name)
        (self.home / ".claude").mkdir()
        self.settings = self.home / ".claude" / "settings.json"
        self.settings.write_text(json.dumps(SETTINGS, indent=2))
        os.chmod(self.settings, 0o644)
        self.base = self.home / ".claude-mode"
        env = patch.dict(os.environ, {"CLAUDE_MODE_DIR": str(self.base), "CLAUDE_MODE_SETTINGS": str(self.settings)})
        env.start()
        self.addCleanup(env.stop)
        self.now = 1_800_000_000.0

    def ask(self, mode, *, request_id="1800000000-abcdef12", token="good", at=None):
        inbox = self.base / "inbox"
        inbox.mkdir(parents=True, exist_ok=True)
        (inbox / f"{request_id}.json").write_text(json.dumps(
            {"id": request_id, "mode": mode, "requested_at": self.now if at is None else at, "token": token}))

    def run_switch(self):
        return SWITCH.process(self.home, lambda token: "owner@example.com" if token == "good" else None, now=self.now)

    def test_bypass_and_back_keep_the_lists(self):
        self.ask("bypass")
        state = self.run_switch()
        data = json.loads(self.settings.read_text())
        self.assertEqual(state["mode"], "bypass")
        self.assertEqual(data["permissions"]["defaultMode"], "bypassPermissions")
        self.assertTrue(data["skipDangerousModePermissionPrompt"])
        self.assertEqual(state["last_request"]["event"], "switched")
        self.assertEqual(self.settings.stat().st_mode & 0o777, 0o644)

        self.now += 60
        self.ask("standard", request_id="1800000060-abcdef12")
        state = self.run_switch()
        data = json.loads(self.settings.read_text())
        self.assertEqual(state["mode"], "standard")
        self.assertEqual(data, SETTINGS)
        self.assertEqual(len(list((self.base / "backups").iterdir())), 2)
        self.assertEqual([e["event"] for e in state["recent"]], ["switched", "switched"])
        self.assertEqual(state["recent"][0]["by"], "owner@example.com")
        self.assertFalse(list((self.base / "inbox").iterdir()))
        self.assertNotIn("good", (self.base / "switch.log").read_text())

    def test_refuses_unsigned_stale_repeated_and_unknown(self):
        cases = [
            ({"token": "forged"}, "not_signed_in_owner"),
            ({"at": 1_800_000_000.0 - 600}, "stale_request"),
            ({"request_id": "../../etc"}, None),
        ]
        for index, (kwargs, reason) in enumerate(cases):
            kwargs.setdefault("request_id", f"1800000000-0000000{index}")
            self.ask("bypass", **kwargs)
            state = self.run_switch()
            self.assertEqual(state["mode"], "standard")
            self.assertEqual(state["recent"][0]["event"], "refused")
            if reason:
                self.assertEqual(state["recent"][0]["reason"], reason)
        self.ask("root", request_id="1800000000-00000009")
        self.assertEqual(self.run_switch()["recent"][0]["reason"], "unknown_mode")
        self.ask("bypass", request_id="1800000000-00000000")
        self.assertEqual(self.run_switch()["recent"][0]["reason"], "bad_or_repeated_id")
        self.assertEqual(json.loads(self.settings.read_text()), SETTINGS)
        self.assertFalse((self.base / "backups").exists())

    def test_damaged_settings_are_never_overwritten(self):
        self.settings.write_text("{broken")
        self.ask("bypass")
        state = self.run_switch()
        self.assertEqual(self.settings.read_text(), "{broken")
        self.assertEqual((state["mode"], state["recent"][0]["event"]), ("unknown", "refused"))

    def test_a_hand_edit_is_noticed(self):
        self.run_switch()
        data = json.loads(self.settings.read_text())
        data["permissions"]["defaultMode"] = "bypassPermissions"
        self.settings.write_text(json.dumps(data))
        state = self.run_switch()
        self.assertEqual((state["mode"], state["recent"][0]["event"]), ("bypass", "changed_outside"))


    def test_junk_in_log_and_inbox_does_not_jam_the_switch(self):
        self.base.mkdir()
        (self.base / "switch.log").write_text('1\n{broken\n{"id": "1800000000-11111111", "event": "refused"}\n')
        (self.base / "inbox").mkdir()
        (self.base / "inbox" / ".DS_Store").write_text("x")
        self.ask("bypass", request_id="1800000000-11111111")
        state = self.run_switch()
        self.assertEqual((state["mode"], state["recent"][0]["reason"]), ("standard", "bad_or_repeated_id"))
        self.assertFalse(list((self.base / "inbox").iterdir()))

    def test_a_mode_of_its_own_is_left_alone(self):
        data = json.loads(self.settings.read_text())
        data["permissions"]["defaultMode"] = "plan"
        self.settings.write_text(json.dumps(data))
        self.ask("bypass")
        state = self.run_switch()
        self.assertEqual((state["mode"], state["recent"][0]["reason"]), ("other", "other_mode_left_alone"))
        self.assertEqual(json.loads(self.settings.read_text()), data)

    def test_the_access_app_is_pinned_not_read_from_disk(self):
        source = (BUILDER / "claude_mode_switch.py").read_text()
        self.assertNotIn("cloudflare_access.json", source)
        self.assertNotIn("configured_access_app", source)


class EndpointTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name) / ".claude-mode"

    def call(self, method, body=None, *, access=True, token="fixture-owner", host="command.meshly.fr", origin="https://command.meshly.fr"):
        handler = SERVER.Handler.__new__(SERVER.Handler)
        handler.path, handler.command = "/api/claude-mode", method
        data = json.dumps(body or {}).encode()
        handler.headers = {"Host": host, "Content-Length": str(len(data)), "Content-Type": "application/json",
                           "Origin": origin, "Cf-Access-Jwt-Assertion": "jwt" if access else ""}
        if token is not None:
            handler.headers["X-Dashboard-Run-Token"] = token
        handler.rfile = io.BytesIO(data)
        output = {}
        handler._json_response = lambda status, payload: output.update(status=status, payload=payload)
        with (patch.object(SERVER, "CLAUDE_MODE_DIR", self.base),
              patch.object(SERVER, "_dashboard_run_token", return_value="fixture-owner"),
              patch.object(SERVER.Handler, "_cloudflare_access_owner", return_value=access)):
            getattr(handler, f"do_{method}")()
        return output

    def test_signed_in_owner_queues_a_request_with_the_sign_in(self):
        reply = self.call("POST", {"mode": "bypass"})
        self.assertEqual((reply["status"], reply["payload"]["state"]), (202, "pending"))
        files = list((self.base / "inbox").iterdir())
        self.assertEqual(len(files), 1)
        request = json.loads(files[0].read_text())
        self.assertEqual((request["mode"], request["token"], request["id"]), ("bypass", "jwt", reply["payload"]["id"]))
        self.assertTrue(SWITCH.REQUEST_ID.match(request["id"]))
        self.assertEqual(files[0].stat().st_mode & 0o777, 0o600)
        view = self.call("GET")
        self.assertEqual((view["status"], view["payload"]["agent"], view["payload"]["pending"]), (200, "missing", [request["id"]]))
        self.assertNotIn("jwt", json.dumps(view["payload"]))

    def test_the_owner_key_alone_cannot_switch(self):
        # Agents on the Mac mini can read the owner key; only a Cloudflare Access sign-in may ask.
        self.assertEqual(self.call("POST", {"mode": "bypass"}, access=False)["status"], 401)
        self.assertEqual(self.call("POST", {"mode": "root"})["status"], 400)
        self.assertEqual(self.call("GET", access=False, token=None)["status"], 401)
        self.assertFalse((self.base / "inbox").exists())

    def test_state_is_read_back(self):
        self.base.mkdir()
        (self.base / "state.json").write_text(json.dumps({"schema": "claude_mode_v1", "mode": "bypass",
                                                          "observed_at": SWITCH._iso(time.time()), "recent": []}))
        view = self.call("GET")["payload"]
        self.assertEqual((view["mode"], view["agent"], view["pending"]), ("bypass", "ok", []))


class PageTests(unittest.TestCase):
    def test_switch_lives_on_architecture_and_is_owner_only(self):
        arch = PAGE[PAGE.index('id="section-architecture"'):PAGE.index('id="arch-state"')]
        self.assertIn('id="claude-mode" data-mode="unknown" hidden', arch)
        self.assertIn('role="switch"', arch)
        self.assertIn("setTimeout(claudeModeLoad, 0)", PAGE)
        self.assertIn("/api/claude-mode", PAGE)


if __name__ == "__main__":
    unittest.main()
