"""«Архитектура»: the projection shows wiring and confirmed states only, and leaks nothing private."""
from __future__ import annotations

import json
import os
import plistlib
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from dashboard_builder import architecture as arch

NOW = datetime(2026, 10, 26, 21, 30, tzinfo=timezone.utc)
THREAD = "019ff42b-354b-7951-8cac-7c2f4a22f381"
PRIVATE_PATH = "/Users/someone/Documents/Projects/SECRET"


def routes():
    def route(project, department, role, enabled=True):
        return {"hostId": "remote-ssh-discovered:maxxs-mac-mini", "threadId": THREAD, "project": project,
                "repository": "pirajoke/x", "departmentId": department, "agentRole": role, "enabled": enabled}
    return {"schema": "main_manager_agent_routes_v1", "routes": {
        "jarvis": route("JARVIS", "infrastructure", "BUILDER"),
        "main-manager": route("MAIN MANAGER", "hq", "COORDINATOR"),
        "my-dictionary": route("MY DICTIONARY", "development", "BUILDER"),
        "health-os": route("HEALTH OS", "internal", "ANALYST", enabled=False),
    }}


def campus():
    return {
        "agents": [
            {"route_id": "main-manager", "state": "running", "freshness": "fresh", "state_at": "2026-10-26T21:29:00Z"},
            {"route_id": "my-dictionary", "state": "running", "freshness": "stale", "state_at": "2026-10-20T10:00:00Z"},
        ],
        "owner_gates": [{"project": "JARVIS", "updated_at": "2026-10-25T20:45:59Z", "next_step": "Ждёт решения"}],
    }


def queue():
    return {"version": 1, "items": [
        {"project": "JARVIS", "status": "queued", "owner_gate": "publication", "completed_at": "2026-10-26T09:15:39Z",
         "next_step": "PRIVATE TASK TEXT", "source_task_id": "secret-task"},
        {"project": "JARVIS", "status": "acked", "owner_gate": "merge", "completed_at": "2026-08-18T11:47:31Z",
         "ack": {"acked_at": "2026-10-25T20:45:59Z"}},
    ]}


LAUNCHCTL = "\n".join([
    "PID\tStatus\tLabel",
    "101\t0\tcom.pirajoke.bridge-api",
    "102\t0\tcom.pirajoke.bridge-worker",
    "103\t0\tcom.pirajoke.bridge-worker-2",
    "-\t0\tcom.pirajoke.main-manager-dispatcher",
    "-\t1\tcom.pirajoke.main-manager-portfolio-continuation",
    "104\t-15\tcom.pirajoke.jarvis-bot",
])


def project(**overrides):
    values = dict(routes=routes(), department_defs={"departments": {d: {} for d in arch.DEPARTMENT_ORDER}},
                  campus=campus(), queue=queue(), scheduler_state={"cursor": {"completed_at": "2026-10-26T09:15:39Z"}},
                  onboarding={"new_agents_registered": 0, "recovery_pending": False},
                  jobs=arch.parse_launchctl(LAUNCHCTL), log_times={}, bridge_tasks={"tasks": [
                      {"status": "done", "updated_at": "2026-10-26T21:27:50Z", "title": "PRIVATE TITLE"}]}, now=NOW)
    values.update(overrides)
    return arch.architecture_projection(**values)


class AgentStateTests(unittest.TestCase):
    def test_only_fresh_events_or_queue_gates_set_a_state(self):
        agents = {a["id"]: a for a in project()["agents"]}
        self.assertEqual(agents["main-manager"]["state"], "working")
        self.assertEqual(agents["jarvis"]["state"], "needs_mark")
        self.assertEqual(agents["jarvis"]["next_step"], "Нужно твоё решение: решение о публикации")
        # A stale «running» is not shown as work.
        self.assertEqual(agents["my-dictionary"]["state"], "unknown")
        self.assertIsNone(agents["my-dictionary"]["state_at"])
        self.assertEqual(agents["health-os"]["state"], "stopped")
        self.assertEqual(agents["jarvis"]["host"], "Mac mini")

    def test_counts_and_blockers(self):
        data = project()
        self.assertEqual(data["agent_counts"], {"registered": 4, "working": 1, "needs_mark": 1, "idle": 0, "unknown": 1})
        self.assertIn("Ждёт твоего решения: JARVIS.", data["blockers"])
        self.assertTrue(any("нового агента целиком" in b for b in data["blockers"]))

    def test_no_activity_at_all_is_a_blocker(self):
        data = project(campus=None)
        self.assertFalse(any(a["state"] == "working" for a in data["agents"]))
        self.assertEqual(data["agent_counts"]["needs_mark"], 0)

    def test_missing_registry_is_empty_not_invented(self):
        data = project(routes=None)
        self.assertEqual(data["agents"], [])
        self.assertEqual(data["agent_counts"]["registered"], 0)


class ServiceTests(unittest.TestCase):
    def test_process_failure_and_missing_jobs(self):
        services = {s["id"]: s for s in project()["services"]}
        self.assertEqual(services["bridge-api"]["state"], "running")
        self.assertEqual(services["bridge-workers"]["processes"], 2)
        self.assertEqual(services["dispatcher"]["state"], "scheduled")
        self.assertEqual(services["continuation"]["state"], "failed")
        self.assertEqual(services["notifier"]["state"], "stopped")
        # Killed by a signal but running again: the live process wins.
        self.assertEqual(services["jarvis-bot"]["state"], "running")

    def test_unreadable_launchd_is_unknown(self):
        services = project(jobs=None)["services"]
        self.assertTrue(all(s["state"] == "unknown" for s in services))

    def test_log_time_comes_from_the_plist_logs(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "out.log"
            log.write_text("x")
            os.utime(log, (NOW.timestamp(), NOW.timestamp()))
            with (Path(tmp) / "com.pirajoke.bridge-api.plist").open("wb") as handle:
                plistlib.dump({"Label": "com.pirajoke.bridge-api", "StandardOutPath": str(log)}, handle)
            times = arch.service_log_times(Path(tmp), ["com.pirajoke.bridge-api", "com.pirajoke.missing"])
        self.assertEqual(times, {"com.pirajoke.bridge-api": NOW})


class QueueAndOnboardingTests(unittest.TestCase):
    def test_queue_counts_open_gates_only(self):
        q = project()["queue"]
        self.assertEqual((q["open"], q["owner_gates"], q["executable"]), (1, 1, 0))
        self.assertEqual(q["gate_projects"], ["JARVIS"])
        self.assertEqual(q["last_collected_at"], "2026-10-26T09:15:39Z")

    def test_onboarding_receipts_and_digests(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = root / "onboarding"
            state.mkdir()
            (state / "a.receipt.json").write_text(json.dumps(
                {"registered_at": "2026-10-26T21:14:49Z", "identity": {"route_id": "pixelverse-dashboard", "cwd": PRIVATE_PATH}}))
            for name in ("helper", "canonical_helper", "routes"):
                (root / name).write_text("same")
            (root / "canonical_routes").write_text("different")
            summary = arch.onboarding_summary(state, installed_helper=root / "helper", canonical_helper=root / "canonical_helper",
                                              installed_routes=root / "routes", canonical_routes=root / "canonical_routes")
            self.assertEqual(summary["receipts"], 1)
            self.assertEqual(summary["last"], {"route": "Командный центр", "at": "2026-10-26T21:14:49Z", "new_agent": False})
            self.assertEqual(summary["new_agents_registered"], 0)
            self.assertTrue(summary["helper_matches_canonical"])
            self.assertFalse(summary["registry_matches_canonical"])
            self.assertFalse(summary["recovery_pending"])
            (state / "b.receipt.json").write_text(json.dumps(
                {"registered_at": "2026-10-27T08:00:00Z", "identity": {"route_id": "new-project"}}))
            (state / "pending.json").write_text("{}")
            summary = arch.onboarding_summary(state, installed_helper=root / "helper", canonical_helper=root / "x",
                                              installed_routes=root / "routes", canonical_routes=root / "routes")
            self.assertEqual(summary["new_agents_registered"], 1)
            self.assertTrue(summary["recovery_pending"])
            self.assertFalse(summary["helper_matches_canonical"])
            self.assertNotIn(PRIVATE_PATH, json.dumps(summary))


class PrivacyTests(unittest.TestCase):
    def test_no_paths_chat_ids_or_task_text(self):
        text = json.dumps(project(), ensure_ascii=False)
        for secret in (THREAD, "/Users/", "PRIVATE TASK TEXT", "PRIVATE TITLE", "secret-task", "pirajoke/x", "remote-ssh"):
            self.assertNotIn(secret, text)

    def test_links_only_name_known_nodes(self):
        known = {"owner", "main-manager", "registry", "queue", "onboarding", "chats", "results", "check", "log"}
        known |= {s["id"] for s in arch.SERVICES}
        for link in project()["links"]:
            self.assertIn(link["from"], known)
            self.assertIn(link["to"], known)


if __name__ == "__main__":
    unittest.main()
