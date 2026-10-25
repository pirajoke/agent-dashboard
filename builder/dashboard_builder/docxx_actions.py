"""Mark sorts «Нужен разбор» documents from the site (2026-10-25, «нет кнопок»).

Owner-only. The DOCXX intake worker stays read-only for the dashboard: its status and journal
files are never written. A decision moves the document inside the same DOCXXx library on this
Mac (Google Drive for desktop syncs it), into a folder that already exists there, or leaves it
where it is. Every decision is kept in ``~/.agent-bridge/docxx-decisions.json`` so the page can
show it as settled and «Вернуть» can put the file back. Nothing is deleted, nothing is created at
the library root (the worker treats new root items as incoming), and a file is never overwritten.
"""
from __future__ import annotations

import fcntl
import json
import os
import re
import stat
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from .docxx import docxx_projection

MAX_KEYS = 50
MAX_FOLDERS = 400
MAX_DECISIONS = 5000
KEY = re.compile(r'^[0-9a-f]{20}$')
ARCHIVE = re.compile(r'archiv|архив', re.IGNORECASE)
REVIEW = re.compile(r'to review|разобрать|на разбор', re.IGNORECASE)
LIBRARY = 'DOCXXx'


def decisions_path(home) -> Path:
    return Path(home) / '.agent-bridge' / 'docxx-decisions.json'


def load_decisions(path) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    items = data.get('decisions') if isinstance(data, dict) else None
    if not isinstance(items, dict):
        return {}
    return {k: v for k, v in items.items() if isinstance(k, str) and KEY.fullmatch(k) and isinstance(v, dict)}


def _save_decisions(path, decisions: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if len(decisions) > MAX_DECISIONS:
        newest = sorted(decisions.items(), key=lambda item: str(item[1].get('at', '')))[-MAX_DECISIONS:]
        decisions = dict(newest)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix='.docxx-decisions-')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump({'schema_version': 1, 'decisions': decisions}, stream, ensure_ascii=False, indent=1)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _root_of(path: str) -> Path | None:
    head, sep, _ = path.partition('/' + LIBRARY + '/')
    return Path(head + '/' + LIBRARY) if sep else None


def _inside(root: Path, candidate: Path) -> bool:
    try:
        real_root = os.path.realpath(root)
        return os.path.realpath(candidate).startswith(real_root + os.sep)
    except (OSError, ValueError):
        return False


def _relative(root: Path, path: Path) -> str:
    return str(Path(os.path.realpath(path)).relative_to(os.path.realpath(root)))


def list_folders(root: Path) -> list[str]:
    """Existing folders two levels deep, hidden and linked ones skipped."""
    found: list[str] = []
    try:
        top = sorted(os.scandir(root), key=lambda e: e.name.lower())
    except OSError:
        return []
    for entry in top:
        if entry.name.startswith('.') or not entry.is_dir(follow_symlinks=False):
            continue
        found.append(entry.name)
        try:
            inner = sorted(os.scandir(entry.path), key=lambda e: e.name.lower())
        except OSError:
            continue
        for child in inner:
            if not child.name.startswith('.') and child.is_dir(follow_symlinks=False):
                found.append(entry.name + '/' + child.name)
        if len(found) >= MAX_FOLDERS:
            break
    return found[:MAX_FOLDERS]


def _sortable(directory, decisions: dict):
    """Rows on the page with their private local path, and the library root they live in."""
    data = docxx_projection(directory, owner=True, decisions=decisions, include_paths=True)
    rows = {row['key']: row for row in data.get('records', []) if isinstance(row, dict)}
    roots = [_root_of(row['_path']) for row in rows.values() if row.get('_path')]
    roots = [root for root in roots if root is not None]
    root = max(set(roots), key=roots.count) if roots else None
    return rows, root


def folders_view(directory, decisions_file) -> dict:
    decisions = load_decisions(decisions_file)
    _, root = _sortable(directory, decisions)
    if root is None or not os.path.isdir(root):
        return {'state': 'unavailable', 'folders': [], 'archive': None, 'recent': []}
    folders = list_folders(root)
    archive = next((f for f in folders if ARCHIVE.search(f.split('/')[-1])), None)
    choices = [f for f in folders if not REVIEW.search(f.split('/')[0])]
    recent = []
    for decision in sorted(decisions.values(), key=lambda d: str(d.get('at', '')), reverse=True):
        folder = decision.get('folder')
        if decision.get('action') == 'move' and folder in choices and folder not in recent:
            recent.append(folder)
        if len(recent) >= 5:
            break
    return {'state': 'ready', 'folders': choices, 'archive': archive, 'recent': recent}


def _free_name(folder: Path, name: str) -> Path:
    target = folder / name
    stem, dot, suffix = name.rpartition('.')
    if not dot or not stem:
        stem, suffix = name, ''
    else:
        suffix = '.' + suffix
    number = 2
    while os.path.lexists(target):
        target = folder / f'{stem} ({number}){suffix}'
        number += 1
    return target


def _move(source: Path, folder: Path) -> Path:
    target = _free_name(folder, source.name)
    os.rename(source, target)  # Same library, same disk: never a copy that could leave two.
    return target


def apply(directory, decisions_file, body: dict) -> dict:
    """Apply one decision to up to MAX_KEYS rows. Answers per row; never raises for one bad row."""
    if not isinstance(body, dict):
        raise ValueError('invalid_request')
    action, keys = body.get('action'), body.get('keys')
    if action not in ('move', 'archive', 'keep', 'undo'):
        raise ValueError('invalid_action')
    if (not isinstance(keys, list) or not 1 <= len(keys) <= MAX_KEYS
            or not all(isinstance(k, str) and KEY.fullmatch(k) for k in keys)):
        raise ValueError('invalid_keys')
    decisions_file = Path(decisions_file)
    decisions_file.parent.mkdir(parents=True, exist_ok=True)
    with open(decisions_file.with_suffix('.lock'), 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        decisions = load_decisions(decisions_file)
        rows, root = _sortable(directory, decisions)
        folder_rel = None
        if action in ('move', 'archive'):
            if root is None:
                raise ValueError('library_unavailable')
            view = folders_view(directory, decisions_file)
            folder_rel = view['archive'] if action == 'archive' else body.get('folder')
            allowed = set(view['folders']) | ({view['archive']} if view['archive'] else set())
            if not isinstance(folder_rel, str) or folder_rel not in allowed:
                raise ValueError('invalid_folder')
        results = []
        now = datetime.now(timezone.utc).isoformat()
        for key in dict.fromkeys(keys):
            results.append(_one(key, action, folder_rel, rows, root, decisions, now))
        _save_decisions(decisions_file, decisions)
    return {'state': 'ready', 'results': results}


def _one(key, action, folder_rel, rows, root, decisions, now) -> dict:
    row = rows.get(key)
    if row is None:
        return {'key': key, 'ok': False, 'error': 'not_found'}
    if action == 'undo':
        decision = decisions.get(key)
        if not decision:
            return {'key': key, 'ok': False, 'error': 'nothing_to_undo'}
        if decision.get('action') in ('move', 'archive'):
            back_root = Path(decision.get('root') or '')
            moved, original = back_root / str(decision.get('to', '')), back_root / str(decision.get('from', ''))
            if (not back_root.is_absolute() or not _inside(back_root, moved) or not _inside(back_root, original)
                    or not os.path.lexists(moved) or os.path.islink(moved)):
                return {'key': key, 'ok': False, 'error': 'not_found'}
            if os.path.lexists(original) or not os.path.isdir(original.parent):
                return {'key': key, 'ok': False, 'error': 'occupied'}
            try:
                os.rename(moved, original)
            except OSError:
                return {'key': key, 'ok': False, 'error': 'move_failed'}
        del decisions[key]
        return {'key': key, 'ok': True}
    if row.get('status') != 'needs_review':
        return {'key': key, 'ok': False, 'error': 'already_sorted'}
    if action == 'keep':
        decisions[key] = {'action': 'keep', 'at': now}
        return {'key': key, 'ok': True}
    path = row.get('_path')
    source = Path(path) if path else None
    if (source is None or root is None or _root_of(path) != root or not _inside(root, source)
            or os.path.islink(source) or not os.path.lexists(source)):
        return {'key': key, 'ok': False, 'error': 'not_found'}
    folder = root / folder_rel
    if not _inside(root, folder) or os.path.islink(folder) or not os.path.isdir(folder):
        return {'key': key, 'ok': False, 'error': 'invalid_folder'}
    if os.path.realpath(source.parent) == os.path.realpath(folder):
        decisions[key] = {'action': 'keep', 'at': now}
        return {'key': key, 'ok': True}
    try:
        mode = os.lstat(source).st_mode
        if not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
            return {'key': key, 'ok': False, 'error': 'not_found'}
        original = _relative(root, source)
        target = _move(source, folder)
    except OSError:
        return {'key': key, 'ok': False, 'error': 'move_failed'}
    decisions[key] = {'action': action, 'folder': folder_rel, 'from': original,
                      'to': _relative(root, target), 'root': str(root), 'at': now}
    return {'key': key, 'ok': True, 'destination': decisions[key]['to']}
