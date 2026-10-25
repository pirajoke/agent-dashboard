import json
import importlib.util
import io
from pathlib import Path
import plistlib
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from dashboard_builder.shared_task_board import projection


class SharedTaskBoardTests(unittest.TestCase):
    def test_owner_projection_uses_jarvis_and_returns_only_task_fields(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            path = home / 'Library/LaunchAgents/com.pirajoke.jarvis-bot.plist'
            path.parent.mkdir(parents=True)
            path.write_bytes(plistlib.dumps({'EnvironmentVariables': {
                'JARVIS_TASKS_ENABLED': '1', 'JARVIS_NOTION_TOKEN_FILE': '/private/key',
                'JARVIS_NOTION_TASK_BOARD_URL': 'https://www.notion.so/board'}}))

            def run(argv, **kwargs):
                self.assertEqual(argv[:3], [str(home / 'jarvis/.venv/bin/python'), '-B', '-c'])
                self.assertEqual(kwargs['env']['JARVIS_NOTION_TOKEN_FILE'], '/private/key')
                self.assertEqual(kwargs['env']['PYTHONPATH'], str(home / 'jarvis/src'))
                return subprocess.CompletedProcess(argv, 0, json.dumps([{
                    'id': 'a', 'title': 'Fresh task', 'status': 'doing',
                    'due_date': '', 'project': 'JARVIS', 'url': 'https://www.notion.so/a',
                    'revision': 'today', 'secret': 'never expose'}]), '')

            result = projection(home, run=run)
            self.assertEqual(result['state'], 'ready')
            self.assertEqual(result['tasks'][0]['title'], 'Fresh task')
            self.assertNotIn('secret', result['tasks'][0])

    def test_unavailable_is_not_an_empty_success(self):
        with tempfile.TemporaryDirectory() as temporary:
            self.assertEqual(projection(Path(temporary))['state'], 'unavailable')

    def test_anonymous_endpoint_never_reads_private_board(self):
        builder = Path(__file__).resolve().parents[1]
        spec = importlib.util.spec_from_file_location('shared_task_server', builder / 'dashboard-server-m4.py')
        server = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(server)
        handler = server.Handler.__new__(server.Handler)
        handler.path, handler.command = '/api/shared-tasks', 'GET'
        handler.headers = {'Host': 'command.meshly.fr'}
        handler.wfile = io.BytesIO()
        status = {}
        handler.send_response = lambda code, *args: status.update(code=code)
        handler.send_header = lambda *args: None
        handler.end_headers = lambda: None
        with patch.object(server.Handler, '_cloudflare_access_owner', return_value=False), \
             patch.object(server, '_dashboard_run_token', return_value='owner-token'), \
             patch.object(server, 'shared_task_board_projection', side_effect=AssertionError('private read')):
            handler.do_GET()
        self.assertEqual(status['code'], 401)
        self.assertEqual(json.loads(handler.wfile.getvalue())['tasks'], [])


if __name__ == '__main__':
    unittest.main()
