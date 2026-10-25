"""Bounded private projection of canonical notes; no networking or source writes."""
from __future__ import annotations

import base64
import csv
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import unicodedata
from datetime import datetime, timezone
from urllib.parse import urlencode, urlsplit, parse_qs

MAX_NOTE = 2 * 1024 * 1024
MAX_CATALOG = 32 * 1024 * 1024
RID = re.compile(r'^[a-f0-9]{32}$')
SOURCES = ('plaud', 'krisp', 'granola', 'other', 'project-update')
ROOTS = ('10-Transcripts', '00-Inbox/plaud', '00-Inbox/krisp', '00-Inbox/granola',
         '90-Operations/project-update-webhook/logs')


def _now():
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def _date(value):
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError, AttributeError):
        return None


def _hash(data):
    return hashlib.sha256(data).hexdigest()


def _safe_path(path):
    path = Path(os.path.abspath(path))
    # macOS system aliases are not user-controlled source links.
    for alias, canonical in (('/var', '/private/var'), ('/tmp', '/private/tmp')):
        if str(path).startswith(alias + '/') and Path(alias).is_symlink() and str(Path(alias).resolve()) == canonical:
            path = Path(canonical) / path.relative_to(alias)
    for part in (path,) + tuple(path.parents):
        if part.is_symlink():
            raise ValueError('symlink_path')
    return path


def _read(path, limit):
    path = _safe_path(path)
    fd = os.open(str(path), os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise ValueError('oversized_or_nonregular')
        data = stream.read(limit + 1)
        if len(data) > limit:
            raise ValueError('oversized')
        return data, info


def _metadata(body):
    result = {}
    lines = body.splitlines()
    if not lines or lines[0].strip() != '---':
        return result
    for line in lines[1:100]:
        if line.strip() == '---':
            break
        match = re.match(r'^([A-Za-z_][\w-]*):\s*(.*?)\s*$', line)
        if match:
            key, value = match.groups()
            if value.startswith(('"', "'")) and value[-1:] == value[0]:
                value = value[1:-1]
            if value and not value.startswith(('[', '{', '|', '>')):
                result[key] = value
    return result


def _url_safe(value):
    if not isinstance(value, str) or len(value) > 8192 or any(ord(c) < 32 for c in value):
        return ''
    try:
        parsed = urlsplit(value)
        query = parse_qs(parsed.query, keep_blank_values=True)
        if parsed.scheme != 'obsidian' or parsed.netloc != 'open' or parsed.path not in ('', '/') or parsed.fragment:
            return ''
        if set(query) != {'vault', 'file'} or any(len(v) != 1 or not v[0] for v in query.values()):
            return ''
        for text in (query['vault'][0], query['file'][0]):
            if text.startswith(('/', '\\')) or '\\' in text or '..' in text.split('/') or any(ord(c) < 32 for c in text):
                return ''
        return value
    except (ValueError, TypeError):
        return ''


def build_catalog(vault, previous=None, now=None):
    stamp = now or _now()
    result = dict(schema=1, generated_at=stamp, state='ready', records=[], sources=[], issues=[],
                  history_scope={'updates_limit': 200, 'transcripts_limit': 2000})
    issues = set()
    try:
        vault = _safe_path(vault)
        if not vault.is_dir():
            raise ValueError('missing_vault')
    except (OSError, ValueError):
        result.update(state='unavailable', issues=['vault_unavailable'])
        return result
    old = previous.get('records', []) if isinstance(previous, dict) else []
    old = [r for r in old if isinstance(r, dict) and RID.fullmatch(str(r.get('id', '')))]
    old_paths = {r.get('relative_path'): r for r in old}
    old_hashes = {}
    for r in old:
        old_hashes.setdefault(r.get('sha256'), []).append(r)
    previous_roots = set(previous.get('source_roots', [])) if isinstance(previous, dict) else set()
    previous_roots.update(root for root in ROOTS if any(str(r.get('relative_path', '')).startswith(root + '/') for r in old))
    for root in previous_roots.intersection(ROOTS):
        try:
            if not _safe_path(vault / root).is_dir():
                raise ValueError('source_root_missing')
        except (OSError, ValueError):
            result.update(state='unavailable', issues=['previous_source_root_unavailable'])
            return result
    result['source_roots'] = []
    files = []
    for root in ROOTS:
        base = vault / root
        try:
            _safe_path(base)
            if not base.exists():
                continue
            if not base.is_dir():
                raise ValueError('source_not_directory')
            result['source_roots'].append(root)
            candidates = []
            def walk_error(_):
                issues.add('source_unreadable')
            for folder, dirs, names in os.walk(str(base), followlinks=False, onerror=walk_error):
                dirs[:] = sorted(d for d in dirs if not d.startswith('.') and not (Path(folder) / d).is_symlink())
                for name in sorted(names):
                    if name.startswith('.') or not name.lower().endswith('.md'):
                        continue
                    path = Path(folder) / name
                    try:
                        _safe_path(path)
                        info = path.stat()
                        if info.st_size > MAX_NOTE or not stat.S_ISREG(info.st_mode):
                            raise ValueError('source_invalid')
                        candidates.append((path, info.st_mtime))
                    except (OSError, ValueError):
                        issues.add('source_skipped')
            if root == ROOTS[-1]:
                candidates = sorted(candidates, key=lambda p: (p[1], str(p[0])), reverse=True)[:200]
            files.extend((p, root) for p, _ in candidates)
        except (OSError, ValueError):
            issues.add('source_unavailable')
    transcripts = 0
    identities = {}
    used_ids = set()
    for path, root in files:
        kind = 'update' if root == ROOTS[-1] else 'transcript'
        if kind == 'transcript' and transcripts >= 2000:
            issues.add('transcript_limit')
            continue
        try:
            raw, info = _read(path, MAX_NOTE)
            body = raw.decode('utf-8')
        except (OSError, ValueError, UnicodeError):
            issues.add('source_skipped')
            continue
        meta = _metadata(body)
        relative = path.relative_to(vault).as_posix()
        source = 'project-update' if kind == 'update' else meta.get('source', '').lower()
        if source not in SOURCES:
            source = next((s for s in SOURCES[:3] if s in relative.lower()), 'other')
        upstream = next((meta[k] for k in ('plaud_id', 'meeting_id', 'granola_id', 'writeback_id') if meta.get(k)), '')
        # Fallback journals reuse this marker; it is provenance, not an event ID.
        if source == 'project-update' and upstream == 'manual-fallback':
            upstream = ''
        digest = _hash(raw)
        identity = source + ':' + upstream if upstream else ''
        if identity and digest in identities.get(identity, {}):
            continue
        if identity:
            identifier = _hash(identity.encode())[:32]
            if identity in identities:
                issues.add('upstream_content_conflict')
                identifier = _hash((identity + ':' + relative).encode())[:32]
            # Preserve previous conflicting record identity where possible.
            prior = old_paths.get(relative)
            if prior and prior.get('source_id') == upstream and prior.get('source') == source:
                identifier = prior['id']
        elif relative in old_paths:
            identifier = old_paths[relative]['id']
        elif len(old_hashes.get(digest, [])) == 1:
            identifier = old_hashes[digest][0]['id']
        else:
            identifier = _hash(relative.encode())[:32]
        if identifier in used_ids:
            identifier = _hash((identifier + ':' + relative).encode())[:32]
        used_ids.add(identifier)
        if identity:
            identities.setdefault(identity, {})[digest] = identifier
        date = meta.get('date', meta.get('created_at', ''))
        if not _date(date):
            match = re.search(r'(?<!\d)(\d{4}-\d{2}-\d{2})(?!\d)', path.stem)
            date = match.group(1) if match and _date(match.group(1)) else ''
        title = meta.get('title') or next((line[2:].strip() for line in body.splitlines() if line.startswith('# ')), path.stem)
        result['records'].append(dict(id=identifier, kind=kind, source=source, source_id=upstream,
            title=title, date=date, modified_at=datetime.fromtimestamp(info.st_mtime, timezone.utc).isoformat().replace('+00:00', 'Z'),
            project=meta.get('project', ''), relative_path=relative,
            obsidian_url='obsidian://open?' + urlencode({'vault': vault.name, 'file': relative[:-3]}),
            sha256=digest, body=body))
        if kind == 'transcript':
            transcripts += 1
    result['records'].sort(key=lambda r: (r['date'], r['modified_at'], r['id']), reverse=True)
    observed = {r['source'] for r in result['records']}
    result['sources'] = [{'source': s, 'state': 'observed' if s in observed else 'not_observed'} for s in SOURCES]
    result['issues'] = sorted(issues)
    if issues:
        result['state'] = 'partial' if result['records'] else 'unavailable'
    return result


def _valid_catalog(data):
    if not isinstance(data, dict) or data.get('schema') != 1 or data.get('state') not in ('ready', 'partial', 'unavailable') or not _date(data.get('generated_at')):
        return False
    if not isinstance(data.get('records'), list) or len(data['records']) > 2200:
        return False
    seen = set()
    for item in data['records']:
        if not isinstance(item, dict) or not RID.fullmatch(str(item.get('id', ''))) or item['id'] in seen:
            return False
        seen.add(item['id'])
        if item.get('kind') not in ('transcript', 'update') or item.get('source') not in SOURCES:
            return False
        if any(not isinstance(item.get(key), str) for key in ('body', 'title', 'date', 'modified_at', 'project', 'relative_path', 'source_id', 'sha256', 'obsidian_url')):
            return False
        if len(item['body'].encode()) > MAX_NOTE:
            return False
    return isinstance(data.get('sources'), list) and isinstance(data.get('issues'), list)


def _atomic(path, raw):
    path = _safe_path(path)
    fd, temporary = tempfile.mkstemp(prefix='.context-', dir=str(path.parent))
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        _safe_path(path)
        os.replace(temporary, str(path))
        directory_fd = os.open(str(path.parent), os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _destination(output, relative):
    relative = Path(relative)
    if relative.is_absolute() or '..' in relative.parts or not relative.parts or any(part.startswith('.') for part in relative.parts):
        raise ValueError('invalid_destination')
    return _safe_path(output / relative)


SUMMARY = '00 — Последние обновления.txt'
INDEX = '00 — Каталог.csv'


def _manifest_valid(manifest, output):
    if not isinstance(manifest, dict) or manifest.get('schema') != 1 or not isinstance(manifest.get('files'), dict) or not isinstance(manifest.get('records'), dict):
        raise ValueError('invalid_manifest')
    destinations = set()
    for identifier, relative in manifest['records'].items():
        if not RID.fullmatch(identifier) or not isinstance(relative, str):
            raise ValueError('invalid_manifest_identity')
        parts = Path(relative).parts
        if len(parts) != 3 or parts[0] not in ('Транскрипты', 'Обновления') or not relative.endswith('.txt'):
            raise ValueError('invalid_manifest_record_path')
        _destination(output, relative)
        key = unicodedata.normalize('NFC', relative).casefold()
        if key in destinations:
            raise ValueError('duplicate_manifest_destination')
        destinations.add(key)
        if relative not in manifest['files']:
            raise ValueError('missing_manifest_file')
    for relative, meta in manifest['files'].items():
        _destination(output, relative)
        if relative not in (INDEX, SUMMARY) and relative not in manifest['records'].values():
            raise ValueError('unmanaged_manifest_path')
        if not isinstance(meta, dict) or not re.fullmatch(r'[a-f0-9]{64}', str(meta.get('sha256', ''))):
            raise ValueError('invalid_manifest_hash')


def _json_bytes(data):
    return json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2).encode()


def _recover_export(output, state, intent_path):
    """Complete an exact durable intent; neither unknown nor owner-edited bytes are adopted."""
    intent = json.loads(_read(intent_path, MAX_CATALOG * 4)[0])
    if not isinstance(intent, dict) or intent.get('schema') != 1 or intent.get('output') != str(output) or not isinstance(intent.get('writes'), dict):
        raise ValueError('invalid_export_intent')
    manifest = intent.get('manifest')
    _manifest_valid(manifest, output)
    encoded = _json_bytes(manifest)
    current_state = _read(state, MAX_CATALOG)[0] if state.exists() else None
    current_hash = _hash(current_state) if current_state is not None else None
    if current_hash not in (intent.get('base_sha256'), _hash(encoded)):
        raise ValueError('manifest_changed_during_recovery')
    writes = []
    for relative, item in intent['writes'].items():
        path = _destination(output, relative)
        if not isinstance(item, dict) or relative not in manifest['files']:
            raise ValueError('invalid_intent_file')
        try:
            raw = base64.b64decode(item['data'], validate=True)
        except (KeyError, ValueError, TypeError):
            raise ValueError('invalid_intent_bytes')
        new_hash = _hash(raw)
        if new_hash != manifest['files'][relative]['sha256']:
            raise ValueError('invalid_intent_hash')
        current = _read(path, MAX_CATALOG)[0] if path.exists() else None
        actual_hash = _hash(current) if current is not None else None
        if actual_hash == new_hash:
            continue
        if actual_hash != item.get('before_sha256'):
            raise ValueError('recovery_destination_conflict')
        writes.append((path, raw, actual_hash))
    # Validate every file before mutating any; recheck immediately before each write.
    for path, raw, expected in writes:
        path.parent.mkdir(parents=True, exist_ok=True)
        current = _read(path, MAX_CATALOG)[0] if path.exists() else None
        if (_hash(current) if current is not None else None) != expected:
            raise ValueError('recovery_destination_changed')
        _atomic(path, raw)
    if current_state != encoded:
        _atomic(state, encoded)
    _safe_path(intent_path).unlink()
    return manifest


def _readable_name(record):
    title = unicodedata.normalize('NFC', record['title'])
    title = ''.join(' ' if unicodedata.category(c).startswith('C') or c in '/\\:*?"<>|' else c for c in title)
    title = re.sub(r'\s+', ' ', title).strip(' .')[:80].rstrip() or 'Без названия'
    while len(title.encode()) > 160:
        title = title[:-1]
    date = record['date'][:10] if _date(record['date']) else 'Без даты'
    return '{} — {} — {} — {}.txt'.format(date, title, record['source'], record['id'][:8])


def export_catalog(catalog, output, state):
    if not _valid_catalog(catalog):
        raise ValueError('invalid_catalog')
    if catalog['state'] == 'unavailable':
        return {'state': 'unavailable', 'written': 0}
    output, state = _safe_path(output), _safe_path(state)
    if not output.is_dir() or not state.parent.is_dir() or output == state.parent or output in state.parents:
        raise ValueError('missing_or_unsafe_roots')
    lock_path = _safe_path(state.with_name(state.name + '.lock'))
    intent_path = _safe_path(state.with_name(state.name + '.intent.json'))
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    with os.fdopen(fd, 'a') as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        initial = _read(state, MAX_CATALOG)[0] if state.exists() else None
        manifest = json.loads(initial) if initial is not None else {'schema': 1, 'files': {}, 'records': {}}
        _manifest_valid(manifest, output)
        if intent_path.exists():
            manifest = _recover_export(output, state, intent_path)
            initial = _read(state, MAX_CATALOG)[0]
        pending = {}
        records = dict(manifest['records'])
        csv_out = io.StringIO(newline='')
        writer = csv.writer(csv_out)
        writer.writerow(['ID', 'Тип', 'Источник', 'Дата записи', 'Название', 'Проект', 'Обновлено', 'Obsidian', 'Экспорт'])
        reason_codes = [x for x in catalog['issues'] if isinstance(x, str) and re.fullmatch(r'[a-z0-9_]{1,80}', x)]
        recent = ['Последние обновления', 'Наблюдение: ' + catalog['generated_at'],
                  'Статус: ' + catalog['state'], 'Причины: ' + (', '.join(reason_codes) or 'нет'),
                  'Область: последние 200 обновлений проектов; не более 2000 транскриптов.',
                  'Основная версия — Obsidian. Экспорт обновляется только из него.', '']
        def cell(text):
            return "'" + text if text.startswith(('=', '+', '-', '@', '\t', '\r')) else text
        for r in catalog['records']:
            uri = _url_safe(r['obsidian_url'])
            if not uri:
                raise ValueError('unsafe_obsidian_url')
            year = r['date'][:4] if _date(r['date']) else 'Без даты'
            relative = records.get(r['id']) or '/'.join(('Транскрипты' if r['kind'] == 'transcript' else 'Обновления', year, _readable_name(r)))
            _destination(output, relative)
            if relative in pending or any(identifier != r['id'] and unicodedata.normalize('NFC', value).casefold() == unicodedata.normalize('NFC', relative).casefold() for identifier, value in records.items()):
                raise ValueError('duplicate_export_destination')
            records[r['id']] = relative
            old_meta = manifest['files'].get(relative, {})
            content_key = _hash(json.dumps(r, ensure_ascii=False, sort_keys=True).encode())
            observed = old_meta.get('observed_at', catalog['generated_at']) if old_meta.get('content_key') == content_key else catalog['generated_at']
            text = '{}\nИсточник: {}\nДата записи: {}\nОбновлено: {}\nНаблюдение: {}\nObsidian: {}\n\n{}'.format(r['title'], r['source'], r['date'] or 'Не указана', r['modified_at'], observed, uri, r['body'])
            pending[relative] = (text.encode(), {'content_key': content_key, 'observed_at': observed})
            writer.writerow([cell(str(x)) for x in (r['id'], r['kind'], r['source'], r['date'], r['title'], r['project'], r['modified_at'], uri, relative)])
            if len(recent) < 107:
                recent.append('{} · {} · {}\n{}'.format(r['date'] or 'Без даты', r['title'], r['source'], uri))
        pending[INDEX] = (csv_out.getvalue().encode('utf-8-sig'), {})
        catalog_key = _hash((csv_out.getvalue() + catalog['state'] + ','.join(reason_codes)).encode())
        if manifest.get('catalog_key') == catalog_key:
            recent[1] = 'Наблюдение: ' + manifest.get('catalog_observed_at', catalog['generated_at'])
        pending[SUMMARY] = ('\n'.join(recent).encode(), {})
        writes = {}
        for relative, (raw, meta) in pending.items():
            path = _destination(output, relative)
            old = manifest['files'].get(relative)
            if path.exists():
                current = _read(path, MAX_CATALOG)[0]
                if not old or _hash(current) != old.get('sha256'):
                    raise ValueError('destination_conflict')
                if current == raw:
                    continue
            elif old:
                raise ValueError('managed_destination_missing')
            writes[relative] = {'data': base64.b64encode(raw).decode('ascii'), 'before_sha256': old['sha256'] if old else None}
        for relative, (raw, meta) in pending.items():
            manifest['files'][relative] = dict(meta, sha256=_hash(raw))
        manifest['records'] = records
        if manifest.get('catalog_key') != catalog_key:
            manifest['catalog_observed_at'] = catalog['generated_at']
        manifest['catalog_key'] = catalog_key
        _manifest_valid(manifest, output)
        encoded = _json_bytes(manifest)
        if initial != encoded or writes:
            intent = dict(schema=1, output=str(output), base_sha256=_hash(initial) if initial is not None else None,
                          manifest=manifest, writes=writes)
            raw_intent = _json_bytes(intent)
            if len(raw_intent) > MAX_CATALOG * 4:
                raise ValueError('intent_size_limit')
            _atomic(intent_path, raw_intent)
            _recover_export(output, state, intent_path)
        return {'state': catalog['state'], 'written': len(writes), 'records': len(catalog['records'])}


def _retold(catalog_path):
    """Russian retellings written next to the catalog by context_retell.py; empty when missing."""
    try:
        data = json.loads(_read(Path(catalog_path).with_name('retold.json'), MAX_CATALOG)[0])
    except (OSError, ValueError, UnicodeError, TypeError):
        return {}
    items = data.get('items') if isinstance(data, dict) else None
    return items if isinstance(items, dict) else {}


def context_library_projection(path, owner=False, query='', source='', kind='', record_id=None, now=None):
    if not owner:
        return {'state': 'owner_required', 'records': []}
    try:
        data = json.loads(_read(path, MAX_CATALOG)[0])
        if not _valid_catalog(data):
            raise ValueError('invalid_catalog')
    except (OSError, ValueError, UnicodeError):
        return {'state': 'unavailable', 'records': []}
    state = data['state']
    if state != 'unavailable' and ((_date(now or _now()) - _date(data['generated_at'])).total_seconds() > 3600):
        state = 'stale'
    safe_keys = ('id', 'kind', 'source', 'title', 'date', 'modified_at', 'project', 'sha256')
    retold = _retold(path)
    def public_record(r, detail=False):
        projected = {k: r[k] for k in safe_keys}
        projected['obsidian_url'] = _url_safe(r['obsidian_url'])
        plain = retold.get(r['id'])
        # A Russian retelling (context_retell.py) only while it matches the record's current text.
        if isinstance(plain, dict) and plain.get('sha256') == r['sha256'] and isinstance(plain.get('title'), str) and isinstance(plain.get('text'), str):
            projected['plain'] = {'title': plain['title'][:200], 'text': plain['text'][:1000]}
        if detail:
            projected['body'] = r['body']
        return projected
    if record_id is not None:
        if isinstance(record_id, str) and RID.fullmatch(record_id):
            for r in data['records']:
                if r['id'] == record_id:
                    return {'state': state, 'generated_at': data['generated_at'], 'record': public_record(r, True)}
        return {'state': 'not_found', 'records': []}
    needle = query[:1000].casefold()
    records = [r for r in data['records'] if (not source or r['source'] == source) and (not kind or r['kind'] == kind) and (not needle or needle in '\n'.join((r['title'], r['body'], r['project'])).casefold())]
    sources = [{'source': s['source'], 'state': s['state']} for s in data['sources'] if isinstance(s, dict) and s.get('source') in SOURCES and s.get('state') in ('observed', 'not_observed')]
    return dict(state=state, generated_at=data['generated_at'], records=[public_record(r) for r in records[:100]], total=len(records), sources=sources,
                history_scope={'updates_limit': 200, 'transcripts_limit': 2000})
