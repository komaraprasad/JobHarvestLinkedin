"""HTTP API. The dashboard starts/stops runs and downloads results; the extension asks for the next task and
sends back what it read."""
import json
import os
import re

from flask import Blueprint, jsonify, request, send_file

from . import export
from .extstore import ExtStore
from .place_search import plan, suggest
from .search import DATE_POSTED, EXPERIENCE, JOB_TYPE, SORT, WORK_TYPE, SearchParams


def _ok_id(rid):
    return isinstance(rid, str) and rid.isalnum() and len(rid) <= 32


def places_from_form(f):
    """Location chips as [{text, id}] (hidden field 'places', JSON). Falls back to a plain 'location' text."""
    try:
        raw = json.loads(f.get("places") or "[]")
    except ValueError:
        raw = []
    places = []
    for p in raw if isinstance(raw, list) else []:
        if isinstance(p, dict) and str(p.get("text") or "").strip():
            gid = str(p.get("id") or "")
            places.append({"text": str(p["text"]).strip()[:120], "id": gid if gid.isdigit() else ""})
    if not places and f.get("location", "").strip():
        places = [{"text": f.get("location", "").strip()[:120], "id": ""}]
    return places[:10]


def params_from_form(f):
    pick = lambda name, table: [v for v in f.getlist(name) if v in table]
    places = places_from_form(f)
    loc = plan(places) if places else {"names": [], "local_terms": [], "geo_id": "", "location_text": "", "facet": ""}
    return SearchParams(
        keywords=f.get("keywords", "").strip(), location=loc["location_text"],
        places=places, place_names=loc["names"], local_terms=loc["local_terms"], geo_id=loc["geo_id"],
        region_facet=loc["facet"],
        date_posted=f.get("date_posted", "") if f.get("date_posted", "") in DATE_POSTED else "",
        work_types=pick("work_types", WORK_TYPE), experience=pick("experience", EXPERIENCE), job_types=pick("job_types", JOB_TYPE),
        easy_apply=bool(f.get("easy_apply")), under_10_applicants=bool(f.get("under_10_applicants")),
        sort=f.get("sort", "recent") if f.get("sort", "recent") in SORT else "recent",
        max_jobs=max(1, min(int(f.get("max_jobs") or 10), 100)), enrich_company=bool(f.get("enrich")),
    )


def create_blueprint(store: ExtStore, out_dir):
    bp = Blueprint("ext", __name__, url_prefix="/api/ext")

    def body():
        return request.get_json(silent=True) or {}

    # ---------- dashboard ----------
    @bp.post("/start")
    def start():
        params = params_from_form(request.form)
        if not params.keywords:
            return jsonify(error="Role / keywords is required"), 400
        try:
            rid = store.start_run(params)
        except ValueError as exc:
            return jsonify(error=str(exc)), 409
        return jsonify(id=rid, url=store.search_url(params, 0))

    @bp.post("/stop/<rid>")
    def stop(rid):
        if _ok_id(rid):
            store.stop(rid)
        return jsonify(ok=True)

    @bp.get("/status/<rid>")
    def status(rid):
        st = store.status(rid) if _ok_id(rid) else None
        return (jsonify(st), 200) if st else (jsonify(error="unknown run"), 404)

    @bp.get("/locations/suggest")
    def location_suggest():
        """Suggestions for the location box (alias_suggestions + the location directory; LinkedIn is not called)."""
        return jsonify(suggest(request.args.get("q", "")))

    @bp.get("/saved_jobs")
    def saved_jobs():
        """Already-collected jobs in any of the given places (?place=Bangalore&place=Pune), via SQL LIKE."""
        places = [p for p in request.args.getlist("place") if p.strip()][:10]
        return jsonify(store.saved_jobs(places))

    @bp.get("/history")
    def history():
        return jsonify(store.history())

    @bp.get("/latest")
    def latest():
        rid = store.latest_run()
        return jsonify(id=rid, **(store.state(rid) or {}))

    @bp.get("/download/<rid>/<kind>")
    def download(rid, kind):
        if kind not in ("xlsx", "csv") or not _ok_id(rid) or not store.status(rid):
            return "not found", 404
        path = os.path.join(out_dir, f"linkedin_jobs_{rid}.{kind}")
        (export.write_xlsx if kind == "xlsx" else export.write_csv)(store.rows(rid), path)
        return send_file(path, as_attachment=True, download_name=f"linkedin_jobs.{kind}")

    @bp.get("/browse")
    def browse():
        """The same jobs the filtered/full download would contain, as JSON for viewing (first 200)."""
        a = request.args
        dates = [a.get(k, "") for k in ("date_from", "date_to")]
        if any(d and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", d) for d in dates):
            return jsonify(error="dates must be YYYY-MM-DD"), 400
        rows = store.rows_filtered("", a.get("text", "")[:200], a.get("location", "")[:200], *dates)
        keep = ("job_title", "company_name", "location", "company_industry", "company_size", "job_url", "first_found")
        return jsonify(total=len(rows), rows=[{k: r.get(k, "") for k in keep} for r in rows[:200]])

    @bp.get("/export.<kind>")
    def export_filtered(kind):
        """All saved jobs, or a filtered set: ?run_id=&text=&location=&date_from=&date_to= (several values with |)."""
        if kind not in ("xlsx", "csv"):
            return "not found", 404
        a = request.args
        rid = a.get("run_id", "")
        if rid and not _ok_id(rid):
            return "bad run id", 400
        dates = [a.get(k, "") for k in ("date_from", "date_to")]
        if any(d and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", d) for d in dates):
            return "dates must be YYYY-MM-DD", 400
        rows = store.rows_filtered(rid, a.get("text", "")[:200], a.get("location", "")[:200], *dates)
        path = os.path.join(out_dir, f"linkedin_jobs_export.{kind}")
        (export.write_xlsx if kind == "xlsx" else export.write_csv)(rows, path)
        return send_file(path, as_attachment=True, download_name=f"linkedin_jobs_all.{kind}")

    @bp.get("/results")
    def results():
        """Every saved job for the Results page (filtered in the page), with the role searches that found it."""
        roles = store.job_roles()
        keep = ("job_id", "job_title", "company_name", "location", "workplace", "employment_type", "company_industry",
                "company_size", "company_url", "job_url", "contact_profile_links", "data_notes", "first_found", "last_seen")
        rows = [dict({k: r.get(k, "") for k in keep}, roles=roles.get(r["job_id"], []),
                     description=(r.get("job_description") or "")[:600]) for r in store.rows_filtered()]
        return jsonify(rows=rows, roles=sorted({k for v in roles.values() for k in v}, key=str.lower))

    @bp.post("/export_ids.<kind>")
    def export_ids(kind):
        """Excel / CSV of exactly the jobs the Results page shows (ids in the body, form field 'ids', comma separated)."""
        if kind not in ("xlsx", "csv"):
            return "not found", 404
        ids = [i for i in (request.form.get("ids") or "").split(",") if i.strip()]
        path = os.path.join(out_dir, f"linkedin_jobs_selection.{kind}")
        (export.write_xlsx if kind == "xlsx" else export.write_csv)(store.rows_by_ids(ids), path)
        return send_file(path, as_attachment=True, download_name=f"linkedin_jobs_results.{kind}")

    # ---------- extension ----------
    @bp.get("/state/<rid>")
    def state(rid):
        st = store.state(rid) if _ok_id(rid) else None
        return (jsonify(st), 200) if st else (jsonify(error="unknown run"), 404)

    @bp.get("/next/<rid>")
    def next_task(rid):
        return jsonify(store.next_task(rid) if _ok_id(rid) else {"type": "done", "reason": "bad run id"})

    @bp.get("/more_companies/<rid>")
    def more_companies(rid):
        if not _ok_id(rid):
            return jsonify([])
        return jsonify(store.more_companies(rid, request.args.get("k", "2")))

    @bp.post("/card/<rid>")
    def card(rid):
        b = body()
        go_on = store.add_card(rid, b.get("job_id"), b.get("data"), b.get("error")) if _ok_id(rid) else False
        return jsonify(continue_=go_on)

    @bp.post("/precheck/<rid>")
    def precheck(rid):
        cards = (body().get("cards") or [])[:100]
        return jsonify(read=store.precheck(rid, cards) if _ok_id(rid) else [])

    @bp.post("/quickcheck/<rid>")
    def quickcheck(rid):
        """As soon as a job's panel shows its labels (Remote, Contract, ...): does it break the filters? Lets the
        extension skip it before reading the description, hiring team and company box."""
        b = body()
        return jsonify(mismatch=store.quick_mismatch(rid, b.get("tags") or [], str(b.get("location") or ""))
                       if _ok_id(rid) else None)

    @bp.post("/page_done/<rid>")
    def page_done(rid):
        b = body()
        if _ok_id(rid):
            store.finish_search_page(rid, int(b.get("page") or 0), b.get("ids") or [], int(b.get("n_new") or 0), bool(b.get("has_more")))
        return jsonify(ok=True)

    @bp.post("/company_result/<rid>")
    def company_result(rid):
        b = body()
        if _ok_id(rid):
            store.add_company_result(rid, b.get("company_url"), b.get("data"))
        return jsonify(ok=True)

    @bp.post("/linkedin_stop/<rid>")
    def linkedin_stop(rid):
        b = body()
        if _ok_id(rid):
            store.linkedin_stop(rid, str(b.get("reason") or "unknown warning")[:200], str(b.get("url") or ""))
        return jsonify(ok=True)

    @bp.post("/debug/<rid>")
    def debug(rid):
        """Page snapshot sent by the extension when a page doesn't look as expected. Kept on this PC only."""
        b = body()
        kind = "".join(ch for ch in str(b.get("kind") or "page") if ch.isalnum() or ch == "-")[:30] or "page"
        if not _ok_id(rid):
            return jsonify(error="bad run id"), 400
        folder = os.path.join(out_dir, "debug")
        os.makedirs(folder, exist_ok=True)
        base = os.path.join(folder, f"{rid}_{kind}")
        with open(base + ".html", "w", encoding="utf-8") as f:
            f.write(str(b.get("html") or ""))
        with open(base + ".json", "w", encoding="utf-8") as f:
            json.dump({k: v for k, v in b.items() if k != "html"}, f, indent=2)
        return jsonify(ok=True, file=os.path.relpath(base + ".html", os.path.dirname(out_dir)))

    @bp.post("/log/<rid>")
    def log(rid):
        if _ok_id(rid):
            store.log(rid, str(body().get("msg") or "")[:300])
        return jsonify(ok=True)

    return bp
