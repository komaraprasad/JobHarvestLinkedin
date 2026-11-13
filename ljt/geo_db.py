"""Read-only access to world_geo.db (158k places: name, type, country, optional LinkedIn geo_id).

Used for: the location directory (rows WITH a LinkedIn ID), location-box suggestions, and finding which
country a city is in. The tool works without the file (falls back to the built-in directory)."""
import os
import sqlite3
import threading
from functools import lru_cache

DB_PATH = os.environ.get("LJT_GEO_DB", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "world_geo.db"))
_local = threading.local()
TYPE_RANK = {"Country": 0, "State / Province": 1, "Metro Area": 2, "City": 3}


def available():
    return os.path.exists(DB_PATH)


def _db():
    if not available():
        return None
    if getattr(_local, "db", None) is None:
        _local.db = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, check_same_thread=False)
    return _local.db


@lru_cache(maxsize=1)
def linked_places():
    """Rows that carry a LinkedIn geo ID, as directory items {id, name, type, country}."""
    db = _db()
    if not db:
        return []
    rows = db.execute("SELECT name, type, country, geo_id FROM locations WHERE geo_id IS NOT NULL AND geo_id != '' ORDER BY id")
    out, seen = [], set()
    for name, typ, country, gid in rows:
        if str(gid).isdigit() and name not in seen:
            seen.add(name)
            out.append({"id": str(gid), "name": name, "type": typ, "country": country})
    return out


def search(query, limit=8):
    """Places whose name starts with the query (any word order is not attempted). Countries/states first."""
    db = _db()
    q = (query or "").strip().lower()
    if not db or len(q) < 2:
        return []
    rows = db.execute("SELECT name, type, country, geo_id FROM locations WHERE lower(name) LIKE ? LIMIT 400",
                      (q.replace("%", "").replace("_", "") + "%",)).fetchall()
    rows.sort(key=lambda r: (not (r[3] or "").isdigit(), TYPE_RANK.get(r[1], 9), len(r[0])))
    return [{"text": r[0], "id": r[3] if (r[3] or "").isdigit() else "", "type": r[1], "country": r[2]} for r in rows[:limit]]


@lru_cache(maxsize=4096)
def countries_of(place):
    """Countries that have a city/state/metro whose name starts with `place` ('Madurai' -> {'India'}).
    Empty set when unknown. Cached; read-only."""
    db = _db()
    name = (place or "").strip()
    if not db or len(name) < 3:
        return frozenset()
    rows = db.execute("SELECT DISTINCT country FROM locations WHERE type != 'Country' AND (lower(name) = ? OR lower(name) LIKE ?)",
                      (name.lower(), name.lower() + ",%")).fetchall()
    return frozenset(r[0] for r in rows if r[0])
