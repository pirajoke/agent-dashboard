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
    return {'state': state, 'automatic': enabled and fresh and state in ('ready', 'processing'),
            'checked_at': _stamp(checked),
            'pending': _count(saved.get('pending')) if fresh and enabled and state in ('ready', 'processing', 'error') else None,
            'error': error}


def _record(row, source, key, historical=False):
    if not isinstance(row, dict): return None
    status = row.get('status')
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
            'historical': historical, 'kind': 'folder' if row.get('kind') == 'folder' else 'file'}


def docxx_projection(directory, *, owner=False, now=None):
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
                row = _record(value, source, key, True)
                if row: rows[row['key']] = row
        except (OSError, ValueError, TypeError):
            warnings.append('История ' + ('iCloud' if source == 'icloud' else 'Google Drive') + ' недоступна.')
    current = []
    for values, source in ((status.get('results', []), 'icloud'), (ingress.get('results', []),'drive'), (status.get('review_pending', []),'review')):
        if not isinstance(values, list):
            warnings.append('Неполные данные очереди.'); continue
        for index, value in enumerate(values[:1000]):
            if not isinstance(value, dict): continue
            row = _record(value, source, value.get('id') or value.get('source') or index)
            if row:
                current.append(row)
                # Latest snapshot supersedes history of the same source or destination.
                for old_key in list(rows):
                    old = rows[old_key]
                    if (row['url'] and old['url'] == row['url']) or (row['destination'] and old['destination'] == row['destination']) or (row['original_name'] and old['original_name'] == row['original_name'] and source == old['source']):
                        del rows[old_key]
                rows[row['key']] = row
    issues = {'needs_review','error','duplicate_found','retained','awaiting_verification'}
    review = sum(row['status'] in issues for row in current)
    pending_icloud = sum(row['source'] == 'icloud' and row['status'] in ('settling','pending','awaiting_verification') for row in current)
    drive_pending = _count(ingress.get('pending'))
    pending = pending_icloud + drive_pending if drive_pending is not None else None
    error = status.get('error') or status.get('phase') == 'needs_review' or catalog.get('status') == 'error' or ingress.get('status') in ('error','awaiting_verification')
    if catalog.get('status') == 'error': warnings.append('Облачный каталог временно недоступен. Входящие файлы сохранены.')
    if ingress.get('status') == 'error': warnings.append('Последняя проверка Google Drive завершилась ошибкой.')
    if isinstance(status.get('status_view'), dict) and status['status_view'].get('status') == 'error': warnings.append('Обновление текстового статуса в Google Drive задерживается.')
    if status.get('error'): warnings.append('Последний проход завершился ошибкой. Смотрите журнал обработки.')
    state = 'stale' if stale else 'processing' if busy else 'attention' if error or review else 'waiting' if pending or pending is None else 'ready'
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
    return {'state': state, 'checked_at': _stamp(checked), 'observed_at': _stamp(now),
            'busy': busy, 'scan_started_at': _stamp(status.get('scan_started_at')),
            'stale_after_seconds': STALE_AFTER, 'scan_interval_seconds': 300,
            'model_calls': _count(status.get('model_calls')), 'catalog_count': _count(catalog.get('documents')),
            'catalog_state': catalog.get('status') if catalog.get('status') in ('ready','error','refreshing') else 'unknown',
            'pending': pending, 'review_count': review, 'records': records[:100],
            'records_total': len(records), 'warnings': warnings, 'links': links,
            'gmail': _gmail_status(directory, now)}
