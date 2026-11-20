import sys, tempfile
from pathlib import Path
from ruamel.yaml import YAML
sys.path.insert(0, str(Path.cwd()/'builder/dashboard_builder'))
from kanban_setup import register
with tempfile.TemporaryDirectory() as root:
    config=Path(root)/'config.yaml'; config.write_text('# owner comment\nmcp_servers:\n  existing:\n    command: other\n')
    register(config,'/bin/uv',Path('/some/kanban_mcp.py'))
    edited=config.read_bytes()
    assert b'# owner comment' in edited
    assert set(YAML().load(edited)['mcp_servers'])=={'existing','command_center'}
    assert config.stat().st_mode & 0o777 == 0o600
    register(config,'/bin/uv',Path('/some/kanban_mcp.py'))
    assert edited==config.read_bytes()
    try:
        register(config,'/bin/uv',Path('/wrong/kanban.py'))
    except ValueError:
        pass
    else:
        raise AssertionError('overwrote an existing connection')
