"""Docker Guardian on 2026-11-10: a scheduled job between runs is not an error, equal repairs collapse."""
import json
from pathlib import Path
import re
import shutil
import subprocess
import unittest

from test_machine_health import HTML, js_function


@unittest.skipUnless(shutil.which("node"), "node is needed to run the page code")
class ScheduledServiceAndRepairHistoryTests(unittest.TestCase):
    def run_js(self, names, body):
        source = HTML.read_text()
        notes = re.search(r"const SVC_NOTES = .*?;\n", source).group(0)
        script = "\n".join([
            "const SVC_OFF_ON_PURPOSE = [];", notes,
            "function svcSlug(t) { return String(t || '').toLowerCase(); }",
            *(js_function(source, name) for name in names),
            f"console.log(JSON.stringify(({body})()));",
        ])
        return json.loads(subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True).stdout)

    def test_scheduled_job_between_clean_runs_waits_and_a_failed_one_is_an_error(self):
        result = self.run_js(("svcOffOnPurpose", "svcWaiting", "svcProblem"), """() => {
          const job = {name: 'Docker Guardian', status: 'stopped', cat: 'scheduled', interval: 300, desc: 'Ensures Docker'};
          return [
            [svcWaiting({...job, exit_code: 0}), svcProblem({...job, exit_code: 0})],
            [svcWaiting({...job, exit_code: null}), svcProblem({...job, exit_code: null})],
            svcProblem({...job, cat: 'core', exit_code: 1, desc: 'Ensures Docker · последний запуск с ошибкой (код 1)'}).label,
            svcProblem({...job, cat: 'core', exit_code: null, desc: 'Ensures Docker · не загружена в launchd'}).label,
            svcProblem({name: 'Bot', status: 'stopped', exit_code: 0, desc: 'bot'}).label,
          ];
        }""")
        self.assertEqual(result, [[True, None], [True, None], "Ошибка", "Не запущена", "Остановлен"])

    def test_equal_repairs_in_a_row_collapse_into_one_line_with_a_count(self):
        result = self.run_js(("medicRepairGroups",), """() => {
          const same = {machine: 'mini', problem: 'Docker Guardian не работал', fix: 'Запустили заново кнопкой медика'};
          const groups = medicRepairGroups([
            {...same, id: 'a', at: '2026-11-10T14:05:00Z'}, {...same, id: 'b'}, {...same, id: 'c'},
            {machine: 'pro', problem: 'Mac тормозил', fix: 'Закрыли Drive', id: 'd'}, {...same, id: 'e'},
          ]);
          return groups.map(g => [g.entry.id, g.count]);
        }""")
        self.assertEqual(result, [["a", 3], ["d", 1], ["e", 1]])

    def test_scheduled_jobs_are_no_longer_hidden_from_the_list(self):
        source = HTML.read_text()
        self.assertNotIn("filter(s => s.cat !== 'scheduled')", source)
        self.assertIn("'Ждёт запуска'", source)


    def test_main_manager_health_line_uses_the_same_problem_rule(self):
        # 2026-11-11: the MAIN MANAGER line said «Не работает: Live Feed Generator, Daily Hygiene, Docker Guardian»
        # for scheduled jobs that were only waiting for their next run.
        source = HTML.read_text()
        self.assertNotIn("services.filter(service => service.status !== 'running')", source)
        self.assertIn("const down = services.filter(service => svcProblem(service));", source)

if __name__ == "__main__":
    unittest.main()
