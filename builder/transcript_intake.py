"""Deterministic, non-destructive manual transcript intake. No network or models."""
from __future__ import annotations
import contextlib
import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import stat

MAX_BYTES = 2 * 1024 * 1024
SOURCES = ('krisp', 'granola')

def sha(raw):
    return hashlib.sha256(raw).hexdigest()

def front(text):
    data = {}
    if text.startswith('---\n'):
        end = text.find('\n---', 4)
        if 0 < end < 16384:
            for line in text[4:end].splitlines():
                k, sep, v = line.partition(':')
                if sep and re.fullmatch(r'[a-z_][a-z0-9_]*', k):
                    data[k] = v.strip().strip('"\'')
            return data, text[end + 4:].lstrip('\n')
    return data, text

def checked_path(path):
    path = Path(path).absolute()
    if '..' in path.parts: raise ValueError('parent_traversal')
    for candidate in reversed((path,) + tuple(path.parents)):
        if candidate.is_symlink():
            # macOS system aliases, not user-selected storage aliases.
            if str(candidate) in ('/tmp', '/var', '/etc') and str(candidate.resolve()) == '/private' + str(candidate):
                continue
            raise ValueError('symlink_path')
    return path

def safe(root, path):
    root, path = checked_path(root), checked_path(path)
    path.relative_to(root)
    return path

def walk(root, issues=None):
    if root.is_symlink():
        if issues is not None: issues['unsupported'] += 1
        return
    if not root.is_dir(): return
    def enumeration_error(error):
        if issues is None: raise error
        issues['unsupported'] += 1
    for folder, dirs, files in os.walk(root, followlinks=False, onerror=enumeration_error):
        excluded = [n for n in dirs if n.startswith('.') or (Path(folder)/n).is_symlink()]
        if issues is not None: issues['unsupported'] += len(excluded)
        dirs[:] = [n for n in dirs if n not in excluded]
        for name in sorted(files):
            if name.startswith('.'): continue
            p = Path(folder)/name
            if p.is_symlink() or not stat.S_ISREG(p.lstat().st_mode):
                if issues is not None: issues['unsupported'] += 1
                continue
            yield p

def read(p):
    fd = os.open(str(p), os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
    with os.fdopen(fd, 'rb') as f:
        if not stat.S_ISREG(os.fstat(f.fileno()).st_mode): raise ValueError('nonregular_file')
        raw = f.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES: raise ValueError('oversized')
    return raw, raw.decode('utf-8')

def atomic(path, raw, exclusive=False):
    fd, name = tempfile.mkstemp(prefix='.transcript-', dir=str(path.parent))
    temp = Path(name)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(raw); f.flush(); os.fsync(f.fileno())
        if exclusive:
            os.link(temp, path)  # Atomic publication without replacing any existing file.
        else:
            os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)

def import_transcript_exports(vault, intake, state_file, dry_run=False):
    vault, intake, state_file = map(checked_path, (vault, intake, state_file))
    if not vault.is_dir() or not intake.is_dir() or vault.is_symlink() or intake.is_symlink():
        raise ValueError('missing_or_unsafe_root')
    for root in (vault, intake):
        if state_file.resolve().is_relative_to(root.resolve()): raise ValueError('state_must_be_external')
    if state_file.is_symlink() or state_file.parent.is_symlink(): raise ValueError('unsafe_state')
    # Validate all write locations before creating state or any note.
    for source in SOURCES: safe(vault, vault/'00-Inbox'/source)
    result = dict(imported=0, already_present=0, conflicts=0, unsupported=0)
    if not dry_run and not state_file.parent.is_dir(): raise ValueError('missing_state_parent')
    lock = contextlib.nullcontext() if dry_run else (state_file.parent/'intake.lock').open('a')
    with lock as handle:
        if not dry_run: fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        state = json.loads(state_file.read_text()) if state_file.exists() else {'schema':1,'records':{}}
        if not isinstance(state, dict) or state.get('schema') != 1 or not isinstance(state.get('records'), dict): raise ValueError('invalid_state')
        for record in state['records'].values():
            if not isinstance(record, dict) or not isinstance(record.get('path'), str): raise ValueError('invalid_state_record')
            safe(vault, vault / record['path'])
        index = {}
        roots = ['10-Transcripts'] + ['00-Inbox/'+s for s in ('plaud',)+SOURCES]
        for rel in roots:
            for p in walk(safe(vault, vault/rel)):
                if p.suffix.lower() != '.md': continue
                raw, text = read(p)  # Incomplete canonical index must never permit a duplicate.
                fm, body = front(text); source = fm.get('source','')
                if source not in SOURCES: continue
                upstream = fm.get('meeting_id') if source == 'krisp' else fm.get('granola_id')
                keys=[]
                if upstream: keys.append(source+':id:'+upstream)
                if fm.get('import_sha256'): keys.append(source+':sha:'+fm['import_sha256'])
                for key in keys: index.setdefault(key,[]).append((p,raw,fm,body))
        for source in SOURCES:
            for p in walk(intake/source, result):
                if p.suffix.lower() not in ('.txt','.md'):
                    result['unsupported'] += 1; continue
                try: raw,text = read(p)
                except (OSError,UnicodeError,ValueError):
                    result['unsupported'] += 1; continue
                digest = sha(raw); fm,body = front(text)
                field = 'meeting_id' if source == 'krisp' else 'granola_id'
                upstream = fm.get(field,'')
                if len(upstream)>256 or any(ord(c)<32 for c in upstream):
                    result['unsupported']+=1;continue
                key=source+(':id:'+upstream if upstream else ':sha:'+digest)
                record=state['records'].get(key)
                if record:
                    try:
                        target=safe(vault,vault/record['path'])
                        if target.exists() and sha(read(target)[0]) != record['note_sha256']:
                            result['conflicts']+=1;continue
                    except (KeyError,ValueError,OSError,UnicodeError):
                        result['conflicts']+=1;continue
                existing=index.get(key,[]) or index.get(source+':sha:'+digest,[])
                if existing:
                    matches=[x for x in existing if x[2].get('import_sha256')==digest or x[1]==raw or x[3]==body]
                    if len(matches)!=1 or len(existing)!=1:
                        result['conflicts']+=1;continue
                    target,nraw,_,_=matches[0]
                    state['records'][key]={'path':str(target.relative_to(vault)),'note_sha256':sha(nraw),'import_sha256':digest}
                    result['already_present']+=1;continue
                rid=sha(key.encode())[:32];target=safe(vault,vault/'00-Inbox'/source/(rid+'.md'))
                if target.exists():result['conflicts']+=1;continue
                header=['---','type: transcript','source: '+source,'import_sha256: '+digest,'imported_at: '+datetime.datetime.now(datetime.timezone.utc).isoformat()]
                title = fm.get('title') or next((line.lstrip('# ').strip() for line in body.splitlines() if line.startswith('# ')), p.stem)
                title = ''.join(c for c in title if ord(c) >= 32)[:240]
                header.append('title: ' + json.dumps(title, ensure_ascii=False))
                if upstream: header.append(field+': '+json.dumps(upstream,ensure_ascii=False))
                date=fm.get('date','')
                if re.fullmatch(r'\d{4}-\d{2}-\d{2}',date):header.append('date: '+date)
                note=('\n'.join(header)+'\n---\n\n'+text).encode('utf-8')
                if not dry_run:
                    target.parent.mkdir(parents=True,exist_ok=True);safe(vault,target)
                    try:atomic(target,note,exclusive=True)
                    except FileExistsError:result['conflicts']+=1;continue
                state['records'][key]={'path':str(target.relative_to(vault)),'note_sha256':sha(note),'import_sha256':digest}
                nfm,nbody=front(note.decode());index.setdefault(key,[]).append((target,note,nfm,nbody))
                result['imported']+=1
        if not dry_run:
            data=(json.dumps(state,ensure_ascii=False,indent=2)+'\n').encode()
            if not state_file.exists() or state_file.read_bytes()!=data:atomic(state_file,data)
    return result
