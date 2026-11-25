"""Owner-only GitHub issue board. The local ledger stores operation hashes, not tasks."""
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import time
from datetime import date, datetime
from zoneinfo import ZoneInfo
from pathlib import Path

MARKER = re.compile(r'^<!-- cc-task (.+?) -->$', re.MULTILINE)
STATES = ('todo', 'doing', 'done')


class Conflict(ValueError):
    pass


class RequestRejected(RuntimeError):
    """The remote create request was definitely rejected before creating an issue."""

def gh(method, path, payload=None):
    exe = shutil.which('gh')
    if not exe:
        local = Path.home() / '.local' / 'bin' / 'gh'
        exe = str(local) if local.is_file() else '/opt/homebrew/bin/gh'
    args = [exe, 'api', '--hostname', 'github.com', '-X', method, path]
    if payload is not None:
        args.extend(['--input', '-'])
    result = subprocess.run(args, input=json.dumps(payload) if payload is not None else None,
                            text=True, capture_output=True, timeout=20)
    if result.returncode:
        error = result.stderr.lower()
        if method == 'POST' and (
            re.search(r'http (?:400|401|403|404|405|413|415|422|429)\b', error)
            or 'connection refused' in error or 'no such host' in error
        ):
            raise RequestRejected('GitHub отклонил создание задачи. Можно повторить.')
        raise RuntimeError('GitHub недоступен для этой операции')
    return json.loads(result.stdout)


def checked_date(value):
    if not isinstance(value, str) or (value and date.fromisoformat(value).isoformat() != value):
        raise ValueError('Нужна дата ГГГГ-ММ-ДД')
    return value


def short(value, limit, *, required=False):
    if not isinstance(value, str) or len(value) > limit or any(ord(c) < 32 for c in value):
        raise ValueError('Некорректное поле задачи')
    value = value.strip()
    if required and not value:
        raise ValueError('Пустое обязательное поле')
    return value


def marker(meta):
    return '<!-- cc-task ' + json.dumps(meta, ensure_ascii=False).replace('<', r'\u003c').replace('>', r'\u003e') + ' -->'


# Each board request used to spend two extra GitHub calls (who am I, is the repo private) before the real
# one, so a tick took ~2 s (Mark 2026-11-25 «не тыкаются кнопки»). The answers are kept for 10 minutes,
# only for the real GitHub client; a repo that stops being private is noticed within that window.
_CHECKED = {}
CHECK_TTL_S = 600


class Board:
    def __init__(self, *, api=gh, repo=None, ledger=None):
        self.api = api
        cached = api is gh and _CHECKED.get(repo or '')
        if cached and time.monotonic() - cached[1] < CHECK_TTL_S:
            self.repo = cached[0]
        else:
            self.repo = repo or os.environ.get('COMMAND_CENTER_TASK_REPO') or (api('GET', 'user')['login'] + '/HQ')
            if not re.fullmatch(r'[\w.-]+/[\w.-]+', self.repo):
                raise ValueError('Некорректный репозиторий')
            if api('GET', f'repos/{self.repo}').get('private') is not True:
                raise RuntimeError('Для личных задач нужен закрытый репозиторий')
            if api is gh:
                _CHECKED[repo or ''] = (self.repo, time.monotonic())
        self.root = f'repos/{self.repo}'
        self.ledger = ledger or Path.home() / '.agent-bridge' / 'kanban-requests.sqlite3'

    def task(self, issue):
        match = MARKER.search(issue.get('body') or '')
        if not match or 'pull_request' in issue:
            return None
        meta = json.loads(match[1])
        revision = hashlib.sha256(json.dumps([issue['title'], issue['body'], issue['state'],
                                               issue.get('updated_at')]).encode()).hexdigest()
        return dict(id=issue['number'], title=issue['title'], project=meta['project'],
                    status='done' if issue['state'] == 'closed' else meta['lane'],
                    plan=meta.get('plan', ''), due=meta.get('due', ''), revision=revision,
                    url=f"https://github.com/{self.repo}/issues/{issue['number']}")

    def issues(self, state='all'):
        page = 1
        while True:
            batch = self.api('GET', f'{self.root}/issues?labels=command-center&state={state}&per_page=100&page={page}')
            yield from batch
            if len(batch) < 100:
                break
            page += 1

    def list(self, include_done=False):
        return [t for i in self.issues('all' if include_done else 'open') if (t := self.task(i))]

    def apply(self, action, fields):
        if action == 'list_tasks':
            view = fields.get('view', 'all' if fields.get('include_done') is True else 'open')
            if view not in ('all', 'open', 'day', 'overdue'):
                raise ValueError('Неизвестный вид списка')
            cards = self.list(include_done=view == 'all')
            today = datetime.now(ZoneInfo('Europe/Paris')).date().isoformat()
            if view == 'day':
                return [card for card in cards if card['plan'] == today]
            if view == 'overdue':
                return [card for card in cards if card['due'] and card['due'] < today]
            return cards
        if action not in ('create_task', 'update_task'):
            raise ValueError('Неизвестная операция')
        self.ledger.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        db = sqlite3.connect(self.ledger, timeout=60, isolation_level=None)
        try:
            db.execute('CREATE TABLE IF NOT EXISTS requests (key TEXT PRIMARY KEY, signature TEXT, number INTEGER)')
            # A process lock covers reconciliation and remote writes including ambiguous timeouts.
            import fcntl
            with self.ledger.with_suffix('.lock').open('a') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                if action == 'create_task':
                    return self.create(fields, db)
                return self.update(fields)
        finally:
            db.close()

    def create(self, f, db):
        key = short(f['source_key'], 200, required=True)
        title = short(f['title'], 250, required=True)
        project = short(f.get('project') or 'Личное', 120, required=True)
        meta = dict(key=hashlib.sha256(key.encode()).hexdigest(), project=project, lane='todo',
                    plan=checked_date(f.get('plan', '')), due=checked_date(f.get('due', '')))
        sig = hashlib.sha256(json.dumps([title, meta], sort_keys=True).encode()).hexdigest()
        # GitHub issue numbers are unique only within one repository.
        ledger_key = self.repo.casefold() + ':' + meta['key']
        row = db.execute('SELECT signature, number FROM requests WHERE key=?', (ledger_key,)).fetchone()
        if row:
            if row[0] != sig:
                raise Conflict('Этот запрос уже использован для другой задачи')
            if row[1]:
                return self.task(self.api('GET', f'{self.root}/issues/{row[1]}'))
        for issue in self.issues():
            m = MARKER.search(issue.get('body') or '')
            if m and json.loads(m[1]).get('key') == meta['key']:
                db.execute('INSERT OR REPLACE INTO requests VALUES (?,?,?)', (ledger_key, sig, issue['number']))
                return self.task(issue)
        if row:
            raise Conflict('GitHub ещё не подтвердил предыдущую попытку. Обнови список.')
        db.execute('INSERT INTO requests VALUES (?,?,NULL)', (ledger_key, sig))
        try:
            created = self.api('POST', f'{self.root}/issues',
                               {'title': title, 'body': marker(meta), 'labels': ['command-center']})
        except (RequestRejected, ConnectionRefusedError, FileNotFoundError):
            db.execute('DELETE FROM requests WHERE key=?', (ledger_key,))
            raise
        db.execute('UPDATE requests SET number=? WHERE key=?', (created['number'], ledger_key))
        return self.task(created)

    def update(self, f):
        number = f['id']
        if type(number) is not int or number <= 0:
            raise ValueError('Некорректный номер задачи')
        path = f'{self.root}/issues/{number}'
        issue = self.api('GET', path)
        task = self.task(issue)
        if not task or task['revision'] != f['revision']:
            raise Conflict('Обнови список: карточка изменилась')
        body = issue['body']
        m = MARKER.search(body)
        meta = json.loads(m[1])
        status = f.get('status', task['status'])
        if status not in STATES:
            raise ValueError('Неизвестный статус')
        if status != 'done':
            meta['lane'] = status
        for field in ('due','plan'):
            if field in f:
                meta[field] = checked_date(f[field])
        change = {'body': body[:m.start()] + marker(meta) + body[m.end():],
                  'state': 'closed' if status == 'done' else 'open'}
        return self.task(self.api('PATCH', path, change))
