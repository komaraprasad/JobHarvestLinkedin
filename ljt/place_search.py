"""Connects locations.py (unchanged) to the Jobs Collector: suggestions, the REGION facet, what the LinkedIn
jobs search gets, and the final location check on each collected job."""
from typing import Dict, List
from urllib.parse import quote

from . import geo_db
from .geo_directory import BY_ID, DIRECTORY
from .job_location import job_in_requested_place
from .locations import _fold, _local_terms, alias_suggestions, lead_in_place, resolve_many


def suggest(query: str, limit: int = 8) -> List[Dict[str, str]]:
    """Location-box suggestions: alias_suggestions first, then directory matches. Never calls LinkedIn."""
    q = _fold(query)
    if len(q) < 2:
        return []
    by_name = {_fold(d["name"]): d for d in DIRECTORY}
    out, seen = [], set()

    def add(text, gid):
        key = gid or _fold(text)          # one suggestion per LinkedIn ID
        if key not in seen:
            seen.add(key)
            out.append({"text": text, "id": gid})

    for name in alias_suggestions(query):
        d = by_name.get(_fold(name))
        add(d["name"] if d else name, d["id"] if d else "")
    matches = [d for d in DIRECTORY if q in _fold(d["name"])]
    matches.sort(key=lambda d: (not _fold(d["name"]).startswith(q), d["type"] != "Country", len(d["name"])))
    for d in matches:
        add(d["name"], d["id"])
    for d in geo_db.search(query, limit=limit):      # any other place in world_geo.db (mostly without an ID)
        add(d["text"], d["id"])
    return out[:limit]


def region_facet(regions: List[Dict[str, str]]) -> str:
    """Sales Navigator REGION facet, e.g.
    (type:REGION,values:List((id:105214831,text:Bengaluru%2C Karnataka%2C India,selectionType:INCLUDED)))"""
    values = ",".join(f"(id:{r['id']},text:{quote(r['text'], safe=' ')},selectionType:INCLUDED)" for r in regions)
    return f"(type:REGION,values:List({values}))"


def plan(places: List[Dict[str, str]]) -> Dict[str, object]:
    """resolve_many + what a LinkedIn JOBS search can take. Job search takes ONE geoId, so several regions use
    their shared country (Bengaluru + Chennai -> India) and the per-job check keeps only the requested places."""
    r = resolve_many(places, DIRECTORY)
    regions, names = r["regions"], r["names"]
    geo_id, location_text = "", ""
    if len(regions) == 1:
        geo_id, location_text = regions[0]["id"], regions[0]["text"]
    elif regions:
        countries = {BY_ID[g["id"]]["country"] for g in regions if g["id"] in BY_ID}
        if len(countries) == 1:
            country = next(iter(countries))
            c = next((d for d in DIRECTORY if d["type"] == "Country" and d["name"] == country), None)
            if c:
                geo_id, location_text = c["id"], c["name"]
    elif len(names) == 1:
        location_text = names[0]               # no ID at all: send the text, filter by it locally too
    return {"regions": regions, "local_terms": r["local_terms"], "names": names, "geo_id": geo_id,
            "location_text": location_text, "facet": region_facet(regions) if regions else ""}


def job_in_places(job_location: str, names: List[str], local_terms: List[str]) -> bool:
    """Final check on a collected job. With local_terms (a place was widened): lead_in_place, as specified.
    Otherwise the job must be in one of the requested places; job locations often name only the city
    ('Bengaluru (Hybrid)'), so a country also accepts the cities it contains. An empty location is kept."""
    if local_terms:
        if lead_in_place(job_location, local_terms):
            return True
    elif not names or not (job_location or "").strip():
        return True
    elif any(job_in_requested_place(n, job_location) for n in names):
        return True
    return remote_covers(job_location, names)


def remote_covers(job_location: str, names: List[str]) -> bool:
    """A REMOTE job open to a whole country ('India (Remote)') covers every requested place in that country
    (Bengaluru, Karnataka, India). LinkedIn lists such jobs in city searches on purpose."""
    loc = job_location or ""
    if "remote" not in loc.lower():
        return False
    where = _fold(loc.lower().replace("(remote)", "").replace("remote", "")).strip(" ,-")
    if not where:
        return True                                   # just 'Remote': not judged
    for n in names:
        d = next((x for x in DIRECTORY if _fold(x["name"]) == _fold(n)), None)
        country = _fold(d["country"]) if d else _fold(n.split(",")[-1])
        if where == country:
            return True
    return False


def saved_like_terms(place: str) -> List[str]:
    """Lower-case terms for filtering saved jobs by place with SQL LIKE '%term%'."""
    return [t.lower() for t in _local_terms(place)] or [(place or "").strip().lower()]
