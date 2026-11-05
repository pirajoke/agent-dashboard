"""«Генеалогия» tab (Mark 2026-11-05): the family tree and a map of how the family moved.

Mark: «добавь визуализацию в командный центр, вкладка Genealogy… историческую линию с 1800 года,
как перемещались люди по всей карте». The data is his family research: names of living relatives,
places and sources. It lives only on the Mac mini (``~/.agent-bridge/genealogy.json``) and is served
behind the owner check; it never reaches the public HTML, the repository or the GitHub Pages copy.

The file is produced from the research project (master tree + family book + MyHeritage) and is
read-only for the site. Shape::

    {"places": {key: {"name", "lat", "lon", "approx"}},
     "people": [{"id", "name", "sex", "status", "parents": [...], "spouses": [...],
                 "birth": {...}, "death": {...}, "stops": [{"y", "p", "t", "k"}], ...}]}
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

MAX_FILE_BYTES = 4 * 1024 * 1024
MAX_PEOPLE = 5000


class GenealogyUnavailable(ValueError):
    """The file exists but is not a usable genealogy record."""


def load_genealogy(path: Path) -> dict:
    """Read and lightly validate the private genealogy file.

    Raises FileNotFoundError when there is no file yet, GenealogyUnavailable when it is malformed.
    """
    path = Path(path)
    size = path.stat().st_size
    if size > MAX_FILE_BYTES:
        raise GenealogyUnavailable("genealogy file is too large")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GenealogyUnavailable("genealogy file is not JSON") from exc
    if not isinstance(data, dict):
        raise GenealogyUnavailable("genealogy root must be an object")
    people = data.get("people")
    places = data.get("places")
    if not isinstance(people, list) or not isinstance(places, dict) or len(people) > MAX_PEOPLE:
        raise GenealogyUnavailable("genealogy needs a people list and a places map")
    ids = set()
    clean = []
    for person in people:
        if not isinstance(person, dict):
            continue
        pid = person.get("id")
        name = person.get("name")
        if not isinstance(pid, str) or not pid or not isinstance(name, str) or pid in ids:
            continue
        ids.add(pid)
        clean.append(person)
    clean_places = {}
    for key, place in places.items():
        if not isinstance(place, dict):
            continue
        lat, lon = place.get("lat"), place.get("lon")
        if isinstance(lat, (int, float)) and isinstance(lon, (int, float)) and -90 <= lat <= 90 and -180 <= lon <= 180:
            clean_places[str(key)] = {"name": str(place.get("name") or key), "lat": float(lat), "lon": float(lon),
                                      "approx": bool(place.get("approx"))}
    for person in clean:
        for field in ("parents", "spouses"):
            links = person.get(field)
            person[field] = [x for x in links if x in ids] if isinstance(links, list) else []
        stops = person.get("stops")
        person["stops"] = [s for s in stops if isinstance(s, dict) and s.get("p") in clean_places] if isinstance(stops, list) else []
    updated = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat(timespec="seconds")
    branches = []
    for line in data.get("branches") or []:
        if isinstance(line, dict) and isinstance(line.get("key"), str) and isinstance(line.get("roots"), list):
            branches.append({"key": line["key"], "name": str(line.get("name") or line["key"]),
                             "color": str(line.get("color") or ""), "roots": [r for r in line["roots"] if r in ids]})
    return {"state": "ready", "updated": updated, "places": clean_places, "people": clean, "branches": branches}
