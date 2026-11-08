"""Техника → MacBook Pro shows how the laptop is looked after (Mark 2026-11-02)."""
import importlib.util
import json
import plistlib
import shutil
import subprocess
import tempfile
import unittest
import unittest.mock
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


class ThermalCollectorTests(unittest.TestCase):
    """Mark 2026-11-08 «температуру компьютера в технике … чтобы мог трекать»."""

    M1_SENSORS = {"PMU tdie1": 48.2, "PMU tdie4": 55.9, "PMU tdev2": 41.0, "PMU tcal": 51.8,
                  "NAND CH0 temp": 38.0, "gas gauge battery": 31.5, "PMU TP3w": 44.0}

    def test_cpu_is_the_hottest_die_sensor_and_tcal_is_ignored(self):
        status = collector.thermal_status(self.M1_SENSORS, "com.apple.system.thermalpressurelevel 0")
        self.assertEqual(status["cpu_c"], 55.9)
        self.assertEqual(status["max_c"], 55.9)
        self.assertEqual(status["ssd_c"], 38.0)
        self.assertEqual(status["battery_c"], 31.5)
        self.assertEqual(status["sensors"], 7)
        self.assertEqual(status["pressure"], "nominal")

    def test_core_sensors_and_pmu_fallback(self):
        self.assertEqual(collector.thermal_status({"pACC MTR Temp Sensor3": 71.0, "eACC MTR Temp Sensor0": 60.0}, None)["cpu_c"], 71.0)
        self.assertEqual(collector.thermal_status({"PMU tdev1": 47.0, "PMU tcal": 51.8}, None)["cpu_c"], 47.0)
        self.assertEqual(collector.thermal_status({"macmon cpu": 63.4}, None)["cpu_c"], 63.4)

    def test_no_sensors_stays_unknown_but_keeps_pressure(self):
        status = collector.thermal_status(None, "com.apple.system.thermalpressurelevel 2")
        self.assertIsNone(status["cpu_c"])
        self.assertEqual(status["sensors"], 0)
        self.assertEqual(status["pressure"], "heavy")
        self.assertIsNone(collector.thermal_status({}, "garbage")["pressure"])

    def test_history_keeps_seven_days_and_appends_now(self):
        old = [{"t": "2026-10-20T12:00:00Z", "cpu": 90.0, "p": "nominal"},
               {"t": "2026-11-01T12:00:00Z", "cpu": 50.0, "p": "nominal"},
               {"t": "bad", "cpu": 1}, "junk"]
        history = collector.thermal_history(old, {"cpu_c": 61.2, "pressure": "moderate"}, NOW)
        self.assertEqual([p["t"] for p in history], ["2026-11-01T12:00:00Z", "2026-11-02T12:00:00Z"])
        self.assertEqual(history[-1], {"t": "2026-11-02T12:00:00Z", "cpu": 61.2, "p": "moderate"})
        # Nothing readable → nothing appended.
        self.assertEqual(len(collector.thermal_history(old, {"cpu_c": None, "pressure": None}, NOW)), 1)

    def test_main_keeps_history_between_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mac-mini.json"
            path.write_text(json.dumps({"thermal_history": [{"t": collector.iso_z(datetime.now(timezone.utc) - timedelta(hours=1)),
                                                            "cpu": 52.0, "p": "nominal"}]}))
            with unittest.mock.patch.object(collector, "sensors_in_child", return_value={"PMU tdie1": 57.0}):
                self.assertEqual(collector.main(["--out", tmp, "--machine", "mac-mini"]), 0)
            data = json.loads(path.read_text())
        self.assertEqual(data["thermal"]["cpu_c"], 57.0)
        self.assertEqual([p["cpu"] for p in data["thermal_history"]], [52.0, 57.0])

    def test_sensor_reader_is_harmless_off_macos(self):
        if collector.sys.platform != "darwin":
            self.assertIsNone(collector.read_hid_temperatures())


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
            self.write(Path(tmp), "macbook-pro-example.json", "2026-11-02T11:55:00Z")
            self.assertEqual(care_projection(Path(tmp), "macbook-pro", owner=True, now=NOW)["state"], "fresh")
        self.assertEqual(care_projection(Path("/tmp"), "../etc", owner=True)["state"], "unknown_machine")

    def test_owner_gets_a_day_of_points_and_a_line_per_day(self):
        history = [{"t": "2026-10-30T12:00:00Z", "cpu": 70.0, "p": "nominal"},
                   {"t": "2026-10-30T13:00:00Z", "cpu": 80.0, "p": "moderate"},
                   {"t": "2026-11-02T08:00:00Z", "cpu": 50.0, "p": "nominal"},
                   {"t": "2026-11-02T11:55:00Z", "cpu": 54.0, "p": "nominal"}]
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "mac-mini.json").write_text(json.dumps({
                "generated_at": "2026-11-02T11:55:00Z", "thermal": {"cpu_c": 54.0, "pressure": "nominal"},
                "thermal_history": history}))
            payload = care_projection(Path(tmp), "mac-mini", owner=True, now=NOW)
            public = care_projection(Path(tmp), "mac-mini", owner=False, now=NOW)
        self.assertEqual(payload["thermal"]["cpu_c"], 54.0)
        self.assertEqual([p["cpu"] for p in payload["thermal_history"]["last_24h"]], [50.0, 54.0])
        days = payload["thermal_history"]["days"]
        self.assertEqual(days[0]["max"], 80.0)
        self.assertEqual(days[0]["avg"], 75.0)
        self.assertEqual(days[0]["worst_pressure"], "moderate")
        self.assertNotIn("thermal", public)
        self.assertNotIn("thermal_history", public)

    def test_server_routes_care_through_the_owner_check(self):
        source = SERVER.read_text()
        self.assertIn('"/api/machines/care"', source)
        self.assertIn("care_projection(MAC_CARE_DIR, machine, owner=self._dashboard_run_authorized())", source)

    def test_installer_adds_the_collector_on_every_mac(self):
        # Mark 2026-11-08: the Mac mini runs it too, so Техника shows its temperature.
        source = INSTALLER.read_text()
        self.assertIn("install_agent com.pirajoke.mac-care-collector mac_care_collector.py 300", source)
        self.assertIn("live_sessions_collector.py mac_care_collector.py)", source)
        self.assertNotIn('if [[ "$PUSHES" == "1" ]]; then', source)


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
            js_function(source, "machineCareSchedule"),
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

    def thermal(self, care):
        source = HTML.read_text()
        now = int(NOW.timestamp() * 1000)
        script = "\n".join([
            source[source.index("const THERMAL_HOT_C"):source.index("function machineThermalSummary(")],
            js_function(source, "thermalLevel"),
            js_function(source, "machineThermalSummary"),
            js_function(source, "thermalChartPath"),
            f"const s = machineThermalSummary({json.dumps(care)}, {now});",
            f"console.log(JSON.stringify({{level: s.level, word: s.word, value: s.value, detail: s.detail, state: s.state, path: thermalChartPath(s.points, {now}).path}}));",
        ])
        out = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True).stdout
        return json.loads(out)

    def test_temperature_words_and_chart(self):
        calm = self.thermal({"thermal": {"cpu_c": 46.4, "ssd_c": 38, "pressure": "nominal"},
                             "thermal_history": {"last_24h": [{"t": "2026-11-02T10:00:00Z", "cpu": 44},
                                                              {"t": "2026-11-02T10:05:00Z", "cpu": 70},
                                                              {"t": "2026-11-02T11:55:00Z", "cpu": 46}], "days": []}})
        self.assertEqual((calm["level"], calm["word"], calm["value"]), ("ok", "норма", "46°"))
        self.assertIn("за сутки макс 70°", calm["detail"])
        self.assertEqual(calm["path"].count("M"), 2)  # the 110-minute gap breaks the line
        hot = self.thermal({"thermal": {"cpu_c": 88, "pressure": "nominal"}})
        self.assertEqual((hot["level"], hot["word"]), ("warn", "горячо"))
        throttled = self.thermal({"thermal": {"cpu_c": 70, "pressure": "heavy"}})
        self.assertEqual((throttled["level"], throttled["word"]), ("bad", "перегрев"))
        unknown = self.thermal({"thermal": {"cpu_c": None, "pressure": None}})
        self.assertEqual(unknown["word"], "датчики не читаются")
        self.assertEqual(self.thermal({})["state"], "no_thermal")

    def test_both_machines_have_a_temperature_block(self):
        source = HTML.read_text()
        for key in ("mini", "pro"):
            self.assertIn(f'id="{key}-thermal"', source)
        self.assertIn("refreshMachineCare('mini', 'mac-mini');", source)
        self.assertIn("renderMachineThermal(key, care);", source)

    def test_restart_detail_comes_from_the_real_schedule(self):
        source = HTML.read_text()
        script = js_function(source, "machineCareSchedule") + "\nconsole.log(JSON.stringify(['restart at 4:00AM Sunday', 'shutdown at 11:30PM weekdays', 'odd'].map(machineCareSchedule)));"
        out = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True).stdout
        self.assertEqual(json.loads(out), ["перезагрузка, вс 04:00", "выключение, по будням 23:30", "odd"])

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
