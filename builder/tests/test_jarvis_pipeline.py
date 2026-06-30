from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dashboard_builder import jarvis_pipeline


class JarvisPipelineTests(unittest.TestCase):
    def test_latest_intake_contract_reads_capture_meta(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "jarvis.db"
            with sqlite3.connect(db) as con:
                con.execute(
                    """
                    create table captures (
                        id integer primary key,
                        created_at text not null,
                        text text not null,
                        routed_to text not null,
                        meta text not null
                    )
                    """
                )
                con.execute(
                    "insert into captures values (?, ?, ?, ?, ?)",
                    (
                        1,
                        "2026-06-30T10:00:00+00:00",
                        "на месяц",
                        "monthly_plan",
                        json.dumps(
                            {
                                "intent": "status_query",
                                "project": "Personal",
                                "title": "на месяц",
                                "confidence": 0.92,
                                "write_targets": ["answer", "answer_sources"],
                            },
                            ensure_ascii=False,
                        ),
                    ),
                )

            with patch.object(jarvis_pipeline, "JARVIS_DB", db):
                contract = jarvis_pipeline._latest_intake_contract()

        self.assertTrue(contract["ok"])
        self.assertEqual(contract["summary"], "status_query → monthly_plan")
        self.assertEqual(contract["detail"], "0.92 / answer, answer_sources")

    def test_todo_sync_status_counts_unlinked_linear_todos(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "jarvis.db"
            with sqlite3.connect(db) as con:
                con.execute(
                    """
                    create table todos (
                        id integer primary key,
                        created_at text not null,
                        updated_at text not null,
                        title text not null,
                        project text not null,
                        source text not null,
                        status text not null,
                        external_id text not null
                    )
                    """
                )
                con.executemany(
                    "insert into todos values (?, ?, ?, ?, ?, ?, ?, ?)",
                    [
                        (1, "2026-06-30", "2026-06-30", "Linked", "Personal", "telegram:personal_task", "open", "PER-1"),
                        (2, "2026-06-30", "2026-06-30", "Local only", "Personal", "telegram:personal_task", "open", ""),
                        (3, "2026-06-30", "2026-06-30", "Closed", "Personal", "telegram:personal_task", "done", ""),
                    ],
                )

            with patch.object(jarvis_pipeline, "JARVIS_DB", db):
                sync = jarvis_pipeline._todo_sync_status()

        self.assertFalse(sync["ok"])
        self.assertEqual(sync["open"], 2)
        self.assertEqual(sync["linked"], 1)
        self.assertEqual(sync["unsynced"], 1)
        self.assertEqual(sync["items"][0]["title"], "Local only")

    def test_goals_status_accepts_planning_month(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "goals.yaml").write_text("month: '2026-07'\n", encoding="utf-8")

            class _FixedDateTime:
                @staticmethod
                def now():
                    class _Now:
                        @staticmethod
                        def date():
                            from datetime import date

                            return date(2026, 6, 30)

                    return _Now()

            with patch.object(jarvis_pipeline, "JARVIS_REPO", repo), patch.object(
                jarvis_pipeline, "datetime", _FixedDateTime
            ):
                goals = jarvis_pipeline._goals_status()

        self.assertTrue(goals["ok"])
        self.assertEqual(goals["month"], "2026-07")


if __name__ == "__main__":
    unittest.main()
