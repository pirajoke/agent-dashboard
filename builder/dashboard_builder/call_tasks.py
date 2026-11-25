"""Tasks from calls: owner-only projection of ~/.agent-bridge/call-tasks/tasks.json + ticks.

Mark 2026-11-25: «у меня создаются задачи из call, но я не вижу куда они уходят и как их посмотреть и увидеть
когда они сделаны. и в каком контексте».

tasks.json is written on the Mac mini by pirajoke/hq call-recorder/call_tasks.py from the private CRM cards
(the cards stay the source of truth). A tick here appends one line to marks.jsonl; call_tasks.py applies it to
the card («- [x]»), commits in the local CRM git and refreshes the Jarvis day plan. Until then the projection
shows the tick from marks.jsonl, so the page answers at once. Without the owner check only the state is
returned: the public page never carries call content.
"""
from __future__ import annotations

import fcntl
import json
import os
import re
import stat
from datetime import datetime, timezone
from pathlib import Path

MAX_FILE = 8 * 1024 * 1024
MAX_MARK_LINES = 2000
STALE_AFTER_S = 3600
STEP_ID = re.compile(r'^[a-f0-9]{12}$')
CARD = re.compile(r'^[\w.-]{1,200}\.md$')
MEETING_ID = re.compile(r'^[a-f0-9]{32}$')


def default_dir(home: Path) -> Path:
    return Path(os.environ.get('COMMAND_CENTER_CALL_TASKS_DIR', str(home / '.agent-bridge' / 'call-tasks')))


def _date(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def _s(value, limit):
    return value[:limit] if isinstance(value, str) else ''


def _read(path: Path, limit: int) -> bytes:
    fd = os.open(str(path), os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise ValueError('oversized_or_nonregular')
        return stream.read(limit + 1)


def _marks(folder: Path) -> dict:
    """Latest tick per step id that call_tasks.py may not have applied yet."""
    try:
        lines = _read(folder / 'marks.jsonl', MAX_FILE).decode('utf-8', 'replace').splitlines()[-MAX_MARK_LINES:]
    except (OSError, ValueError):
        return {}
    out = {}
    for line in lines:
        try:
            m = json.loads(line)
        except ValueError:
            continue
        if isinstance(m, dict) and isinstance(m.get('id'), str) and isinstance(m.get('done'), bool):
            out[m['id']] = m
    return out


def _call(raw, marks, generated):
    if not isinstance(raw, dict) or not CARD.fullmatch(str(raw.get('card', ''))):
        return None
    steps = []
    for s in raw.get('steps', [])[:60] if isinstance(raw.get('steps'), list) else []:
        if not isinstance(s, dict) or not STEP_ID.fullmatch(str(s.get('id', ''))) or not isinstance(s.get('text'), str):
            continue
        done, done_at, pending = bool(s.get('done')), _s(s.get('done_at'), 40), False
        mark = marks.get(s['id'])
        mark_at = _date(mark.get('at')) if mark else None
        if mark and mark_at and (not generated or mark_at > generated) and mark['done'] != done:
            done, pending = mark['done'], True
            done_at = _s(mark.get('at'), 40) if done else ''
        steps.append({'id': s['id'], 'text': s['text'][:600], 'done': done, 'done_at': done_at, 'pending': pending})
    others = [{'who': _s(o.get('who'), 120), 'text': _s(o.get('text'), 600), 'due': _s(o.get('due'), 80)}
              for o in (raw.get('others', [])[:40] if isinstance(raw.get('others'), list) else [])
              if isinstance(o, dict) and isinstance(o.get('text'), str)]
    duration = raw.get('duration_min')
    return {
        'card': raw['card'], 'call': raw['card'][:-3], 'title': _s(raw.get('title'), 300) or 'Звонок',
        'date': _s(raw.get('date'), 10), 'project': _s(raw.get('project'), 80),
        'people': [_s(p, 80) for p in raw.get('people', [])[:8] if isinstance(p, str)]
        if isinstance(raw.get('people'), list) else [],
        'meeting_id': raw.get('meeting_id') if MEETING_ID.fullmatch(str(raw.get('meeting_id', ''))) else '',
        'start': _s(raw.get('start'), 40) if _date(raw.get('start')) else '',
        'duration_min': duration if isinstance(duration, int) and 0 < duration < 24 * 60 else None,
        'steps': steps, 'others': others,
    }


def call_tasks_projection(folder, owner=False, now=None):
    if not owner:
        return {'state': 'owner_required', 'calls': []}
    folder = Path(folder)
    try:
        data = json.loads(_read(folder / 'tasks.json', MAX_FILE))
    except FileNotFoundError:
        return {'state': 'not_installed', 'calls': []}
    except (OSError, ValueError, UnicodeError):
        return {'state': 'unavailable', 'calls': []}
    generated = _date(data.get('generated_at')) if isinstance(data, dict) else None
    if not generated or data.get('schema') != 1 or not isinstance(data.get('calls'), list):
        return {'state': 'unavailable', 'calls': []}
    marks = _marks(folder)
    calls = [c for c in (_call(raw, marks, generated) for raw in data['calls'][:300]) if c]
    current = now or datetime.now(timezone.utc)
    state = 'stale' if (current - generated).total_seconds() > STALE_AFTER_S else 'ready'
    return {'state': state, 'generated_at': data['generated_at'], 'calls': calls}


def record_mark(folder, payload, now=None):
    """Append one tick {id, card, done}. Validates against the current tasks.json; raises LookupError/ValueError."""
    if not isinstance(payload, dict):
        raise ValueError('invalid')
    step_id, card, done = payload.get('id'), payload.get('card'), payload.get('done')
    if not (isinstance(step_id, str) and STEP_ID.fullmatch(step_id) and isinstance(card, str)
            and CARD.fullmatch(card) and isinstance(done, bool)):
        raise ValueError('invalid')
    folder = Path(folder)
    data = json.loads(_read(folder / 'tasks.json', MAX_FILE))
    known = any(c.get('card') == card and any(s.get('id') == step_id for s in c.get('steps', []))
                for c in data.get('calls', []) if isinstance(c, dict))
    if not known:
        raise LookupError(step_id)
    at = (now or datetime.now(timezone.utc)).isoformat(timespec='seconds').replace('+00:00', 'Z')
    line = json.dumps({'id': step_id, 'card': card, 'done': done, 'at': at, 'by': 'command-center'},
                      ensure_ascii=False) + '\n'
    path = folder / 'marks.jsonl'
    fd = os.open(str(path), os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    with os.fdopen(fd, 'a', encoding='utf-8') as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        stream.write(line)
    return {'id': step_id, 'card': card, 'done': done, 'at': at}
