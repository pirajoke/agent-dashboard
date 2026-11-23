"""«Правила» (Макс 2026-11-23: «выведи в командный центр вкладку правила, чтобы видны были все правила HQ»).

Read-only view of the rule files that steer Jarvis and the HQ agents. Files are read live, with a
cache of at most a minute, and nothing here ever writes. Only a fixed list of Markdown files is
shown: Jarvis topic files, the HQ AGENTS/CLAUDE files and three reference docs. Backups
(``*.bak*``), permissions, secrets, ``.env`` and config files are never read.

Markdown is turned into HTML here with a small renderer that escapes every piece of text first,
so a rule file cannot inject markup into the page.
"""
from __future__ import annotations

import html
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

CACHE_SECONDS = 60
MAX_FILE_BYTES = 400_000

# (group id, group title, [(relative path, title or None = take the first heading)])
GROUPS = (
    ("jarvis", "Jarvis", (
        ("HQ/hq/jarvis-topics/_rules.md", "Правила Джарвиса"),
        ("HQ/hq/jarvis-topics/_common.md", "Общие факты"),
        ("HQ/hq/jarvis-topics/_style.md", "Стиль ответа"),
        ("HQ/hq/jarvis-topics/README.md", "Как устроены темы"),
        ("HQ/hq/jarvis-topics/*.md", None),
        (".hermes/profiles/jarvis/SOUL.md", "Характер Джарвиса (SOUL)"),
    )),
    ("agents", "Агенты HQ", (
        ("AGENTS.md", "Общие правила (установлены на Mac mini)"),
        ("HQ/hq/global/AGENTS.md", "Общие правила: исходник в HQ"),
        ("HQ/hq/global/CLAUDE.md", "Общие правила: CLAUDE.md"),
        ("HQ/hq/AGENTS.md", "Правила штаба"),
        ("HQ/hq/CLAUDE.md", "Штаб: CLAUDE.md"),
    )),
    ("docs", "Справка", (
        ("HQ/hq/docs/rules-history.md", "История правил"),
        ("HQ/hq/docs/rules-freshness.md", "Свежесть правил"),
        ("HQ/hq/docs/max-words.md", "Слова Макса"),
    )),
)

_BLOCKED_PARTS = {"permissions", "secrets", ".env", "config.yaml"}
_cache: dict = {}
_lock = threading.Lock()


_ROOTS = ("HQ/hq", ".hermes/profiles/jarvis", "AGENTS.md")


def _target_ok(home: Path, path: Path) -> bool:
    """A symlink may only point at a file under the same allowed roots, and passes the same filter."""
    try:
        target = path.resolve(strict=True)
    except OSError:
        return False
    for root in _ROOTS:
        try:
            base = (home / root).resolve()
        except OSError:
            continue
        if target == base or base in target.parents:
            return _allowed(target)
    return False


def _allowed(path: Path) -> bool:
    name = path.name
    if ".bak" in name or not name.endswith(".md"):
        return False
    return not any(part in _BLOCKED_PARTS or part.startswith(".env") for part in path.parts)


def _first_heading(text: str) -> str:
    for line in text.splitlines():
        if line.startswith("# "):
            title = line[2:].strip()
            return re.sub(r"\s*\((обновлено|updated)[^)]*\)\s*$", "", title).strip()
    return ""


def _entries(home: Path):
    """Yield (group, group title, path, fixed title) without duplicates, in display order."""
    seen: set = set()
    for group, group_title, items in GROUPS:
        for rel, title in items:
            if "*" in rel:
                base = home / rel.rsplit("/", 1)[0]
                paths = sorted(base.glob(rel.rsplit("/", 1)[1])) if base.is_dir() else []
            else:
                paths = [home / rel]
            for path in paths:
                try:
                    key = str(path.resolve())
                except OSError:
                    key = str(path)
                if key in seen or not _allowed(path) or not _target_ok(home, path):
                    continue
                if "*" in rel and path.name.startswith("_"):
                    continue
                seen.add(key)
                yield group, group_title, path, title


# ── Markdown → HTML (escaped) ────────────────────────────────────────────────

_INLINE_CODE = re.compile(r"`([^`]+)`")
_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_ITALIC = re.compile(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])")


def _inline(text: str) -> str:
    codes: list = []

    def keep(match):
        codes.append(f"<code>{html.escape(match.group(1))}</code>")
        return f"\x00{len(codes) - 1}\x00"

    text = text.replace("\x00", "")
    text = _INLINE_CODE.sub(keep, text)
    text = html.escape(text, quote=False)
    text = _LINK.sub(lambda m: f'<a href="{html.escape(html.unescape(m.group(2)))}" rel="noopener noreferrer" target="_blank">{m.group(1)}</a>', text)
    text = _BOLD.sub(r"<strong>\1</strong>", text)
    text = _ITALIC.sub(r"<em>\1</em>", text)
    return re.sub(r"\x00(\d+)\x00", lambda m: codes[int(m.group(1))], text)


def _table(rows: list) -> str:
    def cells(row):
        row = row.strip().strip("|")
        return [c.strip() for c in row.split("|")]

    head = cells(rows[0])
    body = [cells(r) for r in rows[2:]]
    out = ["<div class=\"rules-table\"><table><thead><tr>"]
    out += [f"<th>{_inline(c)}</th>" for c in head]
    out.append("</tr></thead><tbody>")
    for row in body:
        out.append("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in row) + "</tr>")
    out.append("</tbody></table></div>")
    return "".join(out)


def render_markdown(text: str) -> str:
    lines = text.replace("\r\n", "\n").split("\n")
    out: list = []
    para: list = []
    lists: list = []  # stack of (indent, tag)

    def flush_para():
        if para:
            out.append(f"<p>{_inline(' '.join(para))}</p>")
            para.clear()

    def close_lists(indent=-1):
        while lists and lists[-1][0] > indent:
            out.append(f"</li></{lists.pop()[1]}>")

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if stripped.startswith("```"):
            flush_para(); close_lists()
            block = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                block.append(lines[i])
                i += 1
            out.append(f"<pre><code>{html.escape(chr(10).join(block))}</code></pre>")
            i += 1
            continue
        if not stripped:
            flush_para()
            i += 1
            continue
        if stripped.startswith("<!--") and any("-->" in rest for rest in lines[i:]):
            while i < len(lines) and "-->" not in lines[i]:
                i += 1
            i += 1
            continue
        heading = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if heading:
            flush_para(); close_lists()
            level = min(len(heading.group(1)) + 1, 6)
            out.append(f"<h{level}>{_inline(heading.group(2))}</h{level}>")
            i += 1
            continue
        if re.match(r"^(-{3,}|\*{3,}|_{3,})$", stripped):
            flush_para(); close_lists()
            out.append("<hr>")
            i += 1
            continue
        if stripped.startswith("|") and i + 1 < len(lines) and re.match(r"^\s*\|?\s*:?-{2,}", lines[i + 1]):
            flush_para(); close_lists()
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append(lines[i])
                i += 1
            out.append(_table(rows))
            continue
        if stripped.startswith(">"):
            flush_para(); close_lists()
            quote = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                quote.append(lines[i].strip()[1:].strip())
                i += 1
            out.append(f"<blockquote>{render_markdown(chr(10).join(quote))}</blockquote>")
            continue
        item = re.match(r"^(\s*)([-*+]|\d+[.)])\s+(.*)$", line)
        if item:
            flush_para()
            indent = len(item.group(1).replace("\t", "    "))
            tag = "ol" if item.group(2)[0].isdigit() else "ul"
            if lists and indent > lists[-1][0]:
                out.append(f"<{tag}><li>")
                lists.append((indent, tag))
            else:
                close_lists(indent)
                if lists and lists[-1][0] == indent and lists[-1][1] != tag:
                    out.append(f"</li></{lists.pop()[1]}>")
                if lists and lists[-1][0] == indent:
                    out.append("</li><li>")
                else:
                    out.append(f"<{tag}><li>")
                    lists.append((indent, tag))
            out.append(_inline(item.group(3)))
            i += 1
            continue
        if lists and line.startswith(" "):
            out.append(" " + _inline(stripped))
            i += 1
            continue
        close_lists()
        para.append(stripped)
        i += 1
    flush_para(); close_lists()
    return "\n".join(out)


# ── Projection ────────────────────────────────────────────────────────────────

def _safe_render(text: str) -> str:
    try:
        return render_markdown(text)
    except Exception:  # one odd file must not take the whole tab down
        return f"<pre><code>{html.escape(text)}</code></pre>"


def _file_id(home: Path, path: Path) -> str:
    try:
        rel = path.relative_to(home)
    except ValueError:
        rel = path
    return re.sub(r"[^a-z0-9_]+", "-", str(rel).lower()).strip("-")


def collect(home: Path) -> dict:
    groups: dict = {}
    for group, group_title, path, title in _entries(home):
        try:
            if not path.is_file():
                continue
            stat = path.stat()
            if stat.st_size > MAX_FILE_BYTES:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if title is None:
            title = f"Тема: {_first_heading(text) or path.stem}"
        shown = str(path).replace(str(home), "~", 1)
        entry = {
            "id": _file_id(home, path),
            "title": title,
            "path": shown,
            "modified": datetime.fromtimestamp(stat.st_mtime, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "html": _safe_render(text),
        }
        groups.setdefault(group, {"id": group, "title": group_title, "files": []})["files"].append(entry)
    ordered = [groups[g] for g, _, _ in GROUPS if g in groups]
    return {"ok": True, "groups": ordered, "read_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}


def projection(home: Path, *, owner: bool, now: float | None = None) -> dict:
    now = time.monotonic() if now is None else now
    with _lock:
        cached = _cache.get(str(home))
        if not cached or now - cached[0] > CACHE_SECONDS:
            cached = (now, collect(home))
            _cache[str(home)] = cached
    data = cached[1]
    if not owner:
        count = sum(len(g["files"]) for g in data["groups"])
        return {"ok": True, "owner_view": False, "count": count}
    return {**data, "owner_view": True}
