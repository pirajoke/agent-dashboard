#!/usr/bin/env python3
"""One-way local collector. Paths are operator configuration, never source control."""
import argparse
import fcntl
import json
import os
from pathlib import Path
from dashboard_builder.context_library import build_catalog, export_catalog, _atomic, _read, _safe_path, _valid_catalog, MAX_CATALOG


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vault', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--state-dir', type=Path, required=True)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    try:
        state = _safe_path(args.state_dir)
        if not state.is_dir():
            raise ValueError('state_root_missing')
        snapshot = state / 'catalog.json'
        previous = json.loads(_read(snapshot, MAX_CATALOG)[0]) if snapshot.exists() else None
        if previous is not None and not _valid_catalog(previous):
            raise ValueError('invalid_previous_catalog')
        if args.dry_run:
            catalog = build_catalog(args.vault, previous)
            print(json.dumps({'state': catalog['state'], 'records': len(catalog['records']), 'issues': catalog['issues'], 'dry_run': True}))
            return 0 if catalog['state'] != 'unavailable' else 1
        lock = _safe_path(state / 'collector.lock')
        fd = os.open(str(lock), os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        with os.fdopen(fd, 'a') as stream:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            previous = json.loads(_read(snapshot, MAX_CATALOG)[0]) if snapshot.exists() else None
            catalog = build_catalog(args.vault, previous)
            if catalog['state'] == 'unavailable':
                print(json.dumps({'state': 'unavailable', 'preserved_last_good': True}))
                return 1
            encoded = json.dumps(catalog, ensure_ascii=False, indent=2).encode()
            if len(encoded) > MAX_CATALOG:
                raise ValueError('catalog_size_limit')
            result = export_catalog(catalog, args.output, state / 'manifest.json')
            _atomic(snapshot, encoded)
            print(json.dumps(result))
        return 0
    except (OSError, ValueError, RuntimeError):
        print(json.dumps({'state': 'unavailable', 'reason': 'collector_failed_closed'}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
