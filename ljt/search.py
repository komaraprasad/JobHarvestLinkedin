"""What the person asks for in the dashboard, and how it becomes a LinkedIn job-search address.

Filter codes are LinkedIn's own URL parameters (as used by linkedin.com/jobs/search/ in 2026):
f_TPR date posted · f_WT workplace type · f_E experience level · f_JT job type · f_AL Easy Apply ·
f_EA under 10 applicants · sortBy (DD = most recent, R = most relevant).
"""
from dataclasses import dataclass, field, fields

from .locations import canonical
from .place_search import job_in_places

DATE_POSTED = {"24h": ("r86400", "Past 24 hours"), "week": ("r604800", "Past week"), "month": ("r2592000", "Past month")}
WORK_TYPE = {"onsite": ("1", "On-site"), "remote": ("2", "Remote"), "hybrid": ("3", "Hybrid")}
EXPERIENCE = {"internship": ("1", "Internship"), "entry": ("2", "Entry level"), "associate": ("3", "Associate"),
              "mid-senior": ("4", "Mid-Senior level"), "director": ("5", "Director"), "executive": ("6", "Executive")}
JOB_TYPE = {"full-time": ("F", "Full-time"), "part-time": ("P", "Part-time"), "contract": ("C", "Contract"),
            "temporary": ("T", "Temporary"), "internship": ("I", "Internship"), "other": ("O", "Other")}
SORT = {"recent": ("DD", "Most recent"), "relevant": ("R", "Most relevant")}


@dataclass
class SearchParams:
    keywords: str
    location: str = ""
    date_posted: str = ""                               # one of DATE_POSTED or ""
    work_types: list = field(default_factory=list)      # any of WORK_TYPE
    experience: list = field(default_factory=list)      # any of EXPERIENCE
    job_types: list = field(default_factory=list)       # any of JOB_TYPE
    easy_apply: bool = False
    under_10_applicants: bool = False
    sort: str = "recent"
    max_jobs: int = 10
    enrich_company: bool = True
    # Location chips ({text, id}) and what locations.resolve_many made of them (see ljt/place_search.plan)
    places: list = field(default_factory=list)
    place_names: list = field(default_factory=list)
    local_terms: list = field(default_factory=list)
    geo_id: str = ""
    region_facet: str = ""

    @classmethod
    def from_dict(cls, d):
        """Ignores keys from older saved runs that no longer exist."""
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in (d or {}).items() if k in names})



def plain_query(p: SearchParams):
    """Search text for LinkedIn's AI job search: just the role and the place(s), e.g. 'python developer in
    Hyderabad, Telangana, India'. LinkedIn turns 'in <place>' into its own location filter; all other filters are
    applied with LinkedIn's filter buttons (see ui_filters)."""
    q = p.keywords.strip()
    if p.place_names:
        q += " in " + " or ".join(p.place_names)
    elif p.location.strip():
        q += f" in {canonical(p.location)}"
    return " ".join(q.split())


def ui_filters(p: SearchParams):
    """The filters to set with LinkedIn's own filter buttons, by their on-screen names."""
    out = []
    if p.date_posted in DATE_POSTED:
        out.append({"pill": "Date posted", "options": [DATE_POSTED[p.date_posted][1]], "single": True})
    for pill, values, table in (("Experience level", p.experience, EXPERIENCE), ("Workplace type", p.work_types, WORK_TYPE),
                                ("Employment type", p.job_types, JOB_TYPE)):
        labels = [table[v][1] for v in values if v in table]
        if labels:
            out.append({"pill": pill, "options": labels})
    if p.easy_apply:
        out.append({"pill": "Easy Apply", "toggle": True})
    if p.under_10_applicants:
        out.append({"pill": "Under 10 applicants", "toggle": True})
    return out


def filter_mismatch(p: SearchParams, tags, location):
    """Checks a collected job against the filters that LinkedIn shows on the job itself. Returns the reason it does
    NOT match, or None. A filter is only checked when the job shows that kind of information (never guessed)."""
    tags = {t.lower() for t in tags or []}
    shown_work = tags & {"remote", "hybrid", "on-site"}
    want_work = {WORK_TYPE[w][1].lower() for w in p.work_types if w in WORK_TYPE}
    if want_work and shown_work and not (shown_work & want_work):
        return f"workplace is {'/'.join(sorted(shown_work))}, not {'/'.join(sorted(want_work))}"
    shown_type = tags & {"full-time", "part-time", "contract", "temporary", "internship", "other", "volunteer"}
    want_type = {JOB_TYPE[j][1].lower() for j in p.job_types if j in JOB_TYPE}
    if want_type and shown_type and not (shown_type & want_type):
        return f"job type is {'/'.join(sorted(shown_type))}, not {'/'.join(sorted(want_type))}"
    if p.easy_apply and tags and "easy apply" not in tags:
        return "not Easy Apply"
    names = p.place_names or ([p.location] if p.location.strip() else [])
    if not job_in_places(location, names, p.local_terms):
        return f"location is {location}, not {' / '.join(names)}"
    return None


def _codes(values, table):
    return ",".join(table[v][0] for v in values if v in table)


def _base_query(p: SearchParams):
    q = {"keywords": p.keywords, "location": p.location}
    if p.geo_id:
        q["geoId"] = p.geo_id
    if p.date_posted in DATE_POSTED:
        q["f_TPR"] = DATE_POSTED[p.date_posted][0]
    for key, values, table in (("f_WT", p.work_types, WORK_TYPE), ("f_E", p.experience, EXPERIENCE), ("f_JT", p.job_types, JOB_TYPE)):
        if _codes(values, table):
            q[key] = _codes(values, table)
    if p.easy_apply:
        q["f_AL"] = "true"
    if p.under_10_applicants:
        q["f_EA"] = "true"
    if p.sort in SORT:
        q["sortBy"] = SORT[p.sort][0]
    return q
