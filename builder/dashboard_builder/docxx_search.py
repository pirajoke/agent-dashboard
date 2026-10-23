"""Read-only, bounded search of registered versions. No cloud verification."""
from pathlib import Path
import re
import sqlite3
import stat
import time

from .docxx import _drive_link

MAX_DATABASE = 512 * 1024 * 1024
SAFE_ID = re.compile(r'[A-Za-z0-9_-]{1,160}')
HASH = re.compile(r'[0-9a-f]{64}')


def docxx_search(directory, query, *, owner=False, limit=20):
    if not owner:
        return {'state': 'owner_required', 'results': []}
    if (not isinstance(query, str) or len(query) > 500 or '\x00' in query
            or type(limit) is not int or not 1 <= limit <= 100):
        return {'state': 'invalid_query', 'results': []}
    query = query.strip().casefold()
    if not query:
        return {'state': 'ready', 'results': []}
    unavailable = {'state': 'unavailable', 'results': []}
    connection = None
    try:
        directory = Path(directory).absolute()
        if directory.is_symlink():
            return unavailable
        database = directory / 'operations.sqlite3'
        info = database.lstat()
        if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= MAX_DATABASE:
            return unavailable
        for suffix in ('-wal', '-shm', '-journal'):
            sidecar = Path(str(database) + suffix)
            try:
                side_info = sidecar.lstat()
            except FileNotFoundError:
                continue
            if not stat.S_ISREG(side_info.st_mode) or side_info.st_size > MAX_DATABASE:
                return unavailable
        connection = sqlite3.connect(database.as_uri() + '?mode=ro', uri=True, timeout=1)
        after = database.lstat()
        if (info.st_dev, info.st_ino) != (after.st_dev, after.st_ino):
            return unavailable
        connection.execute('PRAGMA query_only=ON')
        connection.execute('PRAGMA trusted_schema=OFF')
        deadline = time.monotonic() + 2
        connection.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
        connection.create_function('docxx_casefold', 1, lambda value: value.casefold() if isinstance(value, str) else '')
        rows = connection.execute('''SELECT document_id, file_id, sha256,
            substr(text, 1, 100000) FROM search_documents
            WHERE instr(docxx_casefold(substr(text, 1, 100000)), ?) > 0
            LIMIT ?''', (query, limit))
        results, seen = [], set()
        for document_id, file_id, sha, text in rows:
            if (not isinstance(document_id, str) or not SAFE_ID.fullmatch(document_id)
                    or not isinstance(sha, str) or not HASH.fullmatch(sha) or not isinstance(text, str)):
                continue
            url = _drive_link(file_id)
            identity = (document_id, file_id if url else None, sha)
            if identity in seen:
                continue
            seen.add(identity)
            # Case folding can expand characters; map the matching offset back.
            folded_offset = text.casefold().find(query)
            offset, consumed = 0, 0
            for offset, character in enumerate(text):
                if consumed >= folded_offset:
                    break
                consumed += len(character.casefold())
            snippet = text[max(0, offset - 70):max(0, offset - 70) + 300]
            row = {'document_id': document_id, 'sha256': sha, 'snippet': snippet}
            if url:
                row.update(file_id=file_id, url=url)
            results.append(row)
        return {'state': 'ready', 'results': results}
    except (OSError, ValueError, TypeError, sqlite3.Error):
        return unavailable
    finally:
        if connection is not None:
            connection.close()
