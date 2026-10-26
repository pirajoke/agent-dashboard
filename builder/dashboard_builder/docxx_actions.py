"""Mark sorts «Нужен разбор» documents from the site (2026-10-25, «нет кнопок»).

Owner-only. The DOCXX intake worker stays read-only for the dashboard: its status and journal
files are never written. A decision moves the document inside the same DOCXXx library on this
Mac (Google Drive for desktop syncs it), into a folder that already exists there, or leaves it
where it is. Every decision is kept in ``~/.agent-bridge/docxx-decisions.json`` so the page can
show it as settled and «Вернуть» can put the file back. Nothing is deleted, nothing is created at
the library root (the worker treats new root items as incoming), and a file is never overwritten.

«В корзину» (2026-10-26, «есть мусор») is a move too: into an existing Корзина/Trash folder, or a
«Корзина» made inside the review folder. «Разложить по подсказкам» moves each document into the
folder the Mac mini suggested from its content (docxx_suggest.py) and leaves the rest alone.
"""
from __future__ import annotations

import ctypes
import ctypes.util
import errno
import fcntl
import json
import os
import sys
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
TRASH = re.compile(r'корзин|trash|corbeille', re.IGNORECASE)
TRASH_NAME = 'Корзина'
LIBRARY = 'DOCXXx'


def decisions_path(home) -> Path:
    return Path(home) / '.agent-bridge' / 'docxx-decisions.json'


def suggestions_path(home) -> Path:
    return Path(home) / '.agent-bridge' / 'docxx-suggestions.json'


def load_suggestions(path) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    items = data.get('items') if isinstance(data, dict) else None
    if not isinstance(items, dict):
        return {}
    return {k: v for k, v in items.items() if isinstance(k, str) and KEY.fullmatch(k) and isinstance(v, dict)}


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
    if root is not None:
        _find_in_review(rows, root)
    return rows, root


# Google Docs made in Drive appear on this Mac as small .gdoc/.gsheet/.gslides link files.
_DRIVE_LINKS = ('', '.gdoc', '.gsheet', '.gslides', '.gdraw', '.gform')


def _drive_id(row: dict) -> str | None:
    url = str(row.get('url') or '')
    marker = 'https://drive.google.com/file/d/'
    return url[len(marker):].split('/', 1)[0] if url.startswith(marker) else None


def _gdoc_id(path: Path) -> str | None:
    """The Drive id written inside a .gdoc/.gsheet link file, when it has one."""
    if path.suffix not in _DRIVE_LINKS[1:]:
        return None
    try:
        with open(path, 'rb') as stream:
            data = json.loads(stream.read(65536).decode('utf-8'))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    value = data.get('doc_id') or str(data.get('resource_id') or '').rpartition(':')[2]
    return value if isinstance(value, str) and value else None


def _find_in_review(rows: dict, root: Path) -> None:
    """Drive rows whose journal carries no local path: find the file by name in the review folder.

    Only an unambiguous pair counts: one row, one file, no other row on that file, and a Google
    Docs link file whose id matches the row's Drive id when both are known.
    """
    lost = [row for row in rows.values() if row.get('status') == 'needs_review' and not row.get('_path')
            and row.get('name')]
    if not lost:
        return
    taken = {os.path.realpath(row['_path']) for row in rows.values() if row.get('_path')}
    review = [f for f in list_folders(root) if REVIEW.search(f.split('/')[0])]
    matches: dict[str, list[Path]] = {}
    for row in lost:
        found = []
        for folder in review:
            for suffix in _DRIVE_LINKS:
                candidate = root / folder / (row['name'] + suffix)
                if (os.path.isfile(candidate) and not os.path.islink(candidate) and _inside(root, candidate)
                        and os.path.realpath(candidate) not in taken):
                    found.append(candidate)
        matches[row['key']] = found
    claims: dict[str, int] = {}
    for found in matches.values():
        for candidate in found:
            claims[os.path.realpath(candidate)] = claims.get(os.path.realpath(candidate), 0) + 1
    for row in lost:
        found = matches[row['key']]
        if len(found) != 1 or claims[os.path.realpath(found[0])] != 1:
            continue  # Two files, or two rows on one file: leave it to Mark rather than guess.
        inside, expected = _gdoc_id(found[0]), _drive_id(row)
        if inside and expected and inside != expected:
            continue
        row['_path'] = str(found[0])


def folders_view(directory, decisions_file) -> dict:
    decisions = load_decisions(decisions_file)
    rows, root = _sortable(directory, decisions)
    if root is None or not os.path.isdir(root):
        return {'state': 'unavailable', 'folders': [], 'archive': None, 'trash': None, 'recent': []}
    folders = list_folders(root)
    archive = next((f for f in folders if ARCHIVE.search(f.split('/')[-1])), None)
    trash = next((f for f in folders if TRASH.search(f.split('/')[-1])), None)
    review_top = next((f for f in folders if '/' not in f and REVIEW.search(f)), None)
    choices = [f for f in folders if not REVIEW.search(f.split('/')[0]) and f != trash]
    recent = []
    for decision in sorted(decisions.values(), key=lambda d: str(d.get('at', '')), reverse=True):
        folder = decision.get('folder')
        if decision.get('action') == 'move' and folder in choices and folder not in recent:
            recent.append(folder)
        if len(recent) >= 5:
            break
    # Without a trash folder the first «В корзину» makes one inside the review folder, never at the root.
    can_trash = bool(trash or review_top)
    # Rows the Mac mini can actually move; the page offers only «Оставить» for the others.
    movable = [key for key, row in rows.items() if row.get('status') == 'needs_review' and row.get('_path')
               and _inside(root, Path(row['_path']))]
    return {'state': 'ready', 'folders': choices, 'archive': archive, 'trash': trash or None,
            'can_trash': can_trash, 'recent': recent, 'movable': movable}


def _trash_folder(root: Path, view: dict) -> str:
    if view.get('trash'):
        return view['trash']
    top = next((f for f in list_folders(root) if '/' not in f and REVIEW.search(f)), None)
    if not top:
        raise ValueError('no_trash')
    folder = root / top / TRASH_NAME
    if not _inside(root, root / top) or os.path.islink(root / top):
        raise ValueError('no_trash')
    if not os.path.isdir(folder):
        os.mkdir(folder, 0o755)
    return top + '/' + TRASH_NAME


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


_LIBC = None


def _rename_noreplace(source: Path, target: Path) -> None:
    """One atomic rename that fails with FileExistsError instead of replacing a file Drive just synced."""
    global _LIBC
    try:
        if _LIBC is None:
            _LIBC = ctypes.CDLL(ctypes.util.find_library('c'), use_errno=True)
        old, new = os.fsencode(source), os.fsencode(target)
        if sys.platform == 'darwin':
            result = _LIBC.renamex_np(old, new, ctypes.c_uint(0x4))  # RENAME_EXCL
        else:
            result = _LIBC.renameat2(-100, old, -100, new, ctypes.c_uint(1))  # AT_FDCWD, RENAME_NOREPLACE
    except (OSError, AttributeError, TypeError):
        result, code = -1, errno.ENOSYS
    else:
        code = ctypes.get_errno() if result else 0
    if not result:
        return
    if code == errno.EEXIST:
        raise FileExistsError(errno.EEXIST, 'target exists', str(target))
    if code not in (errno.ENOSYS, errno.ENOTSUP, errno.EINVAL, getattr(errno, 'EOPNOTSUPP', errno.ENOTSUP)):
        raise OSError(code, os.strerror(code), str(source))
    # The file system has no exclusive rename: the narrowest check we can make.
    if os.path.lexists(target):
        raise FileExistsError(errno.EEXIST, 'target exists', str(target))
    os.rename(source, target)


def apply(directory, decisions_file, body: dict, suggestions_file=None) -> dict:
    """Apply one decision to up to MAX_KEYS rows. Answers per row; never raises for one bad row."""
    if not isinstance(body, dict):
        raise ValueError('invalid_request')
    action, keys = body.get('action'), body.get('keys')
    if action not in ('move', 'archive', 'trash', 'auto', 'keep', 'undo'):
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
        folder_rel, allowed = None, set()
        if action in ('move', 'archive', 'trash', 'auto'):
            if root is None:
                raise ValueError('library_unavailable')
            view = folders_view(directory, decisions_file)
            allowed = set(view['folders']) | ({view['archive']} if view['archive'] else set())
            if action == 'trash':
                folder_rel = _trash_folder(root, view)
            elif action != 'auto':
                folder_rel = view['archive'] if action == 'archive' else body.get('folder')
                if not isinstance(folder_rel, str) or folder_rel not in allowed:
                    raise ValueError('invalid_folder')
        guesses = load_suggestions(suggestions_file) if action == 'auto' and suggestions_file else {}
        results = []
        now = datetime.now(timezone.utc).isoformat()
        commit = lambda: _save_decisions(decisions_file, decisions)  # noqa: E731
        for key in dict.fromkeys(keys):
            if action == 'auto':
                guess, row = guesses.get(key) or {}, rows.get(key) or {}
                folder = guess.get('folder')
                if guess.get('junk') is True or guess.get('name') != row.get('name') or folder not in allowed:
                    results.append({'key': key, 'ok': False, 'error': 'no_suggestion'})
                    continue
                results.append(_one(key, 'move', folder, rows, root, decisions, now, commit))
                continue
            results.append(_one(key, action, folder_rel, rows, root, decisions, now, commit))
        commit()
    return {'state': 'ready', 'results': results}


def _one(key, action, folder_rel, rows, root, decisions, now, commit) -> dict:
    # A file only moves after the record that can undo it is on disk.
    row = rows.get(key)
    if row is None:
        return {'key': key, 'ok': False, 'error': 'not_found'}
    if action == 'undo':
        decision = decisions.get(key)
        if not decision:
            return {'key': key, 'ok': False, 'error': 'nothing_to_undo'}
        if decision.get('action') in ('move', 'archive', 'trash'):
            back_root = Path(decision.get('root') or '')
            moved, original = back_root / str(decision.get('to', '')), back_root / str(decision.get('from', ''))
            if (not back_root.is_absolute() or not _inside(back_root, moved) or not _inside(back_root, original)
                    or not os.path.lexists(moved) or os.path.islink(moved)):
                return {'key': key, 'ok': False, 'error': 'not_found'}
            if os.path.lexists(original) or not os.path.isdir(original.parent):
                return {'key': key, 'ok': False, 'error': 'occupied'}
            del decisions[key]
            try:
                commit()
            except OSError:
                decisions[key] = decision
                raise
            try:
                _rename_noreplace(moved, original)
            except OSError as error:
                decisions[key] = decision
                commit()
                return {'key': key, 'ok': False, 'error': 'occupied' if isinstance(error, FileExistsError) else 'move_failed'}
            return {'key': key, 'ok': True}
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
    except OSError:
        return {'key': key, 'ok': False, 'error': 'not_found'}
    for _ in range(20):
        target = _free_name(folder, source.name)
        decisions[key] = {'action': action, 'folder': folder_rel, 'from': original,
                          'to': _relative(root, target), 'root': str(root), 'at': now}
        try:
            commit()
        except OSError:
            del decisions[key]
            raise
        try:
            _rename_noreplace(source, target)  # Same library, same disk: never a copy that could leave two.
        except FileExistsError:
            continue  # Drive put a file there just now: take the next free name.
        except OSError:
            del decisions[key]
            commit()
            return {'key': key, 'ok': False, 'error': 'move_failed'}
        return {'key': key, 'ok': True, 'destination': decisions[key]['to']}
    del decisions[key]
    commit()
    return {'key': key, 'ok': False, 'error': 'occupied'}
