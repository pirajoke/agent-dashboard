"""Owner-only projection of JARVIS's canonical Notion task board.

The dashboard never stores a second task list or receives the Notion token.
Only the local JARVIS runtime reads its own LaunchAgent configuration.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import plistlib
import subprocess


_SCRIPT = """
import json
from dataclasses import asdict
from pathlib import Path
from jarvis.notion_tasks import NotionTaskBoard, config_from_env
board = NotionTaskBoard(config_from_env(), Path.home() / 'jarvis' / 'data' / 'shared-task-operations.sqlite3')
tasks = board.list_tasks(include_done=True)
print(json.dumps([asdict(task) for task in tasks], ensure_ascii=False))
"""


def projection(home: Path | None = None, *, run=subprocess.run) -> dict:
    home = home or Path.home()
    plist_path = home / 'Library' / 'LaunchAgents' / 'com.pirajoke.jarvis-bot.plist'
    python = home / 'jarvis' / '.venv' / 'bin' / 'python'
    source = home / 'jarvis' / 'src'
    try:
        config = plistlib.loads(plist_path.read_bytes()).get('EnvironmentVariables', {})
        if not isinstance(config, dict) or config.get('JARVIS_TASKS_ENABLED') != '1':
            raise ValueError('board not enabled')
        env = os.environ.copy()
        for key in ('JARVIS_TASKS_ENABLED', 'JARVIS_TASKS_CREATED_AFTER',
                    'JARVIS_NOTION_TASK_DATA_SOURCE_ID', 'JARVIS_NOTION_TASK_BOARD_URL',
                    'JARVIS_NOTION_TOKEN_FILE'):
            if isinstance(config.get(key), str):
                env[key] = config[key]
        env['PYTHONPATH'] = str(source)
        env['PYTHONDONTWRITEBYTECODE'] = '1'
        result = run([str(python), '-B', '-c', _SCRIPT], env=env, capture_output=True,
                     text=True, timeout=45, check=True)
        tasks = json.loads(result.stdout)
        if not isinstance(tasks, list) or any(not isinstance(task, dict) for task in tasks):
            raise ValueError('invalid board response')
        clean = []
        for task in tasks[:100]:
            clean.append({key: task[key] for key in ('id', 'title', 'status', 'due_date',
                                                     'project', 'url', 'revision') if key in task})
        return {'state': 'ready', 'source': 'notion', 'tasks': clean,
                'board_url': config.get('JARVIS_NOTION_TASK_BOARD_URL', '')}
    except (OSError, ValueError, KeyError, subprocess.SubprocessError, json.JSONDecodeError):
        return {'state': 'unavailable', 'source': 'notion', 'tasks': []}
