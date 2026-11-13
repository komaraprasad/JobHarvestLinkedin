"""Checks a JOB's shown location against the Location box, using locations.py (kept unchanged)."""
import re

from . import geo_db
from .locations import ALIASES, _fold, _local_terms, canonical, lead_in_place

# ---------------------------------------------------------------------------------------------
# Checking a JOB's shown location against the Location box, without a
# geo-ID directory. LinkedIn job locations often name only the city ("Bengaluru (Hybrid)"), so a
# country must also accept the cities/states this module knows to be inside it.
# ---------------------------------------------------------------------------------------------
_PLACE_NOISE = re.compile(r"\b(greater|metropolitan|metro|area|region)\b")


def _countries() -> set:
    """Countries named in ALIASES ('india', 'united states', 'germany', ...)."""
    return {_fold(n.split(",")[-1]) for n in ALIASES.values()}


def _places_in_country(country: str) -> set:
    """Every city / state / everyday name that ALIASES puts inside this country (folded)."""
    terms = {country}
    for alias, name in ALIASES.items():
        parts = [_fold(p) for p in name.split(",") if p.strip()]
        if len(parts) > 1 and parts[-1] == country:
            terms.update(parts[:-1])
            if len(alias) > 3 and "." not in alias:
                terms.add(alias)
        elif _fold(name) == country and len(alias) > 3 and "." not in alias:
            terms.add(alias)                      # 'bharat' -> india
    return terms


def job_in_requested_place(requested: str, job_location: str) -> bool:
    """True when the job's shown location fits the Location box (or either is empty / unclear).

    * Country ('India', 'USA'): the job names that country or any known city/state in it, or names no other
      known country (a city this module doesn't know, e.g. 'Indore', is kept, not guessed away).
    * City / metro ('Bangalore', 'Greater Bengaluru Area'): lead_in_place() with the city's terms.
    """
    if not (requested or "").strip() or not (job_location or "").strip():
        return True
    name = canonical(requested)
    if "," not in name and _fold(name) not in _countries():
        stripped = _PLACE_NOISE.sub(" ", _fold(name))
        name = canonical(stripped) if _fold(canonical(stripped)) != _fold(stripped) else " ".join(stripped.split())
    folded = _fold(name)
    countries = _countries()
    if folded in countries:
        if lead_in_place(job_location, sorted(_places_in_country(folded))):
            return True
        city = re.split(r"[,(]", job_location)[0].strip()      # 'Madurai (Hybrid)' -> 'Madurai'
        known = {_fold(c) for c in geo_db.countries_of(city)}  # world_geo.db: which countries have this place
        if known:
            return folded in known
        loc = f" {_fold(job_location).replace(',', ' ')} "
        return not any(f" {c} " in loc for c in countries if c != folded)
    return lead_in_place(job_location, _local_terms(name))
