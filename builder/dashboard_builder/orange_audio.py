"""Orange Audio meetings: owner-only projection of a private catalog written on the Mac mini.

Mark 2026-11-23: «функционал гранолы … в командный центр … автоматически загружаться ещё и информация
из своей личной гранолы. Назовём её Orange Audio».

The catalog (~/.agent-bridge/orange-audio/catalog.json) is built by orange_catalog.py from the
owner's HQ repository: his own call recorder (Orange Audio) plus Granola notes, one entry per meeting.
This module only reads and validates it. No networking, no models, no writes. Without the owner check
it returns nothing but the state, so the public page never carries meeting content.
"""
from __future__ import annotations

import json
import os
import re
import stat
from datetime import datetime, timezone
from pathlib import Path

MAX_CATALOG = 64 * 1024 * 1024
MAX_MEETINGS = 600
RID = re.compile(r'^[a-f0-9]{32}$')
SOURCES = ('orange', 'granola')
STALE_AFTER_S = 3600


def default_path(home: Path) -> Path:
    return Path(os.environ.get('COMMAND_CENTER_ORANGE_CATALOG', str(home / '.agent-bridge' / 'orange-audio' / 'catalog.json')))


def _date(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def _str(value, limit):
    return value[:limit] if isinstance(value, str) else ''


def _turns(items):
    out = []
    if not isinstance(items, list):
        return out
    for item in items[:20000]:
        if isinstance(item, dict) and isinstance(item.get('text'), str):
            out.append({'t': _str(item.get('t'), 8), 'who': _str(item.get('who'), 80), 'text': item['text'][:4000]})
    return out


def _meeting(raw):
    if not isinstance(raw, dict) or not RID.fullmatch(str(raw.get('id', ''))) or not _date(raw.get('start')):
        return None
    sources = [s for s in raw.get('sources', []) if s in SOURCES] if isinstance(raw.get('sources'), list) else []
    transcripts = raw.get('transcripts') if isinstance(raw.get('transcripts'), dict) else {}
    duration = raw.get('duration_min')
    return {
        'id': raw['id'],
        'title': _str(raw.get('title'), 300) or 'Встреча',
        'start': _str(raw.get('start'), 40),
        'end': _str(raw.get('end'), 40) if _date(raw.get('end')) else '',
        'duration_min': duration if isinstance(duration, int) and 0 < duration < 24 * 60 else None,
        'primary': raw.get('primary') if raw.get('primary') in SOURCES else (sources[0] if sources else 'orange'),
        'sources': sources,
        'app': _str(raw.get('app'), 60),
        'people': [_str(p, 80) for p in raw.get('people', []) if isinstance(p, str)][:12] if isinstance(raw.get('people'), list) else [],
        'summary': _str(raw.get('summary'), 200_000),
        'transcripts': {s: _turns(transcripts.get(s)) for s in SOURCES if s in transcripts},
    }


def _load(path):
    path = Path(path)
    fd = os.open(str(path), os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_CATALOG:
            raise ValueError('oversized_or_nonregular')
        data = json.loads(stream.read(MAX_CATALOG + 1))
    if not isinstance(data, dict) or data.get('schema') != 1 or not _date(data.get('generated_at')) \
            or not isinstance(data.get('meetings'), list) or len(data['meetings']) > MAX_MEETINGS:
        raise ValueError('invalid_catalog')
    return data


def _preview(summary):
    for line in summary.splitlines():
        text = re.sub(r'^[#>\-*\s\[\]x]+', '', line).replace('**', '').strip()
        if text and not re.fullmatch(r'(итог|резюме|summary|договорённости|договоренности)\s*:?', text, re.I):
            return text[:180]
    return ''


def orange_audio_projection(path, owner=False, query='', meeting_id=None, now=None):
    if not owner:
        return {'state': 'owner_required', 'meetings': []}
    try:
        data = _load(path)
    except FileNotFoundError:
        return {'state': 'not_installed', 'meetings': []}
    except (OSError, ValueError, UnicodeError):
        return {'state': 'unavailable', 'meetings': []}
    state = data.get('state') if data.get('state') in ('ready', 'partial') else 'ready'
    current = now or datetime.now(timezone.utc)
    if (current - _date(data['generated_at'])).total_seconds() > STALE_AFTER_S:
        state = 'stale'
    meetings = [m for m in (_meeting(raw) for raw in data['meetings']) if m]
    sources = [{'source': s.get('source'), 'state': s.get('state')} for s in data.get('sources', [])
               if isinstance(s, dict) and s.get('source') in SOURCES and s.get('state') in ('observed', 'not_observed')]
    if meeting_id is not None:
        if isinstance(meeting_id, str) and RID.fullmatch(meeting_id):
            for m in meetings:
                if m['id'] == meeting_id:
                    return {'state': state, 'generated_at': data['generated_at'], 'meeting': m}
        return {'state': 'not_found', 'meetings': []}
    needle = (query or '')[:1000].casefold()

    def matches(m):
        if not needle:
            return True
        hay = [m['title'], m['summary'], ' '.join(m['people'])]
        hay += [t['text'] for turns in m['transcripts'].values() for t in turns]
        return needle in '\n'.join(hay).casefold()

    found = sorted((m for m in meetings if matches(m)), key=lambda m: m['start'], reverse=True)
    listed = [{k: m[k] for k in ('id', 'title', 'start', 'end', 'duration_min', 'primary', 'sources', 'app', 'people')}
              | {'preview': _preview(m['summary']), 'has_summary': bool(m['summary'])} for m in found[:300]]
    return {'state': state, 'generated_at': data['generated_at'], 'meetings': listed, 'total': len(found), 'sources': sources}
