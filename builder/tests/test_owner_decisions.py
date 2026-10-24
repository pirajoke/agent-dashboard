from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from dashboard_builder.department_campus import DEPARTMENT_ZONES
from dashboard_builder.owner_decisions import DecisionConflict, DecisionJournal, reviewed_response

BUILDER = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 3, 12, tzinfo=timezone.utc)
spec = importlib.util.spec_from_file_location("dashboard_owner_decisions_test", BUILDER / "dashboard-server-m4.py")
SERVER = importlib.util.module_from_spec(spec)
spec.loader.exec_module(SERVER)


def event(**changes):
    zone = DEPARTMENT_ZONES["development"]
    result = {
        "event_id": "evt-1", "task_id": "task-1", "department_id": "development",
        "department_label": zone["label"], "project": "ACCOUNTABLE OS",
        "agent_id": "BUILDER", "role": zone["roles"][0], "status": "waiting",
        "updated_at": (NOW - timedelta(minutes=1)).isoformat(), "next_step": "Подготовить выбранный вариант",
        "evidence_count": 1, "ephemeral": True, "zone_id": zone["zone_id"],
        "work_summary": "Сравнение направлений", "decision": {
            "question": "Какой вариант берём?", "reason": "Есть два проверенных направления",
            "options": [
                {"id": "a", "label": "Первый", "pros": "Быстрее", "cons": "Меньше функций", "summary": "Подготовить первый вариант", "recommended": True},
                {"id": "b", "label": "Второй", "pros": "Полнее", "cons": "Дольше", "summary": "Подготовить второй вариант"},
            ],
        },
    }
    result.update(changes)
    return result


def snapshot(events, **changes):
    task = {"id": "snapshot", "updated_at": NOW.isoformat(),
            "metadata": {"event": "status", "source_agent": "MAIN MANAGER", "pixel_events": events}}
    task.update(changes)
    return {"tasks": [task]}


def project(events, *, owner=True, records=None):
    return SERVER._manager_decisions_payload(snapshot(events), owner=owner, records=records or [], now=NOW)


def response(decision, **changes):
    result = {"task_id": decision["task_id"], "revision": decision["revision"], "option_id": "a", "note": "", "reviewed": True}
    result.update(changes)
    return result


class DecisionProjectionTests(unittest.TestCase):
    def test_real_proposal_and_owner_only_details(self):
        owner = project([event()])
        self.assertEqual(len(owner["decisions"]), 1)
        self.assertEqual(owner["decisions"][0]["options"][0]["summary"], "Подготовить первый вариант")
        public = project([event()], owner=False)
        self.assertEqual(public["state"], "owner_required")
        self.assertEqual(public["decisions"], [])
        for private in ("Какой вариант", "проверенных направления", "Сравнение направлений", "options"):
            self.assertNotIn(private, json.dumps(public, ensure_ascii=False))

    def test_fourth_blocker_is_not_lost_to_three_campus_lanes(self):
        events = [event(task_id=f"task-{i}", event_id=f"evt-{i}") for i in range(4)]
        payload = project(events)
        self.assertEqual(len(payload["activity"]), 3)
        self.assertEqual(len(payload["decisions"]), 4)

    def test_newer_active_event_supersedes_old_waiting_event(self):
        payload = project([event(), event(event_id="evt-active", status="active", updated_at=NOW.isoformat())])
        self.assertEqual(payload["decisions"], [])

    def test_stale_future_invalid_and_nonwaiting_events_have_no_choices(self):
        for changes in ({"status": "active"}, {"ephemeral": False}, {"updated_at": (NOW - timedelta(minutes=31)).isoformat()},
                        {"updated_at": (NOW + timedelta(seconds=1)).isoformat()}, {"task_id": "/private/task"}):
            with self.subTest(changes=changes):
                self.assertEqual(project([event(**changes)])["decisions"], [])
        stale = snapshot([event()], updated_at=(NOW - timedelta(minutes=31)).isoformat())
        self.assertEqual(SERVER._manager_decisions_payload(stale, owner=True, records=[], now=NOW)["decisions"], [])

    def test_unverified_snapshot_cannot_supply_options(self):
        data = snapshot([event()], metadata={"event": "status", "source_agent": "BUILDER", "pixel_events": [event()]})
        self.assertEqual(SERVER._manager_decisions_payload(data, owner=True, records=[], now=NOW)["decisions"], [])

    def test_missing_or_unsafe_proposals_allow_own_note_without_fabricated_options(self):
        for proposal in (None, {"options": []}, {"question": "token=private-value", "options": [{"id": "a", "label": "One"}]}):
            decision = project([event(decision=proposal)])["decisions"][0]
            self.assertEqual(decision["options"], [])
            self.assertNotIn("private-value", repr(decision))
            own = reviewed_response(response(decision, option_id=None, note="Предлагаю третий вариант"), [decision], now=NOW)
            self.assertEqual(own["note"], "Предлагаю третий вариант")

    def test_recorded_revision_disappears_but_new_proposal_reappears(self):
        original = project([event()])["decisions"][0]
        record = reviewed_response(response(original), [original], now=NOW)
        self.assertEqual(project([event()], records=[record])["decisions"], [])
        changed = event()
        changed["decision"]["options"][0]["cons"] = "Новая существенная цена"
        current = project([changed], records=[record])["decisions"][0]
        self.assertNotEqual(original["revision"], current["revision"])
        with self.assertRaises(DecisionConflict):
            reviewed_response(response(original), [current], now=NOW)

    def test_review_invalid_option_empty_answer_and_unsafe_note_are_rejected(self):
        decision = project([event()])["decisions"][0]
        for changes in ({"reviewed": False}, {"execute": True}, {"option_id": "unknown"},
                        {"option_id": None}, {"note": "x" * 501}, {"note": "token=private-value"},
                        {"note": "/Users/private/context"}, {"note": ["text"]}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                reviewed_response(response(decision, **changes), [decision], now=NOW)

    def test_malformed_bridge_data_is_honest_and_empty(self):
        for data in (None, [], {"tasks": None}, {"tasks": {}}, {"tasks": [None, "bad"]}):
            self.assertEqual(SERVER._manager_decisions_payload(data, owner=True, records=[], now=NOW)["decisions"], [])


class DecisionJournalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "responses.jsonl"
        self.journal = DecisionJournal(self.path)
        decision = project([event()])["decisions"][0]
        self.record = reviewed_response(response(decision), [decision], now=NOW)

    def test_retries_and_concurrent_confirmations_write_one_owner_only_record(self):
        self.assertEqual(self.journal.read(), [])
        self.assertFalse(self.path.exists())
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: self.journal.record(dict(self.record)), range(12)))
        self.assertTrue(all(item == self.record for item in results))
        self.assertEqual(self.journal.read(), [self.record])
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(len(self.path.read_text().splitlines()), 1)
        with self.assertRaises(DecisionConflict):
            self.journal.record({**self.record, "option_id": "b"})
        self.assertEqual(self.journal.read(), [self.record])

    def test_symlink_insecure_permissions_and_corruption_fail_closed(self):
        target = Path(self.temp.name) / "target"
        target.write_text("unchanged")
        self.path.symlink_to(target)
        with self.assertRaises(OSError):
            self.journal.record(self.record)
        self.assertEqual(target.read_text(), "unchanged")
        self.path.unlink()
        self.path.write_text("not json")
        self.path.chmod(0o644)
        with self.assertRaises(OSError):
            self.journal.read()
        self.path.chmod(0o600)
        with self.assertRaises(OSError):
            self.journal.record(self.record)
        self.assertEqual(self.path.read_text(), "not json")


class DecisionEndpointTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "responses.jsonl"
        self.data = snapshot([event()])
        self.decision = project([event()])["decisions"][0]

    def call(self, method="GET", path="/api/manager/decisions", body=None, *, token="fixture-owner", origin=None, length=None):
        handler = SERVER.Handler.__new__(SERVER.Handler)
        handler.path, handler.command = path, method
        raw = json.dumps(body or {}).encode()
        handler.headers = {"Host": "localhost:9999", "Content-Length": str(len(raw) if length is None else length)}
        if token is not None:
            handler.headers["X-Dashboard-Run-Token"] = token
        if origin is not None:
            handler.headers["Origin"] = origin
        handler.rfile = io.BytesIO(raw)
        output = {}
        handler._json_response = lambda status, payload: output.update(status=status, payload=payload)
        original = SERVER._manager_decisions_payload
        with (patch.object(SERVER, "MANAGER_DECISIONS_FILE", self.path),
              patch.object(SERVER, "_dashboard_run_token", return_value="fixture-owner"),
              patch.object(SERVER, "_bridge_request", return_value=self.data) as bridge,
              patch.object(SERVER, "_manager_decisions_payload", side_effect=lambda data, **kw: original(data, now=NOW, **kw)),
              patch.object(SERVER.subprocess, "Popen") as popen):
            getattr(handler, f"do_{method}")()
            popen.assert_not_called()
        return output, bridge.call_args_list

    def test_anonymous_get_has_no_private_proposals_and_responses_need_token(self):
        output, _ = self.call(token=None)
        self.assertEqual(output["status"], 200)
        self.assertEqual(output["payload"]["state"], "owner_required")
        self.assertNotIn("Какой вариант", repr(output))
        self.assertEqual(self.call(path="/api/manager/decisions/responses", token=None)[0]["status"], 401)
        self.assertFalse(self.path.exists())

    def test_host_alone_wrong_token_or_cross_origin_cannot_record(self):
        for changes, status in (({"token": None}, 401), ({"token": "wrong"}, 401), ({"token": "é"}, 401), ({"origin": "https://foreign.invalid"}, 403)):
            result, calls = self.call("POST", "/api/manager/decisions/respond", response(self.decision), **changes)
            self.assertEqual(result["status"], status)
            self.assertEqual(calls, [])
            self.assertFalse(self.path.exists())

    def test_confirmation_records_only_gets_tasks_and_is_idempotent(self):
        body = response(self.decision, note="Выбираю первый")
        first, calls = self.call("POST", "/api/manager/decisions/respond", body, origin="http://localhost:9999")
        self.assertEqual(first["status"], 200)
        self.assertEqual([(c.args[0], c.args[1]) for c in calls], [("GET", "/api/tasks?limit=24&include_messages=1")])
        second, _ = self.call("POST", "/api/manager/decisions/respond", body)
        self.assertEqual(second, first)
        self.assertTrue(first["payload"]["record_only"])
        self.assertEqual(self.call()[0]["payload"]["decisions"], [])
        recorded, calls = self.call(path="/api/manager/decisions/responses")
        self.assertEqual(len(recorded["payload"]["responses"]), 1)
        self.assertEqual(calls, [])

    def test_changed_proposal_and_invalid_body_do_not_write(self):
        for changes, status in (({"revision": "stale"}, 409), ({"reviewed": False}, 400), ({"option_id": "no"}, 400)):
            result, _ = self.call("POST", "/api/manager/decisions/respond", response(self.decision, **changes))
            self.assertEqual(result["status"], status)
            self.assertFalse(self.path.exists())
        for length in (-1, 0, 4097, "bad"):
            result, calls = self.call("POST", "/api/manager/decisions/respond", response(self.decision), length=length)
            self.assertEqual(result["status"], 400)
            self.assertEqual(calls, [])
        self.data = snapshot([event(status="done")])
        self.assertEqual(self.call("POST", "/api/manager/decisions/respond", response(self.decision))[0]["status"], 409)

    def test_corrupted_journal_returns_generic_unavailable(self):
        self.path.write_text("private corrupt contents")
        os.chmod(self.path, 0o600)
        result, _ = self.call()
        self.assertEqual(result["status"], 503)
        self.assertNotIn("private corrupt contents", repr(result))

    def test_static_get_head_and_aliases_cannot_bypass_owner_auth(self):
        root = Path(self.temp.name)
        state = root / '.agent-bridge'
        state.mkdir()
        (state / 'dashboard_run_token').write_text('fixture-only-token')
        (root / 'bridge-alias').symlink_to(state, target_is_directory=True)
        for method in ('GET', 'HEAD'):
            for path in ('/.agent-bridge/', '/.agent-bridge/dashboard_run_token',
                         '/alias/../.agent-bridge/command-center-decisions.jsonl',
                         '/bridge-alias/dashboard_run_token'):
                with self.subTest(method=method, path=path):
                    handler = SERVER.Handler.__new__(SERVER.Handler)
                    handler.path, handler.command = path, method
                    handler.headers = {'Host': 'localhost:9999'}
                    output = {}
                    handler.send_error = lambda status, message: output.update(status=status)
                    handler._json_response = lambda status, payload: output.update(status=status)
                    with patch.object(SERVER, 'HOME', root):
                        getattr(handler, f'do_{method}')()
                    self.assertEqual(output['status'], 403)


if __name__ == "__main__":
    unittest.main()
