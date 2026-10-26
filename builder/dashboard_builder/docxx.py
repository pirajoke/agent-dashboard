"""Read-only, owner-only DOCXX monitor. No model calls, network or source writes."""
from __future__ import annotations
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import sqlite3
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit

MAX_JSON = 4 * 1024 * 1024
STALE_AFTER = 900
ID = re.compile(r'^[A-Za-z0-9_-]{10,160}$')
LABELS = {
    'verified': 'Проверено в Google Drive', 'copied': 'Сохранено; см. проверку облака',
    'already_present': 'Документ уже есть', 'settling': 'Ожидает синхронизации',
    'pending': 'Ожидает проверки', 'awaiting_verification': 'Ожидает проверки облака',
    'duplicate_found': 'Совпадение; входящий файл сохранён', 'needs_review': 'Нужен разбор',
    'error': 'Ошибка; проверьте документ', 'retained': 'Оставлен на месте',
}
REASONS = {
    'catalog_unavailable': 'Каталог временно недоступен. Повторная проверка — в следующем проходе.',
    'over_100MB': 'Размер превышает предел автоматической обработки: 100 МБ.',
    'unrecognized_or_conflicting_content': 'Не удалось однозначно определить назначение документа.',
    'extraction_failed': 'Не удалось прочитать текст. Нужен разбор.',
    'shared_or_not_owned': 'Общий доступ или другой владелец. Автоматическое перемещение отключено.',
    'exact_duplicate_source_retained': 'Совпадение найдено. Входящий файл сохранён вместе с историей и доступами.',
    'bundle_contains_exact_duplicates_retained': 'В комплекте есть совпадения. Папка сохранена целиком.',
}
GMAIL_ERRORS = {
    'auth_required': 'Нужно заново подключить Gmail только для чтения.',
    'account_mismatch': 'Аккаунт почтового входа не совпал с настройкой.',
    'gmail_unavailable': 'Gmail временно недоступен. Вложения сохранены для повторной попытки.',
    'catalog_unavailable': 'Облачный каталог недоступен. Загруженные вложения сохранены.',
    'delivery_pending': 'Вложения ожидают независимой проверки в Google Drive.',
    'history_expired': 'История Gmail устарела. Нужна проверка непрочитанного периода.',
    'processing_failed': 'Вложение пока не распределено. Нужна проверка.',
    'staging_failed': 'Вложение пока не сохранено локально. Оригинал остаётся в Gmail.',
    'message_not_found': 'Одно из писем недоступно. Остальные вложения продолжают обрабатываться.',
    'access_unavailable': 'Нет доступа к почтовому входу.',
    'rate_limited': 'Почтовый сервис временно ограничил запросы.',
    'import_failed': 'Вложение пока не передано в обработку. Нужна проверка.',
}


def state_path(home):
    return Path(home) / 'Library/Application Support/DOCXX-intake'


def _read(path):
    # No arbitrary path supplied by HTTP. Reject source-file links and nonregular files.
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_JSON:
            raise ValueError('invalid_state_file')
        data = stream.read(MAX_JSON + 1)
        if len(data) > MAX_JSON: raise ValueError('oversized_state')
    value = json.loads(data)
    if not isinstance(value, dict): raise ValueError('invalid_state')
    return value


def _date(value):
    try:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            result = float(value)
        else:
            parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
            if parsed.tzinfo is None: return None
            result = parsed.timestamp()
        return result if math.isfinite(result) else None
    except (ValueError, TypeError, OverflowError):
        return None


def _stamp(value):
    value = _date(value)
    try:
        return datetime.fromtimestamp(value, timezone.utc).isoformat() if value is not None else None
    except (ValueError, OverflowError, OSError):
        return None


def _count(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _text(value, limit=220):
    return ''.join(c for c in str(value or '') if c.isprintable())[:limit]


def _basename(value):
    return _text(str(value or '').replace('\\', '/').rsplit('/', 1)[-1])


def _relative(value):
    # Strip machine/account path; unexpected paths are never exposed.
    value = str(value or '')
    return _text(value.split('/DOCXXx/', 1)[1], 600) if '/DOCXXx/' in value else ''


def _local_path(value):
    # Private: the file's place inside the library on this Mac, for owner sorting only; never served.
    value = str(value or '')
    return value if value.startswith('/') and '/DOCXXx/' in value and '\x00' not in value else None


def _drive_link(value, folder=False):
    if not isinstance(value, str) or not ID.fullmatch(value): return None
    return 'https://drive.google.com/' + ('drive/folders/' + value if folder else 'file/d/' + value + '/view')


def _safe_link(value):
    try:
        u = urlsplit(value)
        if u.scheme != 'https' or u.hostname not in ('drive.google.com','docs.google.com') or u.username or u.password or u.port:
            return None
        if u.query or u.fragment: return None
        if not re.fullmatch(r'/(?:drive/folders|file/d|document/d|spreadsheets/d)/[A-Za-z0-9_-]{10,160}(?:/(?:view|edit))?', u.path):
            return None
        return value
    except (TypeError, ValueError, AttributeError):
        return None


def _busy(path):
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
        with os.fdopen(fd, 'rb') as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode): return None
            try:
                fcntl.flock(stream, fcntl.LOCK_SH | fcntl.LOCK_NB)
            except BlockingIOError:
                return True
            fcntl.flock(stream, fcntl.LOCK_UN)
            return False
    except OSError:
        return None


def _gmail_status(directory, now):
    # This file is produced only by the private local intake worker. A connected
    # chat connector alone never proves a background monitor is installed.
    empty = {'state': 'manual', 'automatic': False, 'checked_at': None,
             'pending': None, 'error': None}
    try:
        saved = _read(directory / 'gmail-status.json')
    except FileNotFoundError:
        return empty
    except (OSError, ValueError, TypeError):
        return {**empty, 'state': 'unavailable'}
    state = saved.get('state')
    if (type(saved.get('schema_version')) is not int or saved['schema_version'] != 1
            or saved.get('producer') != 'docxx-gmail-intake'
            or state not in ('manual', 'paused', 'ready', 'processing', 'error')):
        return {**empty, 'state': 'unavailable'}
    checked = _date(saved.get('checked_at'))
    fresh = checked is not None and 0 <= now - checked <= STALE_AFTER
    enabled = saved.get('monitoring_enabled') is True
    if state in ('ready', 'processing', 'error'):
        if not enabled:
            return empty
        if not fresh:
            return {**empty, 'state': 'stale', 'checked_at': _stamp(checked)}
    error = None
    if state == 'error':
        code = saved.get('error_code')
        error = GMAIL_ERRORS.get(code) if isinstance(code, str) else None
        error = error or 'Проверка почты завершилась ошибкой. Нужна проверка подключения.'
    if (state == 'error' and saved.get('error_code') == 'message_not_found'
            and _count(saved.get('pending')) == 0 and _count(saved.get('known_pending')) == 0
            and saved.get('discovery_pending') is False):
        state = 'warning'
    return {'state': state, 'automatic': enabled and fresh and state in ('ready', 'processing', 'warning'),
            'checked_at': _stamp(checked),
            'pending': _count(saved.get('pending')) if fresh and enabled and state in ('ready', 'processing', 'error', 'warning') else None,
            'error': error}


OPERATION_LABELS = {
    'queued': 'В очереди', 'processing': 'Чтение и проверка', 'applying': 'Изменение документа',
    'awaiting_cloud': 'Ожидает проверки облака', 'verified': 'Результат проверен в облаке',
    'needs_review': 'Нужен разбор', 'failed': 'Ошибка обработки', 'uncertain': 'Результат требует проверки',
    'metadata_verified': 'Перемещение проверено',
}


def _operations(directory, now):
    empty = {'state': 'unavailable', 'counts': {}, 'records': [], 'checked_at': None}
    try:
        saved = _read(directory / 'operations-status.json')
        counts, records = saved.get('counts'), saved.get('records')
        if (type(saved.get('schema_version')) is not int or saved['schema_version'] != 1
                or saved.get('producer') != 'docxx-operations'
                or not isinstance(counts, dict) or not isinstance(records, list)
                or any(key not in OPERATION_LABELS or _count(value) is None for key, value in counts.items())):
            return empty
        checked = _date(saved.get('checked_at'))
        fresh = checked is not None and 0 <= now - checked <= STALE_AFTER
        projected = []
        for row in records[:100]:
            if not isinstance(row, dict):
                continue
            ident, state = row.get('id'), row.get('state')
            if (not isinstance(ident, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,160}', ident)
                    or not isinstance(state, str) or state not in OPERATION_LABELS):
                continue
            item = {'id': ident, 'state': state, 'label': OPERATION_LABELS[state]}
            sha, size = row.get('sha256'), row.get('size')
            if isinstance(sha, str) and re.fullmatch(r'[0-9a-f]{64}', sha): item['sha256'] = sha
            if type(size) is int and 0 < size <= 100 * 1024 * 1024: item['size'] = size
            names, kinds = row.get('source_names'), row.get('source_kinds')
            item['source_names'] = [_basename(name) for name in names[:8] if isinstance(name, str)] if isinstance(names, list) else []
            item['source_kinds'] = list(dict.fromkeys(k for k in kinds[:20] if isinstance(k, str) and k in ('icloud', 'drive', 'gmail', 'manual'))) if isinstance(kinds, list) else []
            destination = row.get('destination')
            if (isinstance(destination, str) and 0 < len(destination) <= 600
                    and not destination.startswith(('/', '\\')) and '\\' not in destination
                    and ':' not in destination and all(p not in ('', '.', '..') for p in destination.split('/'))
                    and all(c.isprintable() for c in destination)):
                item['destination'] = destination
            if state == 'metadata_verified':
                if row.get('verification') != 'metadata':
                    continue
                item['verification'] = 'metadata'
            if state in ('verified', 'metadata_verified'):
                url = _drive_link(row.get('cloud_file_id'))
                if url: item.update(cloud_file_id=row['cloud_file_id'], url=url)
            for key in ('checked_at', 'at'):
                stamp = _stamp(row.get(key))
                if stamp: item[key] = stamp
            projected.append(item)
        return {'state': 'ready' if fresh else 'stale', 'counts': counts,
                'records': projected, 'checked_at': _stamp(checked)}
    except (OSError, ValueError, TypeError):
        return empty


def _record(row, source, key, historical=False):
    if not isinstance(row, dict): return None
    status = row.get('status')
    if status in ('moving', 'pending_cloud'):
        status = 'awaiting_verification'
    elif status == 'planned':
        status = 'pending'
    if not isinstance(status, str) or status not in LABELS: status = 'needs_review'
    dest = row.get('destination')
    title = _basename(row.get('target_name') or dest or row.get('source')) or 'Документ без названия'
    reason = REASONS.get(row.get('reason')) if isinstance(row.get('reason'), str) else None
    if not reason and row.get('reason'): reason = 'Подробности — в статусе обработки на Google Drive.'
    final = row.get('finalization') if isinstance(row.get('finalization'), dict) else {}
    if final.get('status') == 'pending':
        status = 'awaiting_verification'
        reason = 'Входящий оригинал сохранён: независимая проверка облака ещё не завершена.'
    if row.get('rename_error') or row.get('verification_error'):
        status = 'needs_review'
        reason = 'Перемещение или переименование требует проверки. Смотрите журнал обработки.'
    ident = row.get('id')
    canonical = _safe_link(row.get('canonical_url', ''))
    category = _relative(dest)
    return {'key': hashlib.sha256((source + str(key)).encode()).hexdigest()[:20],
            'name': title, 'original_name': _basename(row.get('source')), 'destination': category,
            'source': source, 'status': status, 'label': LABELS[status], 'reason': reason,
            'at': _stamp(row.get('at') or row.get('processed_at')),
            'url': _drive_link(ident, row.get('kind') == 'folder'), 'canonical_url': canonical,
            'historical': historical, 'kind': 'folder' if row.get('kind') == 'folder' else 'file',
            '_path': _local_path(dest or row.get('path'))}


MAX_DATABASE = 512 * 1024 * 1024
MAX_ENRICHMENTS = 100
MAX_EXTRACTION = 12000


def _gmail_source_link(value):
    for key in ('thread_id', 'message_id'):
        ident = value.get(key)
        if isinstance(ident, str) and re.fullmatch(r'[0-9a-fA-F]{16,32}', ident):
            return 'https://mail.google.com/mail/#all/' + ident.lower()
    return None


def _ticket_metadata(text):
    # A narrow known template, never a generic OCR excerpt. Credentials, names
    # and arbitrary profile labels must never enter this owner-facing payload.
    if not isinstance(text, str) or not re.search(
            r'^[ \t]*Profil[ \t]+Public-Mediatheque-Ormesson[ \t]*$', text, re.MULTILINE):
        return {}
    dates = re.findall(
        r"Dates\s+de\s+validité\s+Valide\s+à\s+partir\s+du\s+(\d{2}/\d{2}/\d{4})\s+à\s+(\d{2}:\d{2})"
        r"\s+jusqu['’]au\s+(\d{2}/\d{2}/\d{4})\s+à\s+(\d{2}:\d{2})", text)
    if len(dates) != 1:
        return {}
    try:
        start, end = (datetime.strptime(' '.join(parts), '%d/%m/%Y %H:%M')
                      for parts in (dates[0][:2], dates[0][2:]))
        if end < start:
            return {}
    except ValueError:
        return {}
    return {'name': 'Ticket d’accès aux ordinateurs — Médiathèque Ormesson',
            'description': 'Талон доступа к компьютерам медиатеки Ormesson. Данные для входа находятся в оригинале документа.',
            'valid_from': start.date().isoformat(), 'valid_until': end.date().isoformat()}


def _gmail_enrichments(directory, entries):
    """Bounded optional metadata from the existing private journal, read-only."""
    identities = []
    for value in reversed(list(entries.values())):
        if not isinstance(value, dict):
            continue
        sha, size = value.get('sha256'), value.get('size')
        if (isinstance(sha, str) and re.fullmatch(r'[0-9a-f]{64}', sha)
                and type(size) is int and 0 < size <= 100 * 1024 * 1024
                and (sha, size) not in identities):
            identities.append((sha, size))
        if len(identities) >= MAX_ENRICHMENTS:
            break
    if not identities:
        return {}
    connection = None
    try:
        directory = Path(directory).absolute()
        if directory.is_symlink():
            return {}
        database = directory / 'operations.sqlite3'
        def snapshots():
            result = {}
            for suffix in ('', '-wal', '-shm', '-journal'):
                path = Path(str(database) + suffix)
                try:
                    info = path.lstat()
                except FileNotFoundError:
                    if not suffix:
                        raise
                    continue
                if (not stat.S_ISREG(info.st_mode) or info.st_size > MAX_DATABASE
                        or (not suffix and not info.st_size)):
                    raise ValueError('invalid_database')
                result[suffix] = (info.st_dev, info.st_ino)
            return result
        before = snapshots()
        connection = sqlite3.connect(database.as_uri() + '?mode=ro', uri=True, timeout=1)
        after = snapshots()
        if before != after:
            return {}
        connection.execute('PRAGMA query_only=ON')
        connection.execute('PRAGMA trusted_schema=OFF')
        deadline = time.monotonic() + 2
        connection.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
        placeholders = ','.join('(?,?)' for _ in identities)
        query = ("WITH wanted(sha256,size) AS (VALUES " + placeholders + ") "
                 "SELECT o.sha256,o.size,MIN(o.created_at),"
                 "(SELECT substr(e.text,1,?) FROM extractions e WHERE e.sha256=o.sha256 "
                 "ORDER BY e.created_at DESC,e.extractor_id LIMIT 1) "
                 "FROM operations o JOIN wanted w ON w.sha256=o.sha256 AND w.size=o.size "
                 "GROUP BY o.sha256,o.size LIMIT ?")
        parameters = [part for identity in identities for part in identity] + [MAX_EXTRACTION, MAX_ENRICHMENTS]
        enriched = {}
        for sha, size, created, text in connection.execute(query, parameters):
            metadata = _ticket_metadata(text)
            stamp = _stamp(created)
            if stamp:
                metadata.update(at=stamp, date_kind='added')
            enriched[(sha, size)] = metadata
        if snapshots() != after:
            return {}
        return enriched
    except (OSError, ValueError, TypeError, sqlite3.Error):
        return {}
    finally:
        if connection is not None:
            connection.close()


def _gmail_records(directory):
    """Project safe document metadata and validated source links, never raw mail bodies or credentials."""
    saved = _read(directory / 'gmail-journal.json')
    entries = saved.get('attachments')
    if saved.get('schema_version') != 1 or not isinstance(entries, dict) or len(entries) > 20000:
        raise ValueError('invalid_gmail_journal')
    enrichments = _gmail_enrichments(directory, entries)
    merged = {}
    for key, value in entries.items():
        if not isinstance(value, dict): continue
        state = value.get('state')
        review = value.get('needs_review') is True or state == 'review'
        status = ('needs_review' if review else 'verified' if state == 'delivered'
                  else 'awaiting_verification' if state == 'pending' else 'pending')
        data = {'source': value.get('name'), 'destination': value.get('destination'),
                'status': status, 'id': value.get('cloud_file_id') if state == 'delivered' else None,
                'at': value.get('delivered_at') or value.get('attempted_at')}
        if review: data['reason'] = 'unrecognized_or_conflicting_content'
        row = _record(data, 'gmail', key, historical=state == 'delivered' and not review)
        source_url = _gmail_source_link(value)
        if source_url: row['source_url'] = source_url
        sha, size = value.get('sha256'), value.get('size')
        if isinstance(sha, str) and type(size) is int:
            if re.fullmatch(r'[0-9a-f]{64}', sha):
                row['_sha'] = (sha, size)  # Private: lets the folder suggester read the saved text.
            metadata = enrichments.get((sha, size), {})
            row.update({k: v for k, v in metadata.items() if k not in ('at', 'date_kind')})
            if not row['at'] and metadata.get('at'):
                row.update(at=metadata['at'], date_kind='added')
        error = value.get('error_code')
        if isinstance(error, str) and error in GMAIL_ERRORS: row['reason'] = GMAIL_ERRORS[error]
        # Two original attachments may belong to one explicitly reviewed merge.
        identity = row['url'] or row['destination'] or row['key']
        previous = merged.get(identity)
        if previous and previous['status'] == row['status']:
            names = sorted(set(previous['original_name'].split(' + ') + [row['original_name']]))
            previous['original_name'] = _text(' + '.join(names))
        else:
            merged[identity] = row
    return list(merged.values())


def _apply_decisions(rows, decisions):
    """Mark's own sorting from the site (docxx_actions) settles a «Нужен разбор» row."""
    settled = 0
    for row in rows.values():
        decision = decisions.get(row['key']) if isinstance(decisions, dict) else None
        if not isinstance(decision, dict) or decision.get('action') not in ('move', 'archive', 'keep', 'trash'):
            continue
        if row['status'] != 'needs_review':
            continue
        moved = decision['action'] != 'keep'
        trashed = decision['action'] == 'trash'
        row.update(status='sorted', label='В корзине' if trashed else 'Разобрано', historical=False,
                   decision=decision['action'],
                   reason='Ты убрал документ в корзину. «Вернуть как было» достанет его обратно.' if trashed
                   else 'Ты переложил документ сюда.' if moved else 'Ты решил оставить документ как есть.')
        if moved and isinstance(decision.get('to'), str):
            row['destination'] = _text(decision['to'], 600)
        settled += 1
    return settled


def _apply_suggestions(rows, suggestions):
    """The Mac mini's folder guess from the document's content (docxx_suggest.py), for rows still open."""
    if not isinstance(suggestions, dict):
        return
    for row in rows.values():
        guess = suggestions.get(row['key'])
        if row['status'] != 'needs_review' or not isinstance(guess, dict) or guess.get('name') != row['name']:
            continue
        why = _text(guess.get('why'), 200)
        if guess.get('junk') is True:
            row['suggest'] = {'junk': True, 'why': why}
        elif isinstance(guess.get('folder'), str) and guess['folder']:
            row['suggest'] = {'folder': _text(guess['folder'], 300), 'why': why}
        elif guess.get('folder') is None:
            row['suggest'] = {'folder': None, 'why': why}


def docxx_projection(directory, *, owner=False, now=None, decisions=None, include_paths=False, suggestions=None):
    if not owner:
        return {'state': 'owner_required'}  # Do not even stat private sources.
    directory = Path(directory)
    now = time.time() if now is None else now
    try:
        if directory.is_symlink(): raise ValueError('symlink_state')
        status = _read(directory / 'status.json')
    except (OSError, ValueError, TypeError):
        return {'state': 'unavailable', 'message': 'Статус Mini недоступен.', 'records': []}
    checked = _date(status.get('checked_at'))
    stale = checked is None or not 0 <= now - checked <= STALE_AFTER
    busy = _busy(directory / 'runner.lock')
    ingress = status.get('drive_ingress') if isinstance(status.get('drive_ingress'), dict) else {}
    catalog = status.get('catalog') if isinstance(status.get('catalog'), dict) else {}
    rows, warnings = {}, []
    for filename, source in (('journal.json','icloud'), ('drive-ingress-journal.json','drive')):
        try:
            journal = _read(directory / filename)
            if len(journal) > 20000: raise ValueError('journal_limit')
            for key, value in journal.items():
                if source == 'icloud' and isinstance(value, dict) and '/gmail-staging/' in str(value.get('source', '')).replace('\\', '/'):
                    continue  # Gmail's dedicated journal is authoritative for its cloud receipt.
                row = _record(value, source, key, True)
                if row: rows[row['key']] = row
        except (OSError, ValueError, TypeError):
            warnings.append('История ' + ('iCloud' if source == 'icloud' else 'Google Drive') + ' недоступна.')
    try:
        for row in _gmail_records(directory): rows[row['key']] = row
    except FileNotFoundError: pass  # Optional until Gmail is connected.
    except (OSError, ValueError, TypeError): warnings.append('История вложений Gmail недоступна.')
    current = []
    queue_known = True
    for values, source in ((status.get('results'), 'icloud'), (ingress.get('results'),'drive'), (status.get('review_pending'),'review')):
        if not isinstance(values, list):
            queue_known = False
            continue
        if len(values) > 1000: queue_known = False
        for index, value in enumerate(values[:1000]):
            if not isinstance(value, dict):
                queue_known = False
                continue
            if not isinstance(value.get('status'), str) or value['status'] not in {*LABELS, 'moving', 'pending_cloud', 'planned'}:
                queue_known = False
            row = _record(value, source, value.get('id') or value.get('source') or index)
            if row:
                if ('/gmail-staging/' in str(value.get('source', '')).replace('\\', '/') and
                        row['destination'] and any(old['source'] == 'gmail' and
                            old['destination'] == row['destination'] for old in rows.values())):
                    continue  # Keep dedicated Gmail review/receipt metadata when available.
                current.append(row)
                # Latest snapshot supersedes history of the same source or destination.
                for old_key in list(rows):
                    old = rows[old_key]
                    if (row['url'] and old['url'] == row['url']) or (row['destination'] and old['destination'] == row['destination']) or (row['original_name'] and old['original_name'] == row['original_name'] and source == old['source']):
                        del rows[old_key]
                rows[row['key']] = row
    # Runner may include the same document in results and review_pending.
    # Count the latest visible identity once, just as the operation list does.
    settled = _apply_decisions(rows, decisions)
    _apply_suggestions(rows, suggestions)
    current = [row for row in rows.values() if not row['historical']]
    issues = {'needs_review','error','duplicate_found','retained','awaiting_verification'}
    review = sum(row['status'] in issues for row in current)
    pending_icloud = sum(row['source'] == 'icloud' and row['status'] in ('settling','pending','awaiting_verification') for row in current)
    drive_pending = _count(ingress.get('pending'))
    pending = pending_icloud + drive_pending if queue_known and drive_pending is not None else None
    if not queue_known: warnings.append('Неполные данные очереди.')
    gmail = _gmail_status(directory, now)
    operations = _operations(directory, now)
    unified_attention, unified_pending = False, False
    health = None
    if 'health' in status:
        saved_health = status['health']
        health_state = saved_health.get('state') if isinstance(saved_health, dict) else None
        if health_state not in ('ready', 'processing', 'degraded', 'blocked', 'stale'):
            health_state = 'unavailable'
        health = {'state': health_state}
        unified_attention = health_state in ('degraded', 'blocked', 'stale', 'unavailable')
        unified_pending = health_state == 'processing'
    if operations['state'] == 'ready':
        counts = operations['counts']
        unified_attention = unified_attention or any(counts.get(key, 0) > 0 for key in ('needs_review', 'failed', 'uncertain'))
        unified_pending = unified_pending or any(counts.get(key, 0) > 0 for key in ('queued', 'processing', 'applying', 'awaiting_cloud'))
    if unified_attention: warnings.append('В общей обработке есть вопросы для проверки. Откройте общую историю.')
    elif unified_pending: warnings.append('В общей очереди остаются незавершённые операции.')
    isolated_gmail = gmail['state'] == 'warning'
    if gmail.get('error'): warnings.append(gmail['error'])
    if gmail['state'] == 'stale': warnings.append('Статус почтового входа устарел.')
    error = (status.get('error') or not queue_known or unified_attention or (status.get('phase') == 'needs_review' and not isolated_gmail and not (settled and not review))
             or catalog.get('status') != 'ready' or ingress.get('status') in ('error','awaiting_verification')
             or gmail['state'] in ('error', 'stale', 'unavailable'))
    if catalog.get('status') == 'error': warnings.append('Облачный каталог временно недоступен. Входящие файлы сохранены.')
    if ingress.get('status') == 'error': warnings.append('Последняя проверка Google Drive завершилась ошибкой.')
    if isinstance(status.get('status_view'), dict) and status['status_view'].get('status') == 'error': warnings.append('Обновление текстового статуса в Google Drive задерживается.')
    if status.get('error'): warnings.append('Последний проход завершился ошибкой. Смотрите журнал обработки.')
    state = 'stale' if stale else 'processing' if busy else 'attention' if error or review else 'waiting' if unified_pending or pending or pending is None else 'ready'
    if status.get('phase') not in ('ready','needs_review') and not stale and not busy: state = 'unavailable'
    if busy is None: warnings.append('Не удалось проверить, выполняется ли проход прямо сейчас.')
    links = {}
    try:
        cfg = _read(directory / 'config.json')
        root_id = cfg.get('cloud_verifier', {}).get('root_id')
        root_url = _drive_link(root_id, True)
        if root_url: links['library'] = root_url
    except (OSError, ValueError, TypeError, AttributeError): pass
    try:
        saved = _read(directory / 'dashboard-links.json')
        for key in ('guide','review','catalog','status'):
            link = _safe_link(saved.get(key,''))
            if link: links[key] = link
    except (OSError, ValueError, TypeError): pass
    records = sorted(rows.values(), key=lambda r:(not r['historical'], r['at'] or ''), reverse=True)
    for row in records:
        path, sha = row.pop('_path', None), row.pop('_sha', None)
        if include_paths and path:
            row['_path'] = path
        if include_paths and sha:
            row['_sha'] = sha
    return {'state': state, 'checked_at': _stamp(checked), 'observed_at': _stamp(now),
            'busy': busy, 'scan_started_at': _stamp(status.get('scan_started_at')),
            'stale_after_seconds': STALE_AFTER, 'scan_interval_seconds': 300,
            'model_calls': _count(status.get('model_calls')), 'catalog_count': _count(catalog.get('documents')),
            'catalog_state': catalog.get('status') if catalog.get('status') in ('ready','error','refreshing') else 'unknown',
            'pending': pending, 'review_count': review, 'records': records[:100],
            'records_total': len(records), 'warnings': warnings, 'links': links,
            'gmail': gmail, 'operations': operations, 'health': health}
