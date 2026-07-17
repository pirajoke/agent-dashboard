from __future__ import annotations

import importlib.util
import tempfile
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


class JarvisPipelineHistoryTests(unittest.TestCase):
    def test_history_is_public_sanitized_and_done_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            report_dir = Path(tmp)
            (report_dir / "completed-run.md").write_text(
                """# Run
- Status: done
- Task: Проверить JARVIS
- Project: /Users/pirajoke/jarvis
- Provider mode: codex

## Result
- Summary: Проверка завершена успешно. token=supersecretvalue
""",
                encoding="utf-8",
            )
            (report_dir / "failed-run.md").write_text(
                """# Run
- Status: failed
- Task: Эта задача не должна попасть в историю

## Result
- Summary: Проверка не пройдена.
""",
                encoding="utf-8",
            )

            response = {}
            handler = SERVER.Handler.__new__(SERVER.Handler)
            handler._require_dashboard_run_auth = lambda: self.fail(
                "completed history must not require a launch token"
            )
            handler._json_response = lambda status, payload: response.update(
                status=status,
                payload=payload,
            )

            with patch.object(SERVER, "JARVIS_PIPELINE_REPORT_DIR", report_dir):
                handler._handle_jarvis_pipeline_history(
                    urlsplit("/api/jarvis/pipeline/history?limit=12")
                )

        self.assertEqual(response["status"], 200)
        self.assertEqual(response["payload"]["count"], 1)
        item = response["payload"]["items"][0]
        self.assertEqual(
            item,
            {
                "status": "done",
                "task": "Проверить JARVIS",
                "result_summary": "Проверка завершена успешно. [REDACTED_SECRET]",
                "updated_at": item["updated_at"],
            },
        )
        self.assertNotIn("supersecretvalue", str(response["payload"]))
        self.assertNotIn("run_id", item)
        self.assertNotIn("report_path", item)
        self.assertNotIn("project", item)
        self.assertNotIn("provider", item)


if __name__ == "__main__":
    unittest.main()
