from __future__ import annotations

import importlib.util
import plistlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dashboard_builder.service_status import (
    normalize_payload,
    normalize_services,
    parse_launchctl_disabled,
    parse_launchctl_list,
    plist_schedule,
)

BUILDER_DIR = Path(__file__).resolve().parents[1]
SERVER_SPEC = importlib.util.spec_from_file_location("dashboard_server_m4_services", BUILDER_DIR / "dashboard-server-m4.py")
SERVER = importlib.util.module_from_spec(SERVER_SPEC)
assert SERVER_SPEC and SERVER_SPEC.loader
SERVER_SPEC.loader.exec_module(SERVER)


def svc(label: str, status: str = "stopped", **extra) -> dict:
    return {"name": label.rsplit(".", 1)[-1], "label": label, "status": status, "plist": f"/LA/{label}.plist", **extra}


SCHEDULES = {
    "/LA/com.pirajoke.live-feed.plist": {"interval": 300},
    "/LA/com.pirajoke.docker-guardian.plist": {"interval": None},
}


def normalize(services, *, loaded, disabled=frozenset(), installed=None):
    installed = set(installed if installed is not None else (s["plist"] for s in services))
    return normalize_services(
        services,
        loaded=loaded,
        disabled=set(disabled),
        schedule_for=lambda path: SCHEDULES.get(str(path)),
        plist_exists=lambda path: str(path) in installed,
    )


class NormalizeServicesTests(unittest.TestCase):
    def test_running_and_really_stopped_services_stay(self):
        services = [svc("com.pirajoke.jarvis-bot", "running", pid=774), svc("com.pirajoke.tag-website")]
        self.assertEqual(normalize(services, loaded={"com.pirajoke.jarvis-bot": 0}), services)

    def test_switched_off_and_uninstalled_jobs_are_not_down(self):
        services = [svc("com.pirajoke.obsidian-tg-bot"), svc("com.pirajoke.krisp-auto-import")]
        result = normalize(
            services,
            loaded={},
            disabled={"com.pirajoke.obsidian-tg-bot"},
            installed=set(),
        )
        self.assertEqual(result, [])

    def test_scheduled_job_between_runs_is_not_down(self):
        result = normalize([svc("com.pirajoke.live-feed")], loaded={"com.pirajoke.live-feed": 0})
        self.assertEqual(result[0]["cat"], "scheduled")
        self.assertEqual(result[0]["interval"], 300)

    def test_scheduled_job_that_never_ran_yet_is_not_down(self):
        result = normalize([svc("com.pirajoke.docker-guardian")], loaded={"com.pirajoke.docker-guardian": None})
        self.assertEqual(result[0]["cat"], "scheduled")

    def test_scheduled_job_missing_from_launchd_stays_in_view(self):
        # After the 2026-10-12 reboot these jobs were not loaded at all.
        result = normalize([svc("com.pirajoke.live-feed", desc="Live feed", cat="scheduled")], loaded={"other": 0})
        self.assertEqual(result[0]["cat"], "core")
        self.assertEqual(result[0]["desc"], "Live feed · не загружена в launchd")

    def test_scheduled_job_whose_last_run_failed_stays_in_view(self):
        result = normalize([svc("com.pirajoke.live-feed")], loaded={"com.pirajoke.live-feed": 78})
        self.assertEqual(result[0]["cat"], "core")
        self.assertEqual(result[0]["exit_code"], 78)
        self.assertIn("код 78", result[0]["desc"])

    def test_items_without_a_label_are_left_alone(self):
        services = [{"name": "next dev", "status": "stopped"}, "raw"]
        self.assertEqual(normalize_services(services, loaded={"x": 0}, disabled=set()), services)

    def test_payload_lists_are_normalized_and_input_is_not_mutated(self):
        original = svc("com.pirajoke.live-feed")
        data = {"system": {"hostname": "maxxs-mac-mini"}, "services_detailed": [original], "services": [original]}
        result = normalize_payload(
            data,
            loaded={"com.pirajoke.live-feed": 0},
            disabled=set(),
            schedule_for=lambda path: {"interval": 300},
            plist_exists=lambda path: True,
        )
        self.assertEqual(result["services_detailed"][0]["cat"], "scheduled")
        self.assertEqual(result["services"][0]["cat"], "scheduled")
        self.assertNotIn("cat", original)
        self.assertEqual(result["system"], data["system"])


class LaunchdParsingTests(unittest.TestCase):
    def test_launchctl_list(self):
        raw = "PID\tStatus\tLabel\n774\t0\tcom.pirajoke.jarvis-bot\n-\t78\tcom.pirajoke.live-feed\n-\t-\tcom.pirajoke.docker-guardian\n"
        self.assertEqual(
            parse_launchctl_list(raw),
            {"com.pirajoke.jarvis-bot": 0, "com.pirajoke.live-feed": 78, "com.pirajoke.docker-guardian": None},
        )

    def test_launchctl_print_disabled_old_and_new_formats(self):
        raw = (
            "disabled services = {\n"
            '\t"com.pirajoke.obsidian-tg-bot" => disabled\n'
            '\t"com.pirajoke.jarvis-bot" => enabled\n'
            '\t"com.pirajoke.old" => true\n'
            '\t"com.pirajoke.kept" => false\n'
            "}\n"
        )
        self.assertEqual(parse_launchctl_disabled(raw), {"com.pirajoke.obsidian-tg-bot", "com.pirajoke.old"})
        self.assertIsNone(parse_launchctl_disabled(""))

    def test_plist_schedule(self):
        cases = {
            "interval": ({"Label": "a", "StartInterval": 300}, {"interval": 300}),
            "calendar": ({"Label": "b", "StartCalendarInterval": {"Hour": 3}}, {"interval": None}),
            "keepalive": ({"Label": "c", "KeepAlive": True, "StartInterval": 60}, None),
            "daemon": ({"Label": "d", "RunAtLoad": True}, None),
        }
        with tempfile.TemporaryDirectory() as tmp:
            for name, (content, expected) in cases.items():
                with self.subTest(name=name):
                    path = Path(tmp) / f"{name}.plist"
                    path.write_bytes(plistlib.dumps(content))
                    self.assertEqual(plist_schedule(path), expected)
            broken = Path(tmp) / "broken.plist"
            broken.write_text("not a plist")
            self.assertIsNone(plist_schedule(broken))
            self.assertIsNone(plist_schedule(Path(tmp) / "missing.plist"))


class ServerServiceListTests(unittest.TestCase):
    def _get(self, path: str, *, public: bool, health: dict, launchd: tuple) -> dict:
        response = {}
        handler = SERVER.Handler.__new__(SERVER.Handler)
        handler.path = path
        handler._is_public_request = lambda: public
        handler._json_response = lambda status, payload: response.update(status=status, payload=payload)
        with patch.object(SERVER, "_health_request", return_value=health), patch.object(
            SERVER, "_launchd_state", return_value=launchd
        ):
            handler.do_GET()
        return response

    def test_detailed_services_hide_switched_off_jobs_before_public_stripping(self):
        health = {"services": [svc("com.pirajoke.obsidian-tg-bot", log="/Users/x/log"), svc("com.pirajoke.jarvis-bot", "running")]}
        loaded = ({"com.pirajoke.jarvis-bot": 0}, {"com.pirajoke.obsidian-tg-bot"})
        response = self._get("/api/services/detailed", public=True, health=health, launchd=loaded)
        self.assertEqual(response["status"], 200)
        services = response["payload"]["services"]
        self.assertEqual([s["label"] for s in services], ["com.pirajoke.jarvis-bot"])
        self.assertNotIn("plist", services[0])

    def test_list_is_unchanged_when_launchctl_does_not_answer(self):
        health = {"services_detailed": [svc("com.pirajoke.obsidian-tg-bot")]}
        for launchd in (({}, set()), ({"com.pirajoke.jarvis-bot": 0}, None)):
            with self.subTest(launchd=launchd):
                response = self._get("/api/all", public=False, health=health, launchd=launchd)
                self.assertEqual(response["payload"]["services_detailed"], health["services_detailed"])


class LaunchdStateTests(unittest.TestCase):
    def setUp(self):
        SERVER._LAUNCHD_STATE.update(read_at=0.0, loaded={}, disabled=None)
        self.addCleanup(SERVER._LAUNCHD_STATE.update, read_at=0.0, loaded={}, disabled=None)

    def _read(self, list_out: str, disabled_out: str):
        def run_text(cmd, timeout=5):
            return list_out if cmd[1] == "list" else disabled_out

        SERVER._LAUNCHD_STATE["read_at"] = 0.0
        with patch.object(SERVER, "_run_text", side_effect=run_text):
            return SERVER._launchd_state()

    def test_failed_print_disabled_keeps_the_last_answer(self):
        listing = "PID\tStatus\tLabel\n774\t0\tcom.pirajoke.jarvis-bot\n"
        good = 'disabled services = {\n\t"com.pirajoke.obsidian-tg-bot" => disabled\n}\n'
        self.assertEqual(self._read(listing, ""), ({"com.pirajoke.jarvis-bot": 0}, None))
        self.assertEqual(self._read(listing, good)[1], {"com.pirajoke.obsidian-tg-bot"})
        self.assertEqual(self._read(listing, "")[1], {"com.pirajoke.obsidian-tg-bot"})


if __name__ == "__main__":
    unittest.main()


class UnlistedRunningServicesTests(unittest.TestCase):
    """Mark 2026-10-20: running services such as MAIN MANAGER and n8n were missing from Техника."""

    def test_running_jobs_missing_from_the_registry_are_added(self):
        from dashboard_builder.service_status import parse_launchctl_running, unlisted_running_services
        raw = ("PID\tStatus\tLabel\n774\t0\tcom.pirajoke.jarvis-bot\n812\t0\tcom.pirajoke.health-lab\n"
               "901\t0\thomebrew.mxcl.n8n\n-\t0\tcom.pirajoke.live-feed\n455\t0\tcom.google.keystone.agent\n"
               "300\t0\tcom.pirajoke.obsidian-tg-bot\n320\t0\tapplication.com.example.123\n333\t0\tcom.pirajoke.no-plist\n")
        running = parse_launchctl_running(raw)
        self.assertEqual(running, {"com.pirajoke.jarvis-bot", "com.pirajoke.health-lab", "homebrew.mxcl.n8n",
                                   "com.google.keystone.agent", "com.pirajoke.obsidian-tg-bot",
                                   "application.com.example.123", "com.pirajoke.no-plist"})
        extra = unlisted_running_services(
            [svc("com.pirajoke.jarvis-bot", "running")], running=running, disabled={"com.pirajoke.obsidian-tg-bot"},
            agents_dir=Path("/LA"), plist_exists=lambda path: "no-plist" not in str(path))
        self.assertEqual([(item["name"], item["label"]) for item in extra],
                         [("Health Lab", "com.pirajoke.health-lab"), ("N8n", "homebrew.mxcl.n8n")])
        self.assertTrue(all(item["status"] == "running" and item["cat"] == "core" for item in extra))

    def test_payload_adds_them_once_to_each_list(self):
        original = svc("com.pirajoke.jarvis-bot", "running")
        data = {"services_detailed": [original], "services": [original]}
        result = normalize_payload(data, loaded={"com.pirajoke.jarvis-bot": 0, "com.pirajoke.health-lab": 0},
                                   disabled=set(), running={"com.pirajoke.jarvis-bot", "com.pirajoke.health-lab"},
                                   plist_exists=lambda path: True)
        for key in ("services", "services_detailed"):
            self.assertEqual([item["label"] for item in result[key]], ["com.pirajoke.jarvis-bot", "com.pirajoke.health-lab"])
        without = normalize_payload(data, loaded={"com.pirajoke.jarvis-bot": 0}, disabled=set(), plist_exists=lambda path: True)
        self.assertEqual(len(without["services"]), 1)
