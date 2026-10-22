#!/usr/bin/env python3
"""Single local transcript intake and one-way context export runner."""
import argparse
import contextlib
import fcntl
import json
import os
from pathlib import Path
from dashboard_builder.context_library import (
    build_catalog, export_catalog, _atomic, _read, _safe_path,
    _valid_catalog, MAX_CATALOG,
)
from transcript_intake import import_transcript_exports


def run(config_path, dry_run=False):
    config = json.loads(_read(config_path, 16384)[0])
    keys = ('vault', 'output', 'state_dir', 'intake')
    if not isinstance(config, dict) or any(not isinstance(config.get(k), str) for k in keys):
        raise ValueError('invalid_config')
    paths = {k: _safe_path(config[k]) for k in keys}
    if any(not p.is_dir() for p in paths.values()):
        raise ValueError('missing_root')
    state = paths['state_dir']
    if any(state == paths[k] or paths[k] in state.parents for k in ('vault', 'output', 'intake')):
        raise ValueError('state_must_be_external')
    lock = contextlib.nullcontext()
    if not dry_run:
        fd = os.open(str(_safe_path(state / 'runner.lock')),
                     os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        lock = os.fdopen(fd, 'a')
    with lock as stream:
        if not dry_run:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        snapshot = _safe_path(state / 'catalog.json')
        previous = json.loads(_read(snapshot, MAX_CATALOG)[0]) if snapshot.exists() else None
        if previous is not None and not _valid_catalog(previous):
            raise ValueError('invalid_previous_catalog')
        catalog = build_catalog(paths['vault'], previous)
        if catalog['state'] == 'unavailable':
            raise ValueError('source_unavailable')
        imported = import_transcript_exports(paths['vault'], paths['intake'], state / 'intake.json', dry_run)
        if dry_run:
            return dict(state=catalog['state'], records=len(catalog['records']), intake=imported, dry_run=True)
        if imported['imported']:
            catalog = build_catalog(paths['vault'], previous)
        if catalog['state'] == 'unavailable':
            raise ValueError('source_unavailable')
        encoded = json.dumps(catalog, ensure_ascii=False, indent=2).encode()
        if len(encoded) > MAX_CATALOG:
            raise ValueError('catalog_size_limit')
        exported = export_catalog(catalog, paths['output'], state / 'manifest.json')
        _atomic(snapshot, encoded)
        return dict(state=catalog['state'], records=len(catalog['records']), issues=catalog['issues'],
                    intake=imported, export=exported)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    try:
        result = run(args.config, args.dry_run)
    except (OSError, ValueError, RuntimeError, TypeError, KeyError):
        print(json.dumps(dict(state='unavailable', reason='runner_failed_closed')))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
