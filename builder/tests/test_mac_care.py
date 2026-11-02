"""Техника → MacBook Pro shows how the laptop is looked after (Mark 2026-11-02)."""
import importlib.util
import json
import plistlib
import shutil
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dashboard_builder.mac_care import care_projection

ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "mac-mini-dashboard" / "index.html"
SERVER = ROOT / "dashboard-server-m4.py"
INSTALLER = ROOT / "install_daily_work_collector.sh"

spec = importlib.util.spec_from_file_location("mac_care_collector", ROOT / "mac_care_collector.py")
collector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collector)

NOW = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)


class CollectorTests(unittest.TestCase):
    def test_watchdog_counts_last_week_and_keeps_the_newest_line(self):
        local = NOW.astimezone()
        recent = (local - timedelta(hours=3)).strftime("%Y-%m-%d %H:%M:%S")
        older = (local - timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S")
        ancient = (local - timedelta(days=20)).strftime("%Y-%m-%d %H:%M:%S")
        log = f"{ancient} killed Old\n{older} warned Chrome 95%\n{recent} stopped Plaud /Users/mark/Downloads/Plaud 120%\n"
        status = collector.watchdog_status(log, {"com.pirajoke.cpu-watchdog": None}, NOW)
        self.assertEqual(status["job"], "loaded")
        self.assertEqual(status["events_7d"], 2)
        self.assertIn("Plaud", status["last_event"])
        self.assertNotIn("/Users/mark", status["last_event"])

    def test_unreadable_sources_stay_unknown(self):
        self.assertEqual(collector.watchdog_status(None, None, NOW)["events_7d"], None)
        self.assertEqual(collector.watchdog_status(None, None, NOW)["job"], None)
        self.assertEqual(collector.firewall_status(None), {"enabled": None})
        self.assertEqual(collector.updates_status(None)["pending"], None)
        self.assertIsNone(collector.swap_status(None))
        self.assertIsNone(collector.top_processes(None))
        self.assertIsNone(collector.disabled_agents(Path("/nonexistent/folder")))

    def test_firewall_restart_swap_and_processes(self):
        self.assertEqual(collector.firewall_status("Firewall is enabled. (State = 1)"), {"enabled": True})
        self.assertEqual(collector.firewall_status("Firewall is disabled. (State = 0)"), {"enabled": False})
        sched = "Repeating power events:\n  restart at 4:00AM Sunday\n"
        restart = collector.restart_status(sched, 1761955200)
        self.assertTrue(restart["scheduled"])
        self.assertIn("Sunday", restart["schedule"])
        self.assertFalse(collector.restart_status("No scheduled events.\n", None)["scheduled"])
        self.assertEqual(collector.boot_time("{ sec = 1761955200, usec = 0 } Sat Nov  1"), 1761955200.0)
        self.assertEqual(collector.swap_status("vm.swapusage: total = 2048.00M  used = 1536.00M  free = 512.00M"),
                         {"used_gb": 1.5, "total_gb": 2.0})
        top = collector.top_processes(" 98.5 /Applications/Plaud.app/Contents/MacOS/Plaud\n 12,0 /usr/sbin/WindowServer\n 1.0 a\n 0.5 b\n")
        self.assertEqual(top, [{"name": "Plaud", "cpu": 98}, {"name": "WindowServer", "cpu": 12}, {"name": "a", "cpu": 1}])

    def test_pending_updates_from_the_software_update_plist(self):
        data = plistlib.dumps({"RecommendedUpdates": [{"Display Name": "macOS Tahoe", "Display Version": "26.7.2"}],
                               "LastSuccessfulDate": datetime(2026, 11, 1, 9, 0)})
        status = collector.updates_status(data)
        self.assertEqual(status["pending"], ["macOS Tahoe 26.7.2"])
        self.assertEqual(status["checked_at"], "2026-11-01T09:00:00Z")

    def test_hygiene_report_headline_and_attention(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "latest.md"
            report.write_text("# Mac hygiene 2026-11-02\n\nВсё спокойно, 2 замечания.\n- ⚠️ Plaud dmg в Загрузках\n- ⚠️ firewall\n")
            status = collector.hygiene_status(report, {})
        self.assertEqual(status["headline"], "Всё спокойно, 2 замечания.")
        self.assertEqual(status["attention"], 2)
        self.assertEqual(status["job"], "missing")

    def test_main_writes_a_private_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(collector.main(["--out", tmp, "--machine", "macbook-pro"]), 0)
            path = Path(tmp) / "macbook-pro.json"
            data = json.loads(path.read_text())
            self.assertEqual(data["schema"], 1)
            self.assertEqual(data["machine"], "macbook-pro")
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)


class ProjectionTests(unittest.TestCase):
    def write(self, folder, name, generated_at):
        (folder / name).write_text(json.dumps({"schema": 1, "generated_at": generated_at,
                                               "firewall": {"enabled": True}, "top_processes": [{"name": "Chrome", "cpu": 40}]}))

    def test_public_visitors_get_no_facts(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.write(Path(tmp), "macbook-pro.json", "2026-11-02T11:50:00Z")
            payload = care_projection(Path(tmp), "macbook-pro", owner=False, now=NOW)
        self.assertEqual(payload["state"], "owner_only")
        self.assertNotIn("top_processes", payload)
        self.assertNotIn("firewall", payload)

    def test_owner_sees_fresh_then_stale(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.write(Path(tmp), "macbook-pro.json", "2026-11-02T11:50:00Z")
            fresh = care_projection(Path(tmp), "macbook-pro", owner=True, now=NOW)
            stale = care_projection(Path(tmp), "macbook-pro", owner=True, now=NOW + timedelta(hours=2))
        self.assertEqual(fresh["state"], "fresh")
        self.assertEqual(fresh["firewall"], {"enabled": True})
        self.assertEqual(stale["state"], "stale")

    def test_missing_file_and_host_named_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(care_projection(Path(tmp), "macbook-pro", owner=True, now=NOW)["state"], "not_installed")
            self.write(Path(tmp), "macbook-pro-de-max.json", "2026-11-02T11:55:00Z")
            self.assertEqual(care_projection(Path(tmp), "macbook-pro", owner=True, now=NOW)["state"], "fresh")
        self.assertEqual(care_projection(Path("/tmp"), "../etc", owner=True)["state"], "unknown_machine")

    def test_server_routes_care_through_the_owner_check(self):
        source = SERVER.read_text()
        self.assertIn('"/api/machines/care"', source)
        self.assertIn("care_projection(MAC_CARE_DIR, machine, owner=self._dashboard_run_authorized())", source)

    def test_installer_adds_the_collector_only_for_macs_that_push(self):
        source = INSTALLER.read_text()
        self.assertIn("install_agent com.pirajoke.mac-care-collector mac_care_collector.py 900", source)
        self.assertIn('if [[ "$PUSHES" == "1" ]]; then', source)


def js_function(source, name):
    start = source.index(f"function {name}(")
    depth = 0
    for index in range(source.index("{", start), len(source)):
        depth += {"{": 1, "}": -1}.get(source[index], 0)
        if depth == 0:
            return source[start:index + 1]
    raise AssertionError(f"unclosed {name}")


@unittest.skipUnless(shutil.which("node"), "node is needed to run the page code")
class CareRowsTests(unittest.TestCase):
    def rows(self, care):
        source = HTML.read_text()
        now = int(NOW.timestamp() * 1000)
        script = "\n".join([
            js_function(source, "machineCareWhen"),
            js_function(source, "machineCareRows"),
            f"console.log(JSON.stringify(machineCareRows({json.dumps(care)}, {now}).map(r => [r.label, r.level, r.word])));",
        ])
        out = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True).stdout
        return json.loads(out)

    def test_looked_after_macbook_reads_green(self):
        rows = self.rows({
            "watchdog": {"job": "loaded", "events_7d": 1, "last_event_at": "2026-11-02T08:00:00Z", "last_event": "stopped Plaud"},
            "hygiene": {"job": "loaded", "report_at": "2026-11-02T09:00:00Z", "headline": "ok", "attention": 0},
            "restart": {"scheduled": True, "schedule": "restart at 4:00AM Sunday", "boot_at": "2026-11-02T03:00:00Z"},
            "firewall": {"enabled": True},
            "updates": {"pending": [], "checked_at": "2026-11-02T09:00:00Z"},
            "swap": {"used_gb": 0.5, "total_gb": 2},
            "top_processes": [{"name": "Chrome", "cpu": 30}],
            "disabled_agents": 16,
        })
        self.assertTrue(all(level == "ok" for _, level, _ in rows), rows)
        self.assertEqual(len(rows), 8)

    def test_todays_macbook_calls_out_firewall_and_update(self):
        rows = dict((label, (level, word)) for label, level, word in self.rows({
            "watchdog": {"job": "missing"},
            "firewall": {"enabled": False},
            "updates": {"pending": ["macOS Tahoe 26.7.2"]},
            "swap": {"used_gb": 7.0, "total_gb": 8},
            "top_processes": [{"name": "Plaud", "cpu": 120}],
        }))
        self.assertEqual(rows["Защита от зависаний"], ("bad", "не запущена"))
        self.assertEqual(rows["Файрвол"], ("warn", "выключен"))
        self.assertEqual(rows["Обновления"], ("warn", "ждут: 1"))
        self.assertEqual(rows["Память на диске (swap)"], ("bad", "много"))
        self.assertEqual(rows["Сейчас грузят процессор"], ("warn", "есть тяжёлый"))
        self.assertEqual(rows["Перезагрузка по воскресеньям"][0], "unknown")


if __name__ == "__main__":
    unittest.main()
