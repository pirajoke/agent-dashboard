from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from urllib.parse import urlsplit
from unittest.mock import patch


BUILDER_DIR = Path(__file__).resolve().parents[1]
SERVER_PATH = BUILDER_DIR / "dashboard-server-m4.py"
SERVER_SPEC = importlib.util.spec_from_file_location("dashboard_server_m4", SERVER_PATH)
SERVER = importlib.util.module_from_spec(SERVER_SPEC)
assert SERVER_SPEC and SERVER_SPEC.loader
SERVER_SPEC.loader.exec_module(SERVER)


def _issue(number: int, stage: str, *, title: str = "Личная задача") -> dict:
    return {
        "number": number,
        "title": title,
        "html_url": f"https://github.com/pirajoke/jarvis/issues/{number}",
        "updated_at": "2099-07-19T08:54:21Z",
        "closed_at": "2099-07-19T08:54:21Z" if stage == "jarvis:done" else None,
        "labels": [{"name": "ai-task"}, {"name": stage}],
    }


def _bridge_task(number: int, status: str) -> dict:
    return {
        "id": f"task-{number}",
        "status": status,
        "agent_role": "BUILDER",
        "project": "private-project",
        "description": "Секретное описание личной задачи",
        "result": "Секретный результат",
        "error": "Секретная ошибка",
        "created_at": "2099-07-19T08:52:31Z",
        "updated_at": "2099-07-19T08:54:21Z",
        "metadata": {
            "github_repo": "pirajoke/jarvis",
            "github_issue_number": number,
            "objective": "Секретная цель",
        },
        "messages": [{"body": "Секретное сообщение агента"}],
    }


class JarvisPipelineHistoryTests(unittest.TestCase):
    def _history_response(self, *, owner: bool) -> dict:
        response = {}
        handler = SERVER.Handler.__new__(SERVER.Handler)
        handler._dashboard_run_authorized = lambda: owner
        handler._json_response = lambda status, payload: response.update(
            status=status,
            payload=payload,
        )
        issues = [
            _issue(37, "jarvis:done", title="Создать приватный документ"),
            _issue(34, "jarvis:failed", title="Неудачная приватная задача"),
        ]
        bridge = {"tasks": [_bridge_task(37, "done"), _bridge_task(34, "done")]}
        with (
            patch.object(SERVER, "_github_task_issues", return_value=issues),
            patch.object(SERVER, "_bridge_request", return_value=bridge),
        ):
            handler._handle_jarvis_pipeline_history(
                urlsplit("/api/jarvis/pipeline/history?limit=12")
            )
        return response

    def test_public_history_is_github_backed_and_hides_issue_title(self):
        response = self._history_response(owner=False)

        self.assertEqual(response["status"], 200)
        payload = response["payload"]
        self.assertEqual(payload["source"], "github")
        self.assertEqual(payload["privacy"], "anonymous_summary")
        self.assertEqual(payload["count"], 1)
        self.assertEqual(
            payload["items"][0],
            {
                "status": "done",
                "task": "GitHub #37",
                "result_summary": "Выполнено и подтверждено в GitHub.",
                "updated_at": "2099-07-19T08:54:21Z",
                "url": "https://github.com/pirajoke/jarvis/issues/37",
                "source": "github",
                "freshness": "fresh",
                "age_seconds": 0,
            },
        )
        self.assertNotIn("Создать приватный документ", str(payload))
        self.assertNotIn("Секрет", str(payload))

    def test_history_reports_github_bridge_mismatch(self):
        payload = self._history_response(owner=False)["payload"]

        reconciliation = payload["reconciliation"]
        self.assertEqual(reconciliation["status"], "degraded")
        self.assertEqual(reconciliation["checked_count"], 2)
        self.assertEqual(reconciliation["mismatch_count"], 1)
        self.assertEqual(
            reconciliation["mismatches"][0],
            {
                "issue_number": 34,
                "github_url": "https://github.com/pirajoke/jarvis/issues/34",
                "github_status": "failed",
                "bridge_status": "done",
                "reason": "status_mismatch",
            },
        )

    def test_owner_history_can_show_issue_title(self):
        payload = self._history_response(owner=True)["payload"]

        self.assertEqual(payload["privacy"], "owner")
        self.assertEqual(payload["items"][0]["task"], "Создать приватный документ")


class BridgeTaskPrivacyTests(unittest.TestCase):
    def _get_tasks(self, *, owner: bool) -> tuple[dict, list[str]]:
        response = {}
        requested_paths: list[str] = []
        handler = SERVER.Handler.__new__(SERVER.Handler)
        handler.path = "/api/bridge/tasks?limit=12&include_messages=1"
        handler.headers = {"Host": "command.meshly.fr"}
        handler._dashboard_run_authorized = lambda: owner
        handler._json_response = lambda status, payload: response.update(
            status=status,
            payload=payload,
        )

        def bridge_request(_method, path, _payload=None):
            requested_paths.append(path)
            return {"tasks": [_bridge_task(37, "done")]}

        with patch.object(SERVER, "_bridge_request", side_effect=bridge_request):
            handler.do_GET()
        return response, requested_paths

    def test_anonymous_tasks_exclude_all_task_content(self):
        response, paths = self._get_tasks(owner=False)

        self.assertEqual(response["status"], 200)
        self.assertEqual(paths, ["/api/tasks?limit=12&include_messages=0"])
        payload = response["payload"]
        self.assertEqual(payload["privacy"], "anonymous_summary")
        item = payload["tasks"][0]
        self.assertEqual(item["detail_access"], "owner_required")
        for field in ("id", "project", "description", "result", "error", "metadata", "messages"):
            self.assertNotIn(field, item)
        self.assertNotIn("Секрет", str(payload))

    def test_owner_token_returns_full_task_detail(self):
        response, paths = self._get_tasks(owner=True)

        self.assertEqual(response["status"], 200)
        self.assertEqual(paths, ["/api/tasks?limit=12&include_messages=1"])
        item = response["payload"]["tasks"][0]
        self.assertEqual(item["description"], "Секретное описание личной задачи")
        self.assertEqual(item["messages"][0]["body"], "Секретное сообщение агента")

    def test_public_bridge_status_allows_only_known_integer_counts(self):
        payload = SERVER._public_bridge_payload(
            {
                "status": "ok",
                "tasks": {
                    "pending": 2,
                    "running": 1,
                    "done": 7,
                    "failed": 0,
                    "cancelled": 1,
                    "description": "Секретное описание",
                    "private_counter": 99,
                    "queued": "3",
                },
                "message": "Секретное сообщение",
            }
        )

        self.assertEqual(
            payload,
            {
                "status": "ok",
                "tasks": {
                    "pending": 2,
                    "running": 1,
                    "done": 7,
                    "failed": 0,
                    "cancelled": 1,
                },
                "privacy": "anonymous_summary",
            },
        )
        self.assertNotIn("Секрет", str(payload))

    def test_public_bridge_payload_drops_malformed_task_entries(self):
        payload = SERVER._public_bridge_payload(
            {"tasks": [_bridge_task(37, "done"), "Секретный текст"]}
        )

        self.assertEqual(len(payload["tasks"]), 1)
        self.assertNotIn("Секрет", str(payload))


class DashboardOwnerAuthTests(unittest.TestCase):
    def _authorized(self, provided: str | None) -> bool:
        handler = SERVER.Handler.__new__(SERVER.Handler)
        handler.headers = {"Host": "command.meshly.fr"}
        if provided is not None:
            handler.headers["X-Dashboard-Run-Token"] = provided
        with patch.object(SERVER, "_dashboard_run_token", return_value="owner-token"):
            return handler._dashboard_run_authorized()

    def test_public_detail_fails_closed_without_owner_token(self):
        self.assertFalse(self._authorized(None))
        self.assertFalse(self._authorized("wrong-token"))

    def test_public_detail_accepts_owner_token(self):
        self.assertTrue(self._authorized("owner-token"))


if __name__ == "__main__":
    unittest.main()
