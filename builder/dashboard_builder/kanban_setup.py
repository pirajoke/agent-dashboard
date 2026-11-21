# /// script
# requires-python = ">=3.10"
# dependencies = ["ruamel.yaml>=0.18,<0.20"]
# ///
"""Register stdio MCP in an existing, owner-only jarvis profile, preserving other tools."""
import fcntl
import os
from pathlib import Path
import shutil
import tempfile

from ruamel.yaml import YAML


def register(path, executable, script):
    yaml = YAML()
    yaml.preserve_quotes = True
    if path.is_symlink() or not path.is_file() or path.stat().st_uid != os.getuid():
        raise RuntimeError('Expected an existing owner profile')
    config = path.read_text()
    settings = yaml.load(config)
    servers = settings.setdefault('mcp_servers', {})
    spec = {'command': executable, 'args': ['run', '--script', str(script)], 'timeout': 120}
    if 'command_center' in servers:
        if servers['command_center'] == spec:
            return
        raise ValueError('A different command_center MCP server is configured')
    servers['command_center'] = spec
    with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as temp:
        stage = Path(temp.name)
        try:
            yaml.dump(settings, temp)
            temp.flush()
            os.fsync(temp.fileno())
            if path.read_text() != config:
                raise RuntimeError('Profile changed concurrently, retry')
            os.replace(stage, path)
        finally:
            stage.unlink(missing_ok=True)


if __name__ == '__main__':
    uv = shutil.which('uv')
    if not uv:
        raise SystemExit('Install uv before registering the MCP server')
    profile = Path.home() / '.hermes' / 'profiles' / 'jarvis'
    with (profile / '.command-center-mcp.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        register(profile / 'config.yaml', uv, Path(__file__).with_name('kanban_mcp.py').resolve())
