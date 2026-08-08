from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch


BUILDER_DIR = Path(__file__).resolve().parents[1]
SERVER_PATH = BUILDER_DIR / "dashboard-server-m4.py"
SERVER_SPEC = importlib.util.spec_from_file_location("dashboard_server_manager_events", SERVER_PATH)
SERVER = importlib.util.module_from_spec(SERVER_SPEC)
assert SERVER_SPEC and SERVER_SPEC.loader
SERVER_SPEC.loader.exec_module(SERVER)


def bridge_task(*, updated_at: str) -> dict:
    return {
        "id": "task-private-fixture",
        "status": "running",
        "project": "ai_studio",
        "description": "<private-description>",
        "result": "<internal-tool-output>",
        "error": "<credential-placeholder>",
        "updated_at": updated_at,
        "metadata": {
            "event": "status",
            "project": "ai_studio",
            "next_safe_step": "verify_evidence",
            "repo_path": "<client-vault-path>",
        },
        "messages": [{"body": "<vault-content>", "metadata": {"event": "handoff"}}],
    }


class ManagerEventServerProjectionTests(unittest.TestCase):
    def test_projection_payload_returns_only_allowlisted_event_shape(self):
        now = datetime(2026, 8, 8, 12, 0, tzinfo=timezone.utc)
        projected = SERVER._manager_event_payload(
            {"tasks": [bridge_task(updated_at="2026-08-08T11:59:00Z")]},
            now=now,
        )

        self.assertEqual(tuple(projected), ("active", "state", "station", "details"))
        self.assertEqual(tuple(projected["details"]), ("project", "time", "status", "next_step"))
        self.assertEqual(projected["details"]["project"], "AI Studio")
        rendered = repr(projected)
        for forbidden in (
            "<private-description>",
            "<internal-tool-output>",
            "<credential-placeholder>",
            "<client-vault-path>",
            "<vault-content>",
        ):
            self.assertNotIn(forbidden, rendered)

    def test_public_endpoint_returns_same_safe_projection_without_raw_task_data(self):
        now = datetime.now(timezone.utc).isoformat()
        response = {}
        requested = []
        handler = SERVER.Handler.__new__(SERVER.Handler)
        handler.path = "/api/manager/events?limit=24"
        handler.headers = {"Host": "command.meshly.fr"}
        handler._json_response = lambda status, payload: response.update(status=status, payload=payload)

        def bridge_request(_method, path, _payload=None):
            requested.append(path)
            return {"tasks": [bridge_task(updated_at=now)]}

        with patch.object(SERVER, "_bridge_request", side_effect=bridge_request):
            handler.do_GET()

        self.assertEqual(response["status"], 200)
        self.assertEqual(requested, ["/api/tasks?limit=24&include_messages=1"])
        self.assertTrue(response["payload"]["active"])
        self.assertEqual(response["payload"]["details"]["project"], "AI Studio")
        self.assertNotIn("<private-description>", repr(response["payload"]))
        self.assertNotIn("<client-vault-path>", repr(response["payload"]))


if __name__ == "__main__":
    unittest.main()
