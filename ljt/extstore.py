"""Signed-in mode (browser extension): run state, de-duplication, limits and the 'what next' decision.

The extension does the browsing in the person's own signed-in browser. It asks this store for ONE task at a
time (search page -> job pages -> company About pages), so every limit is enforced here, in one place.
Nothing is guessed: values come only from what the extension read on the page.
"""
import datetime
import functools
import json
import os
import re
import threading
import uuid
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from . import clean, db
from .place_search import job_in_places, saved_like_terms
from .search import WORK_TYPE, SearchParams, _base_query, filter_mismatch, plain_query, ui_filters

LINKEDIN = os.environ.get("LJT_LINKEDIN_BASE", "https://www.linkedin.com")  # override only for offline tests
CARDS_PER_PAGE = 25
# A job counts as already collected only when it was read completely (older broken reads are re-read).
COMPLETE = "description IS NOT NULL AND description != '' AND title IS NOT NULL AND title != ''"

DEFAULT_LIMITS = {
    "max_jobs_per_run": 100,
    "max_search_pages_per_run": 6,
    "max_company_pages_per_run": 60,
    "search_pages_per_day": 30,
    "job_pages_per_day": 300,
    "company_pages_per_day": 200,
}

# Tables: see ljt/db.py (SQLite locally, PostgreSQL when hosted).


def ist_now():
    return datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=5, minutes=30)))


def company_key(url):
    """Canonical company page address, or '' when the link is not a company page."""
    m = re.search(r"linkedin\.com/company/([^/?#]+)", url or "")
    return f"https://www.linkedin.com/company/{m.group(1)}/" if m else ""


def _clean_id(v):
    return v if isinstance(v, str) and re.fullmatch(r"\d{4,20}", v) else None


def _locked(fn):
    """Runs a read method under the store lock (the SQLite connection is shared by all request threads)."""
    @functools.wraps(fn)
    def wrap(self, *a, **k):
        with self.lock:
            return fn(self, *a, **k)
    return wrap


class ExtStore:
    def __init__(self, path, limits=None):
        self.limits = {**DEFAULT_LIMITS, **(limits or {})}
        self.lock = threading.RLock()
        self.db = db.connect(path)                # file path -> SQLite, postgres:// URL -> PostgreSQL

    # ---------- helpers ----------
    def _one(self, sql, *a):
        with self.lock:                      # one shared connection: every access goes through the (re-entrant) lock
            return self.db.execute(sql, a).fetchone()

    def _run(self, run_id):
        return self._one("SELECT * FROM runs WHERE id=?", run_id)

    def _day(self):
        return ist_now().strftime("%Y-%m-%d")

    @_locked
    def used_today(self, kind):
        r = self._one("SELECT n FROM daily WHERE day=? AND kind=?", self._day(), kind)
        return r["n"] if r else 0

    def _count(self, run_id, kind):
        self.db.execute("INSERT INTO daily VALUES (?,?,1) ON CONFLICT(day,kind) DO UPDATE SET n=daily.n+1", (self._day(), kind))
        self.db.execute(f"UPDATE runs SET {kind}_pages={kind}_pages+1 WHERE id=?", (run_id,))

    def log(self, run_id, msg):
        with self.lock:
            self.db.execute("INSERT INTO log VALUES (?,?,?)", (run_id, ist_now().strftime("%H:%M:%S"), str(msg)[:500]))
            self.db.commit()

    def _finish(self, run_id, status, reason):
        cur = self.db.execute("UPDATE runs SET status=?, end_reason=? WHERE id=? AND status='running'", (status, reason, run_id))
        self.db.commit()
        if cur.rowcount:                       # log once, even if Stop is pressed several times
            self.log(run_id, f"Run ended: {reason}")
            return {"type": "done", "status": status, "reason": reason}
        run = self._run(run_id)
        return {"type": "done", "status": run["status"], "reason": run["end_reason"]}

    @_locked
    def collected(self, run_id):
        """Jobs that count toward the number asked for: read in this run + collected before and reused. A failed read does not count."""
        return self._one("SELECT COUNT(*) n FROM run_jobs WHERE run_id=? AND status IN ('done','reused')", run_id)["n"]

    def search_url(self, params, page, base=None):
        if base:  # the person's own LinkedIn search (all their filters kept); only the page offset changes
            parts = urlsplit(base)
            q = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k not in ("start", "currentJobId")]
            if page:
                q.append(("start", str(page * CARDS_PER_PAGE)))
            return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(q), ""))
        q = _base_query(params)
        if page:
            q["start"] = page * CARDS_PER_PAGE
        return f"{LINKEDIN}/jobs/search/?" + urlencode({k: v for k, v in q.items() if v not in ("", None)})

    @_locked
    def saved_jobs(self, places, limit=500):
        """Collected jobs located in any of `places`: each place's lower-case _local_terms (or the place itself)
        matched with SQL LIKE '%term%', all terms OR'd together."""
        terms = []
        for p in places:
            for t in saved_like_terms(p):
                if t and t not in terms:
                    terms.append(t)
        sql = f"SELECT job_id, title, company_name, location FROM jobs WHERE {COMPLETE}"
        args = []
        if terms:
            sql += " AND (" + " OR ".join("lower(location) LIKE ?" for _ in terms) + ")"
            args = [f"%{t}%" for t in terms]
        sql += f" ORDER BY collected_at DESC LIMIT {int(limit)}"
        with self.lock:
            return [dict(r) for r in self.db.execute(sql, args)]

    @_locked
    def latest_run(self):
        r = self._one("SELECT id FROM runs ORDER BY created DESC, rowid DESC LIMIT 1")
        return r["id"] if r else None

    @_locked
    def history(self, limit=100):
        """Past searches, newest first: what was searched, when, and how many jobs it collected."""
        out = []
        for r in self.db.execute("""SELECT r.id, r.created, r.params, r.target, r.status, r.end_reason,
                (SELECT COUNT(*) FROM run_jobs j WHERE j.run_id=r.id AND j.status IN ('done','reused')) n
                FROM runs r ORDER BY r.created DESC, r.rowid DESC LIMIT ?""", (int(limit),)):
            try:
                p = json.loads(r["params"] or "{}")
            except ValueError:
                p = {}
            out.append({"id": r["id"], "created": (r["created"] or "")[:16].replace("T", " "),
                        "keywords": p.get("keywords") or "", "places": " / ".join(p.get("place_names") or []) or p.get("location") or "",
                        "target": r["target"], "count": r["n"], "status": r["status"], "end_reason": r["end_reason"] or ""})
        return out

    @_locked
    def state(self, run_id):
        r = self._run(run_id)
        if not r:
            return None
        n = self._one("SELECT COUNT(*) n FROM run_jobs WHERE run_id=? AND status IN ('done','failed')", run_id)["n"]
        return {"state": r["status"], "end_reason": r["end_reason"], "read": n, "target": r["target"]}

    # ---------- dashboard ----------
    def start_run(self, params: SearchParams):
        search_base = self.search_url(params, 0)  # LinkedIn job search with the person's filters applied
        with self.lock:
            active = self._one("SELECT id FROM runs WHERE status='running'")
            if active:
                raise ValueError("Another signed-in run is still active. Stop it first.")
            run_id = uuid.uuid4().hex[:10]
            target = max(1, min(int(params.max_jobs), self.limits["max_jobs_per_run"]))
            self.db.execute("INSERT INTO runs (id, created, params, target, status, search_base) VALUES (?,?,?,?, 'running', ?)",
                            (run_id, ist_now().isoformat(timespec="seconds"), json.dumps(params.__dict__), target, search_base))
            self.db.commit()
            self.log(run_id, f"Run created: '{params.keywords}' in '{params.location or 'any location'}', {target} new jobs wanted.")
            if params.places:
                self.log(run_id, "Location: " + " or ".join(params.place_names) + (f" (LinkedIn geoId {params.geo_id})" if params.geo_id else " (no LinkedIn region filter)")
                         + (f"; only jobs whose location mentions: {', '.join(params.local_terms)}" if params.local_terms else ""))
                if params.region_facet:
                    self.log(run_id, f"REGION facet: {params.region_facet}")
            self.log(run_id, f"LinkedIn search: {search_base}")
            return run_id

    def stop(self, run_id):
        with self.lock:
            if self._run(run_id):
                self._finish(run_id, "stopped", "stopped by you")

    # ---------- extension: what next ----------
    def next_task(self, run_id):
        with self.lock:
            run = self._run(run_id)
            if not run:
                return {"type": "done", "status": "error", "reason": "unknown run"}
            if run["status"] != "running":
                return {"type": "done", "status": run["status"], "reason": run["end_reason"]}
            L = self.limits
            params = SearchParams.from_dict(json.loads(run["params"]))

            new = self.collected(run_id)
            if new < run["target"] and not run["search_done"]:
                if run["search_pages"] >= L["max_search_pages_per_run"]:
                    self.db.execute("UPDATE runs SET search_done=1 WHERE id=?", (run_id,))
                    self.log(run_id, f"Search stopped at {L['max_search_pages_per_run']} result pages (per-run limit).")
                elif self.used_today("search") >= L["search_pages_per_day"]:
                    self.db.execute("UPDATE runs SET search_done=1 WHERE id=?", (run_id,))
                    self.log(run_id, f"Search stopped: daily limit of {L['search_pages_per_day']} result pages reached.")
                else:
                    if self.used_today("job") >= L["job_pages_per_day"]:
                        return self._finish(run_id, "limit", f"daily limit of {L['job_pages_per_day']} job reads reached")
                    self._count(run_id, "search")
                    self.db.commit()
                    page = run["search_page"]
                    # The extension opens this results page, clicks each new card and reads the detail panel.
                    known = [r["job_id"] for r in self.db.execute(f"SELECT job_id FROM jobs WHERE {COMPLETE}")]
                    # ai_url + ui_filters: LinkedIn's newer AI job search ignores the filter parameters. There the
                    # extension searches role + place, then sets each filter with LinkedIn's own filter buttons.
                    return {"type": "search", "mode": "pane", "page": page, "known_ids": known,
                            "url": self.search_url(params, page, run["search_base"]),
                            "ai_url": f"{LINKEDIN}/jobs/search-results/?" + urlencode({"keywords": plain_query(params)}),
                            "ui_filters": ui_filters(params)}

            if params.enrich_company:
                comp = self._one("""SELECT DISTINCT j.company_url u FROM run_jobs r JOIN jobs j ON j.job_id=r.job_id
                    LEFT JOIN companies c ON c.url=j.company_url
                    WHERE r.run_id=? AND j.company_url!='' AND j.company_url IS NOT NULL AND c.url IS NULL LIMIT 1""", run_id)
                if comp:
                    if run["company_pages"] >= L["max_company_pages_per_run"]:
                        return self._finish(run_id, "limit", f"per-run limit of {L['max_company_pages_per_run']} company pages reached")
                    if self.used_today("company") >= L["company_pages_per_day"]:
                        return self._finish(run_id, "limit", f"daily limit of {L['company_pages_per_day']} company pages reached")
                    self.db.execute("INSERT INTO companies (url, status, note) VALUES (?, 'reading', '')", (comp["u"],))
                    self._count(run_id, "company")
                    self.db.commit()
                    page = comp["u"].replace("https://www.linkedin.com", LINKEDIN, 1) + "about/"
                    return {"type": "company", "company_url": comp["u"], "url": page}

            got = self.collected(run_id)
            return self._finish(run_id, "done", f"finished: {got} of {run['target']} jobs collected" +
                                ("" if got >= run["target"] else " (LinkedIn has no more matching jobs for this search)"))

    def more_companies(self, run_id, k):
        """Up to k more company pages to read at the same time as the one next_task just gave (same limits).
        Never ends the run: when there are none, an empty list comes back and next_task decides."""
        out = []
        with self.lock:
            run = self._run(run_id)
            if not run or run["status"] != "running" or not SearchParams.from_dict(json.loads(run["params"])).enrich_company:
                return out
            L = self.limits
            for _ in range(max(0, min(int(k), 5))):
                run = self._run(run_id)
                if run["company_pages"] >= L["max_company_pages_per_run"] or self.used_today("company") >= L["company_pages_per_day"]:
                    break
                comp = self._one("""SELECT DISTINCT j.company_url u FROM run_jobs r JOIN jobs j ON j.job_id=r.job_id
                    LEFT JOIN companies c ON c.url=j.company_url
                    WHERE r.run_id=? AND j.company_url!='' AND j.company_url IS NOT NULL AND c.url IS NULL LIMIT 1""", run_id)
                if not comp:
                    break
                self.db.execute("INSERT INTO companies (url, status, note) VALUES (?, 'reading', '')", (comp["u"],))
                self._count(run_id, "company")
                self.db.commit()
                out.append({"type": "company", "company_url": comp["u"],
                            "url": comp["u"].replace("https://www.linkedin.com", LINKEDIN, 1) + "about/"})
        return out

    # ---------- extension: results (each job is read from the detail panel after clicking its card) ----------
    def add_card(self, run_id, job_id, data=None, error=None):
        """Saves one job read from the results list. Returns True if the extension may read another card."""
        with self.lock:
            run = self._run(run_id)
            jid = _clean_id(str(job_id or ""))
            if not run or run["status"] != "running" or not jid:
                return False
            new = self.collected(run_id)
            if self._one("SELECT 1 FROM run_jobs WHERE run_id=? AND job_id=?", run_id, jid):
                return new < run["target"]
            if new >= run["target"]:
                return False
            if self.used_today("job") >= self.limits["job_pages_per_day"]:
                self._finish(run_id, "limit", f"daily limit of {self.limits['job_pages_per_day']} job reads reached")
                return False
            seq = self._one("SELECT COALESCE(MAX(seq),0) s FROM run_jobs WHERE run_id=?", run_id)["s"] + 1
            d = data or {}
            mismatch = None if error else filter_mismatch(SearchParams.from_dict(json.loads(run["params"])),
                                                          d.get("pane_tags"), d.get("location"))
            if mismatch:  # LinkedIn showed a job outside the requested filters: not saved, not counted
                self.db.execute("INSERT INTO run_jobs VALUES (?,?, 'skipped', ?, ?)", (run_id, jid, mismatch[:200], seq))
                self._count(run_id, "job")
                self.db.commit()
                self.log(run_id, f"Job {jid}: skipped, does not match your filters ({mismatch}).")
                return True
            self.db.execute("""INSERT INTO jobs (job_id, title, company_name, company_url, location, description, contacts,
                job_industry, job_size, notes, collected_at, posted, tags, last_seen) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(job_id) DO UPDATE SET title=excluded.title, company_name=excluded.company_name,
                company_url=excluded.company_url, location=excluded.location, description=excluded.description,
                contacts=excluded.contacts, job_industry=excluded.job_industry, job_size=excluded.job_size, notes=excluded.notes,
                posted=excluded.posted, tags=excluded.tags, last_seen=excluded.last_seen""",
                            (jid, d.get("job_title") or "", d.get("company_name") or "", company_key(d.get("company_url")),
                             d.get("location") or "", None if error else (d.get("job_description") or ""),
                             d.get("contact_profile_links") or "", d.get("company_industry") or "", d.get("company_size") or "",
                             d.get("data_notes") or "", ist_now().isoformat(timespec="seconds"), d.get("posted") or "",
                             json.dumps([t for t in (d.get("pane_tags") or []) if isinstance(t, str)][:10]),
                             ist_now().isoformat(timespec="seconds")))
            self.db.execute("INSERT INTO run_jobs VALUES (?,?,?,?,?)",
                            (run_id, jid, "failed" if error else "done", str(error or "")[:200], seq))
            ckey = company_key(d.get("company_url"))
            if not error and ckey and d.get("box_industry") and d.get("company_size") and \
                    not self._one("SELECT 1 FROM companies WHERE url=?", ckey):
                # The job panel's "About the company" box shows both values: no need to open the company page.
                self.db.execute("INSERT INTO companies VALUES (?,?,?, 'ok', ?, ?)",
                                (ckey, d["box_industry"], d["company_size"], "from the job page (About the company)",
                                 ist_now().isoformat(timespec="seconds")))
            self._count(run_id, "job")
            self.db.commit()
            self.log(run_id, f"Job {jid}: " + (f"not read ({error})." if error else
                     f"read ({(d.get('job_title') or '')[:60]} at {(d.get('company_name') or '')[:40]})."))
            return self.collected(run_id) < run["target"]

    @_locked
    def quick_mismatch(self, run_id, tags, location):
        """The filter a job breaks, judged only from what its panel shows first (labels + location); None if it
        matches or nothing is shown yet. Same rule as add_card, so a quick skip never differs from a full read."""
        run = self._run(run_id)
        if not run or run["status"] != "running":
            return None
        tags = [t for t in tags if isinstance(t, str)][:10]
        return filter_mismatch(SearchParams.from_dict(json.loads(run["params"])), tags, location)

    def precheck(self, run_id, cards):
        """Before clicking: drop cards already collected or whose card shows a location outside the request.
        Returns the job IDs worth opening (in order). Skipped cards are not opened and use no daily job reads."""
        with self.lock:
            run = self._run(run_id)
            if not run or run["status"] != "running":
                return []
            p = SearchParams.from_dict(json.loads(run["params"]))
            names = p.place_names or ([p.location] if p.location else [])
            seq = self._one("SELECT COALESCE(MAX(seq),0) s FROM run_jobs WHERE run_id=?", run_id)["s"]
            keep = []
            for c in cards or []:
                jid = _clean_id(str(c.get("id") or ""))
                if not jid or self._one("SELECT 1 FROM run_jobs WHERE run_id=? AND job_id=?", run_id, jid):
                    continue
                if self._one(f"SELECT 1 FROM jobs WHERE job_id=? AND {COMPLETE}", jid):
                    if self.collected(run_id) < run["target"]:   # collected before: listed again, not re-opened
                        seq += 1
                        self.db.execute("INSERT INTO run_jobs VALUES (?,?, 'reused', 'collected in an earlier run (not re-read)', ?)",
                                        (run_id, jid, seq))
                    self.db.execute("UPDATE jobs SET last_seen=? WHERE job_id=?", (ist_now().isoformat(timespec="seconds"), jid))
                    continue
                loc = str(c.get("location") or "")
                # LinkedIn's AI search pads results with related jobs that ignore the Workplace filter. The card already
                # says "Bengaluru (Hybrid)", so a wrong workplace is skipped here instead of opening the job (~9 s each).
                shown = re.search(r"\((remote|hybrid|on-site)\)", loc, re.I)
                want = {WORK_TYPE[w][1].lower() for w in p.work_types if w in WORK_TYPE}
                if shown and want and shown.group(1).lower() not in want:
                    seq += 1
                    self.db.execute("INSERT INTO run_jobs VALUES (?,?, 'skipped', ?, ?)",
                                    (run_id, jid, f"workplace is {shown.group(1).lower()}, not {'/'.join(sorted(want))}", seq))
                    self.log(run_id, f"Job {jid}: skipped without opening (card says {shown.group(1)}).")
                    continue
                # Only a real place line ("Pune, Maharashtra, India", "India (Remote)") is trusted here; a company line
                # such as "Accenture in India" is not a location, so that job is opened and checked on its own page.
                place_like = ("," in loc or bool(shown) or
                              (bool(re.fullmatch(r"[A-Za-z .'-]+", loc)) and len(loc.split()) <= 3 and " in " not in f" {loc.lower()} "))
                if loc and names and place_like and not job_in_places(loc, names, p.local_terms):
                    seq += 1
                    self.db.execute("INSERT INTO run_jobs VALUES (?,?, 'skipped', ?, ?)",
                                    (run_id, jid, f"location is {loc}, not {' / '.join(names)}"[:200], seq))
                    self.log(run_id, f"Job {jid}: skipped without opening (card location {loc}).")
                    continue
                keep.append(jid)
            self.db.commit()
            return keep

    def finish_search_page(self, run_id, page, ids, n_new, has_more):
        with self.lock:
            run = self._run(run_id)
            if not run:
                return
            reused = self._one("SELECT COUNT(*) n FROM run_jobs WHERE run_id=? AND status='reused'", run_id)["n"]
            empty = run["empty_pages"] + 1 if not n_new else 0
            done = (not has_more) or not ids or empty >= 2 or self.collected(run_id) >= run["target"]
            self.db.execute("UPDATE runs SET search_page=search_page+1, search_done=?, empty_pages=? WHERE id=?",
                            (1 if done else 0, empty, run_id))
            self.db.commit()
            self.log(run_id, f"Result page {page + 1}: {len(ids or [])} jobs listed, {n_new} read"
                     + (f", {reused} taken from earlier runs so far" if reused else "") + ".")

    def add_company_result(self, run_id, company_url, data):
        with self.lock:
            key = company_key(company_url)
            if not key:
                return
            d = data or {}
            self.db.execute("""INSERT INTO companies (url, industry, size, status, note, read_at) VALUES (?,?,?,?,?,?)
                ON CONFLICT(url) DO UPDATE SET industry=excluded.industry, size=excluded.size, status=excluded.status,
                note=excluded.note, read_at=excluded.read_at""",
                            (key, d.get("industry") or "", d.get("size") or "", d.get("status") or "not found",
                             d.get("note") or "", ist_now().isoformat(timespec="seconds")))
            self.db.commit()
            self.log(run_id, f"Company {key.rsplit('/', 2)[-2]}: {d.get('status') or 'not found'}"
                     + (f" (industry: {d.get('industry') or '-'}, size: {d.get('size') or '-'})" if d.get("status") == "ok" else f" - {d.get('note') or ''}"))

    def linkedin_stop(self, run_id, reason, url=""):
        with self.lock:
            self.log(run_id, f"LinkedIn warning on {url[:120]}: {reason}")
            return self._finish(run_id, "blocked", f"LinkedIn showed a warning: {reason}. The tab was left open for you.")

    # ---------- output ----------
    @_locked
    def rows(self, run_id, limit=None):
        """Result rows, cleaned for display/export (see ljt/clean.py). Data Notes explain every blank, briefly."""
        q = """SELECT r.status rstatus, r.note rnote, j.*, c.industry c_ind, c.size c_size, c.status c_status, c.note c_note
               FROM run_jobs r JOIN jobs j ON j.job_id=r.job_id LEFT JOIN companies c ON c.url=j.company_url
               WHERE r.run_id=? AND r.status NOT IN ('skipped','failed') ORDER BY r.seq""" + (f" LIMIT {int(limit)}" if limit else "")
        return self._build_rows(self.db.execute(q, (run_id,)))

    @_locked
    def rows_filtered(self, run_id="", text="", location="", date_from="", date_to=""):
        """Every saved job (or one run's), filtered. Several locations or words are separated with |.
        Dates are YYYY-MM-DD (IST) and match the day the job was first collected."""
        where, args = [COMPLETE.replace("description", "j.description").replace("title", "j.title")], []
        if run_id:
            where.append("j.job_id IN (SELECT job_id FROM run_jobs WHERE run_id=? AND status!='skipped')"); args.append(run_id)
        for col, val in (("(j.title || ' ' || j.company_name || ' ' || j.description)", text), ("j.location", location)):
            terms = [t.strip() for t in (val or "").split("|") if t.strip()]
            if col == "j.location":   # "Bengaluru, Karnataka, India" also matches jobs saved as "Bangalore" / "Bengaluru"
                terms = list(dict.fromkeys(x for t in terms for x in saved_like_terms(t)))
            if terms:
                where.append("(" + " OR ".join(f"{col} LIKE ?" for _ in terms) + ")"); args += [f"%{t}%" for t in terms]
        if date_from:
            where.append("substr(j.collected_at,1,10) >= ?"); args.append(date_from[:10])
        if date_to:
            where.append("substr(j.collected_at,1,10) <= ?"); args.append(date_to[:10])
        q = f"""SELECT 'done' rstatus, '' rnote, j.*, c.industry c_ind, c.size c_size, c.status c_status, c.note c_note
               FROM jobs j LEFT JOIN companies c ON c.url=j.company_url WHERE {' AND '.join(where)}
               ORDER BY j.collected_at DESC"""
        return self._build_rows(self.db.execute(q, args))

    @_locked
    def job_roles(self):
        """job_id -> the searched roles (keywords) that collected it, oldest first."""
        out = {}
        for r in self.db.execute("""SELECT rj.job_id, r.params FROM run_jobs rj JOIN runs r ON r.id=rj.run_id
                                    WHERE rj.status IN ('done','reused') ORDER BY r.created"""):
            try:
                kw = (json.loads(r["params"] or "{}").get("keywords") or "").strip()
            except ValueError:
                kw = ""
            if kw and kw not in out.setdefault(r["job_id"], []):
                out[r["job_id"]].append(kw)
        return out

    @_locked
    def rows_by_ids(self, ids):
        """Saved jobs with these ids, in the given order (export of what the Results page shows)."""
        ids = [str(i) for i in ids if str(i).isdigit()][:5000]
        if not ids:
            return []
        rows = {r["job_id"]: r for r in self.rows_filtered()}
        return [rows[i] for i in ids if i in rows]

    def _build_rows(self, cursor):
        out = []
        for x in cursor:
            notes = []
            if x["rstatus"] in ("queued", "reading", "failed"):
                notes.append("Job not read" + (f" ({x['rnote']})" if x["rnote"] else " (run ended first)"))
            if x["rstatus"] == "reused":
                notes.append("Collected in an earlier run")
            industry, source = "", ""
            if x["c_status"] == "ok" and x["c_ind"]:
                industry = x["c_ind"]
                source = "job page (About the company)" if (x["c_note"] or "").startswith("from the job page") else "company page"
            elif x["job_industry"]:
                industry, source = x["job_industry"], "job posting"
            size = x["c_size"] if x["c_status"] == "ok" and x["c_size"] else (x["job_size"] or "")
            if not industry or not size:
                if not x["company_url"]:
                    why = "no company page link on the job"
                elif x["c_status"] in (None, "reading"):
                    why = "company page not read"
                elif x["c_status"] == "error":
                    why = "company page didn't load"
                elif x["c_status"] != "ok":
                    why = "not shown on the company page"
                else:
                    why = "not shown by LinkedIn"
                what = "industry & size" if not industry and not size else ("industry" if not industry else "size")
                notes.append(f"Company {what} not available ({why})")
            if x["rstatus"] == "done":
                if not x["description"]:
                    notes.append("No description shown")
                if not x["contacts"]:
                    notes.append("No hiring contact shown")
            try:
                tags = json.loads(x["tags"] or "[]")
            except (ValueError, TypeError):
                tags = []
            place, wp = clean.location(x["location"])
            out.append({
                "job_id": x["job_id"], "job_title": clean.title(x["title"]), "company_name": (x["company_name"] or "").strip(),
                "company_industry": industry, "industry_source": source, "company_size": clean.size(size),
                "contact_profile_links": clean.contacts(x["contacts"]), "job_description": clean.description(x["description"]),
                "location": place, "workplace": clean.workplace(wp, tags), "employment_type": clean.employment(tags),
                "posted_date": clean.posted(x["posted"]),
                "job_url": f"https://www.linkedin.com/jobs/view/{x['job_id']}/", "company_url": x["company_url"] or "",
                "data_notes": "; ".join(n for n in notes if n),
                "first_found": x["collected_at"] or "", "last_seen": x["last_seen"] or x["collected_at"] or "",
            })
        return out

    @_locked
    def status(self, run_id):
        with self.lock:
            run = self._run(run_id)
            if not run:
                return None
            c = lambda st: self._one("SELECT COUNT(*) n FROM run_jobs WHERE run_id=? AND status=?", run_id, st)["n"]
            log = [f"{r['ts']}  {r['msg']}" for r in self.db.execute(
                "SELECT ts, msg FROM log WHERE run_id=? ORDER BY rowid DESC LIMIT 40", (run_id,))][::-1]
            total = self._one("SELECT COUNT(*) n FROM run_jobs WHERE run_id=? AND status NOT IN ('skipped','failed')", run_id)["n"]
            return {
                "id": run_id, "state": run["status"], "end_reason": run["end_reason"], "target": run["target"],
                "jobs": {"read": c("done"), "queued": c("queued") + c("reading"), "failed": c("failed"), "reused": c("reused"),
                         "skipped": c("skipped"), "total": total},
                "pages": {"search": run["search_pages"], "job": run["job_pages"], "company": run["company_pages"]},
                "today": {k: {"used": self.used_today(k), "limit": self.limits[f"{k}_pages_per_day"]} for k in ("search", "job", "company")},
                "limits": self.limits, "log": log, "count": total, "preview": self.rows(run_id, limit=200),
                "search": self._search_label(run),
                "created": run["created"],
                "ended": self._one("SELECT ts FROM log WHERE run_id=? AND msg LIKE 'Run ended:%' ORDER BY rowid DESC LIMIT 1", run_id)["ts"]
                         if run["status"] != "running" and self._one("SELECT 1 FROM log WHERE run_id=? AND msg LIKE 'Run ended:%'", run_id) else None,
            }

    @staticmethod
    def _search_label(run):
        """'java developer · Bengaluru, Karnataka, India · 2026-11-12 11:28' for the results heading."""
        try:
            p = json.loads(run["params"] or "{}")
        except ValueError:
            p = {}
        places = " / ".join(p.get("place_names") or []) or p.get("location") or ""
        return " · ".join(x for x in (p.get("keywords") or "", places, (run["created"] or "")[:16].replace("T", " ")) if x)
