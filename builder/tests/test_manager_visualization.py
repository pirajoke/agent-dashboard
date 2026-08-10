from __future__ import annotations

import importlib.util
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from dashboard_builder.agent_theater import build_agent_theater_html
from dashboard_builder.manager_visualization import project_main_manager_event


BUILDER_DIR = Path(__file__).resolve().parents[1]
ASSETS_DIR = BUILDER_DIR / "dashboard-assets"
SERVER_PATH = BUILDER_DIR / "dashboard-server-m4.py"
SERVER_SPEC = importlib.util.spec_from_file_location("dashboard_server_manager_viz", SERVER_PATH)
SERVER = importlib.util.module_from_spec(SERVER_SPEC)
assert SERVER_SPEC and SERVER_SPEC.loader
SERVER_SPEC.loader.exec_module(SERVER)

NOW = datetime(2026, 8, 8, 6, 0, tzinfo=timezone.utc)


def _task(status: str = "pending", **overrides) -> dict:
    task = {
        "id": "private-task-id",
        "project": "AI STUDIO",
        "status": status,
        "description": "PRIVATE PROMPT BODY",
        "result": "PRIVATE TOOL OUTPUT",
        "error": None,
        "updated_at": "2026-08-08T05:45:00Z",
        "metadata": {
            "event": "handoff",
            "triggered_by": "MAIN_MANAGER",
            "next": "/private/example/vault/path",
        },
        "messages": [],
    }
    task.update(overrides)
    return task


class MainManagerEventMappingTests(unittest.TestCase):
    def test_maps_only_the_five_user_facing_states(self):
        cases = {
            "pending": "в очереди",
            "running": "работает",
            "done": "готово",
            "needs_approval": "нужно решение Марка",
            "failed": "ошибка",
        }

        for raw_status, expected in cases.items():
            with self.subTest(raw_status=raw_status):
                event = project_main_manager_event(_task(raw_status), now=NOW)
                self.assertIsNotNone(event)
                self.assertEqual(event["status"], expected)

        self.assertIsNone(project_main_manager_event(_task("cancelled"), now=NOW))

    def test_accepts_structured_task_or_message_manager_markers_only(self):
        self.assertIsNotNone(project_main_manager_event(_task(), now=NOW))
        message_marked = _task(
            metadata={"event": "status"},
            messages=[{
                "sender": "MAIN_MANAGER",
                "receiver": "BUILDER",
                "created_at": "2026-08-08T05:50:00Z",
                "body": "PRIVATE HANDOFF BODY",
                "metadata": {"event": "handoff", "project": "AI STUDIO"},
            }],
        )
        self.assertIsNotNone(project_main_manager_event(message_marked, now=NOW))

        prompt_only = _task(
            description="MAIN_MANAGER told the agent to work",
            metadata={"event": "handoff"},
        )
        self.assertIsNone(project_main_manager_event(prompt_only, now=NOW))

    def test_exposes_exact_safe_fields_and_never_copies_private_content(self):
        event = project_main_manager_event(_task(), now=NOW)

        self.assertEqual(set(event), {"project", "time", "status", "next_safe_step"})
        serialized = str(event)
        for private_value in (
            "private-task-id",
            "PRIVATE PROMPT BODY",
            "PRIVATE TOOL OUTPUT",
            "/private/example/vault/path",
        ):
            self.assertNotIn(private_value, serialized)

    def test_stale_or_path_like_project_event_becomes_honest_idle(self):
        stale = _task(updated_at="2026-08-07T20:00:00Z")
        self.assertIsNone(project_main_manager_event(stale, now=NOW))
        self.assertIsNone(
            project_main_manager_event(_task(project="/private/example/client"), now=NOW)
        )


class MainManagerEndpointTests(unittest.TestCase):
    def _request(self, bridge_payload=None, bridge_error=None) -> dict:
        response = {}
        handler = SERVER.Handler.__new__(SERVER.Handler)
        handler.path = "/api/bridge/main-manager"
        handler.headers = {"Host": "command.meshly.fr"}
        handler._dashboard_run_authorized = lambda: False
        handler._json_response = lambda status, payload: response.update(
            status=status,
            payload=payload,
        )
        with patch.object(
            SERVER,
            "_bridge_request",
            side_effect=bridge_error,
            return_value=bridge_payload,
        ):
            handler.do_GET()
        return response

    def test_public_endpoint_returns_only_the_newest_safe_event(self):
        older = _task(updated_at="2099-08-08T05:30:00Z")
        newer = _task("running", project="Context News", updated_at="2099-08-08T05:50:00Z")
        with patch.object(SERVER, "_project_main_manager_event") as projector:
            projector.side_effect = [
                {"project": "AI STUDIO", "time": older["updated_at"], "status": "в очереди", "next_safe_step": "Ожидать начала работы."},
                {"project": "Context News", "time": newer["updated_at"], "status": "работает", "next_safe_step": "Дождаться подтверждённого результата."},
            ]
            response = self._request({"tasks": [older, newer]})

        self.assertEqual(response["status"], 200)
        self.assertEqual(response["payload"]["event"]["project"], "Context News")
        self.assertEqual(set(response["payload"]), {"event"})
        self.assertNotIn("PRIVATE", str(response["payload"]))

    def test_no_current_event_returns_idle_without_simulation(self):
        response = self._request({"tasks": []})
        self.assertEqual(response, {"status": 200, "payload": {"event": None}})

    def test_bridge_failure_is_generic_for_every_view(self):
        response = self._request(bridge_error=RuntimeError("PRIVATE INTERNAL ERROR"))
        self.assertEqual(
            response,
            {
                "status": 502,
                "payload": {"error": "bridge_unavailable", "event": None},
            },
        )


class MainManagerTheaterContractTests(unittest.TestCase):
    def test_scene_has_manager_home_project_station_and_safe_detail_hooks(self):
        html = build_agent_theater_html()
        for hook in (
            'id="theater-main-manager-home"',
            'id="theater-project-station"',
            'id="theater-main-manager"',
            'id="theater-manager-detail"',
            'id="theater-manager-project"',
            'id="theater-manager-time"',
            'id="theater-manager-status"',
            'id="theater-manager-next"',
        ):
            self.assertIn(hook, html)

    def test_client_uses_dedicated_safe_endpoint_and_has_no_demo_event(self):
        script = (ASSETS_DIR / "script.js").read_text(encoding="utf-8")
        self.assertIn("/api/bridge/main-manager", script)
        self.assertIn("renderMainManager", script)
        self.assertNotIn("demoMainManager", script)
        self.assertNotIn("mockMainManager", script)

    def test_motion_has_reduced_motion_fallback(self):
        css = (ASSETS_DIR / "style.css").read_text(encoding="utf-8")
        self.assertIn(".theater-main-manager", css)
        self.assertIn("prefers-reduced-motion: reduce", css)
        self.assertIn("transition: none", css)


if __name__ == "__main__":
    unittest.main()
