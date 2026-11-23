"""«Медиа» → «Личное»: Max's own published generations (Mark 2026-11-24).

Max: «в разделе медиа сделай личные медиа и туда генерации опубликованные кидай».

Storage lives outside git, on the Mac mini:
  ~/.agent-bridge/personal-media/items.json   the list (newest first when shown)
  ~/.agent-bridge/personal-media/files/       the videos and pictures themselves

Agents add an item with:
  python3 -m dashboard_builder.media_personal add --file intro.mp4 --title "Интро" \
      --where "Кружок Риса" --published 2026-11-17
Everything here is owner-only; the server checks the owner before calling it.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import stat
import sys
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,63}$")
FILE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,120}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
URL_RE = re.compile(r"^https://\S{4,2000}$")
MIME = {
    ".mp4": "video/mp4", ".m4v": "video/mp4", ".mov": "video/quicktime", ".webm": "video/webm",
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".gif": "image/gif",
}
MAX_ITEMS = 500
MAX_TEXT = 300


def root() -> Path:
    custom = os.environ.get("MEDIA_PERSONAL_DIR", "").strip()
    return Path(custom) if custom else Path.home() / ".agent-bridge" / "personal-media"


def _kind(name: str) -> str:
    mime = MIME.get(Path(name).suffix.lower(), "")
    return mime.split("/")[0] if mime else ""


def _text(value, limit: int = MAX_TEXT) -> str:
    return " ".join(str(value or "").split())[:limit]


def _clean(raw: dict, files: Path) -> dict | None:
    if not isinstance(raw, dict):
        return None
    item_id = str(raw.get("id") or "")
    title = _text(raw.get("title"), 160)
    if not ID_RE.match(item_id) or not title:
        return None
    file_name = str(raw.get("file") or "")
    url = str(raw.get("url") or "")
    published = str(raw.get("published") or "")
    where = raw.get("where") if isinstance(raw.get("where"), list) else []
    item = {
        "id": item_id,
        "title": title,
        "note": _text(raw.get("note")),
        "published": published if DATE_RE.match(published) else "",
        "where": [_text(w, 80) for w in where if _text(w, 80)][:6],
        "url": url if URL_RE.match(url) else "",
        "kind": "link",
        "src": "",
    }
    if file_name and FILE_RE.match(file_name) and _kind(file_name) and _safe_file(files / file_name):
        item["kind"] = _kind(file_name)
        item["src"] = f"/api/media/personal/file?id={item_id}"
    if item["kind"] == "link" and not item["url"]:
        return None
    return item


def _safe_file(path: Path) -> bool:
    try:
        info = path.lstat()
    except OSError:
        return False
    return stat.S_ISREG(info.st_mode)


def _read(base: Path) -> list:
    try:
        data = json.loads((base / "items.json").read_text())
    except FileNotFoundError:
        return []
    except (OSError, ValueError):
        raise
    items = data.get("items") if isinstance(data, dict) else None
    return items if isinstance(items, list) else []


def overview(base: Path | None = None) -> dict:
    base = base or root()
    try:
        raw = _read(base)
    except (OSError, ValueError):
        return {"state": "unavailable", "items": []}
    files = base / "files"
    items = [item for item in (_clean(r, files) for r in raw[:MAX_ITEMS]) if item]
    items.sort(key=lambda i: i["published"], reverse=True)
    return {"state": "ready", "items": items}


def file_for(item_id: str, base: Path | None = None) -> tuple[Path, str] | None:
    """The stored file of one item, never a path outside files/ and never a symlink."""
    if not ID_RE.match(item_id or ""):
        raise ValueError("bad id")
    base = base or root()
    try:
        raw = _read(base)
    except (OSError, ValueError):
        return None
    for entry in raw:
        if isinstance(entry, dict) and entry.get("id") == item_id:
            name = str(entry.get("file") or "")
            if not FILE_RE.match(name) or not _kind(name):
                return None
            path = base / "files" / name
            if not _safe_file(path):
                return None
            return path, MIME[path.suffix.lower()]
    return None


def add(*, file: str | None, url: str | None, title: str, where: list[str], published: str,
        note: str = "", base: Path | None = None) -> dict:
    base = base or root()
    if not title.strip():
        raise ValueError("title is required")
    if published and not DATE_RE.match(published):
        raise ValueError("published must be YYYY-MM-DD")
    if url and not URL_RE.match(url):
        raise ValueError("url must start with https://")
    if not file and not url:
        raise ValueError("give --file or --url")
    (base / "files").mkdir(parents=True, exist_ok=True)
    items = _read(base)
    item_id = f"{(published or date.today().isoformat())}-{uuid.uuid4().hex[:8]}"
    entry = {"id": item_id, "title": title.strip(), "note": note.strip(), "where": where,
             "published": published or date.today().isoformat(), "url": url or "",
             "added": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    if file:
        source = Path(file).expanduser()
        if not source.is_file() or not _kind(source.name):
            raise ValueError("file must be a video or picture")
        name = f"{item_id}{source.suffix.lower()}"
        shutil.copy2(source, base / "files" / name)
        entry["file"] = name
    items.insert(0, entry)
    tmp = base / "items.json.tmp"
    tmp.write_text(json.dumps({"items": items}, ensure_ascii=False, indent=2))
    tmp.replace(base / "items.json")
    return entry


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Add a published generation to «Медиа → Личное».")
    sub = parser.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add")
    a.add_argument("--file")
    a.add_argument("--url")
    a.add_argument("--title", required=True)
    a.add_argument("--where", action="append", default=[])
    a.add_argument("--published", default="")
    a.add_argument("--note", default="")
    sub.add_parser("list")
    args = parser.parse_args(argv)
    if args.cmd == "list":
        print(json.dumps(overview(), ensure_ascii=False, indent=2))
        return 0
    try:
        entry = add(file=args.file, url=args.url, title=args.title, where=args.where,
                    published=args.published, note=args.note)
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    print(json.dumps(entry, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
