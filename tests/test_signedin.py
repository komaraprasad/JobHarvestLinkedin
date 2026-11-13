"""Server logic for the dashboard + extension flow. Offline: the 'extension' here is the Flask test client."""
from urllib.parse import parse_qs, urlsplit

import pytest

from app import create_app
from ljt.extstore import company_key


@pytest.fixture
def mk(tmp_path):
    def make(**limits):
        app = create_app(db_path=str(tmp_path / f"e{len(limits)}.sqlite"), limits=limits or None, out_dir=str(tmp_path))
        return app.test_client()
    return make


FORM = {"keywords": "Remote Java developer", "location": "Greater Bengaluru Area", "date_posted": "24h",
        "work_types": ["remote", "hybrid"], "experience": ["mid-senior"], "job_types": ["full-time"],
        "easy_apply": "on", "under_10_applicants": "on", "sort": "recent", "max_jobs": "3", "enrich": "on"}


def start(c, **over):
    r = c.post("/api/ext/start", data={**FORM, **over})
    assert r.status_code == 200, r.get_json()
    return r.get_json()["id"]


def nxt(c, rid):
    return c.get(f"/api/ext/next/{rid}").get_json()


def job(i, comp="acme", contacts=""):
    return {"job_title": f"Java Dev {i}", "company_name": comp.title(), "company_url": f"https://www.linkedin.com/company/{comp}/life/",
            "job_description": "Build APIs", "contact_profile_links": contacts, "location": "Bengaluru (Remote)"}


def card(c, rid, i, comp="acme", **kw):
    return c.post(f"/api/ext/card/{rid}", json={"job_id": str(4000000000 + i), "data": job(i, comp, **kw)}).get_json()["continue_"]


def test_dashboard_filters_become_the_linkedin_search_address(mk):
    c = mk()
    r = c.post("/api/ext/start", data=FORM).get_json()
    q = parse_qs(urlsplit(r["url"]).query)
    assert r["url"].startswith("https://www.linkedin.com/jobs/search/?")
    assert q["keywords"] == ["Remote Java developer"] and q["location"] == ["Greater Bengaluru Area"]
    assert q["f_TPR"] == ["r86400"] and q["f_WT"] == ["2,3"] and q["f_E"] == ["4"] and q["f_JT"] == ["F"]
    assert q["f_AL"] == ["true"] and q["f_EA"] == ["true"] and q["sortBy"] == ["DD"]
    t = nxt(c, r["id"])
    assert t["type"] == "search" and t["mode"] == "pane" and t["url"] == r["url"] and t["known_ids"] == []


def test_ai_search_gets_role_and_place_then_linkedin_filter_buttons(mk):
    c = mk()
    rid = start(c)
    t = nxt(c, rid)
    q = parse_qs(urlsplit(t["ai_url"]).query)["keywords"][0]
    assert t["ai_url"].startswith("https://www.linkedin.com/jobs/search-results/?")
    assert q == "Remote Java developer in Greater Bengaluru Area"
    assert t["ui_filters"] == [
        {"pill": "Date posted", "options": ["Past 24 hours"], "single": True},
        {"pill": "Experience level", "options": ["Mid-Senior level"]},
        {"pill": "Workplace type", "options": ["Remote", "Hybrid"]},
        {"pill": "Employment type", "options": ["Full-time"]},
        {"pill": "Easy Apply", "toggle": True},
        {"pill": "Under 10 applicants", "toggle": True}]


def test_filter_check_uses_only_what_the_job_shows():
    from ljt.search import SearchParams, filter_mismatch
    p = SearchParams("java", location="india", work_types=["remote"], job_types=["part-time"], easy_apply=True)
    assert filter_mismatch(p, ["Remote", "Part-time", "Easy Apply"], "India (Remote)") is None
    assert "workplace is hybrid" in filter_mismatch(p, ["Hybrid", "Part-time", "Easy Apply"], "India")
    assert "job type is full-time" in filter_mismatch(p, ["Remote", "Full-time", "Easy Apply"], "India")
    assert filter_mismatch(p, ["Remote", "Part-time"], "India") == "not Easy Apply"
    assert "location is Berlin" in filter_mismatch(p, ["Remote", "Part-time", "Easy Apply"], "Berlin, Germany")
    assert filter_mismatch(p, [], "") is None                     # nothing shown -> nothing judged
    loose = SearchParams("java", location="Greater Bengaluru Area")
    assert filter_mismatch(loose, [], "Bengaluru, Karnataka, India") is None


@pytest.mark.parametrize("requested, job_location, expected", [
    # the exact locations wrongly skipped in the live run of 2026-11-11 (requested 'india')
    ("india", "Bengaluru (Hybrid)", True), ("india", "Bengaluru (On-site)", True), ("india", "Bengaluru", True),
    ("india", "India (Remote)", True), ("India", "Gurugram, Haryana", True), ("india", "Karnataka, India", True),
    ("india", "Bangalore Urban, Karnataka", True), ("Bharat", "Pune, Maharashtra", True),
    ("india", "Indore, Madhya Pradesh", True),          # city not in the list, no other country named: kept
    ("india", "Berlin, Germany", False), ("india", "Dubai, United Arab Emirates", False),
    # city and metro requests
    ("bangalore", "Bengaluru, Karnataka, India (Hybrid)", True), ("Bengaluru", "Bangalore Urban, Karnataka", True),
    ("Greater Bengaluru Area", "Bengaluru (Hybrid)", True), ("bangalore", "Pune, Maharashtra, India", False),
    ("gurgaon", "Gurugram, Haryana, India", True), ("Hyderabad", "Secunderabad, Telangana", True),
    ("usa", "Austin, Texas, United States", True), ("usa", "Bengaluru, Karnataka, India", False),
    ("", "anywhere", True), ("india", "", True),
])
def test_job_location_matching(requested, job_location, expected):
    from ljt.job_location import job_in_requested_place
    assert job_in_requested_place(requested, job_location) is expected


def test_job_outside_filters_is_skipped_not_counted_not_exported(mk):
    c = mk()
    rid = start(c, max_jobs="2", easy_apply="", under_10_applicants="", location="india", job_types=[], work_types=["remote"])
    nxt(c, rid)
    hybrid = {**job(1), "pane_tags": ["Hybrid", "Full-time"], "location": "Pune, India"}
    assert c.post(f"/api/ext/card/{rid}", json={"job_id": "4000000001", "data": hybrid}).get_json()["continue_"] is True
    ok = {**job(2), "pane_tags": ["Remote", "Full-time"], "location": "India (Remote)"}
    assert c.post(f"/api/ext/card/{rid}", json={"job_id": "4000000002", "data": ok}).get_json()["continue_"] is True
    st = c.get(f"/api/ext/status/{rid}").get_json()
    assert st["jobs"]["skipped"] == 1 and st["jobs"]["read"] == 1 and [r["job_id"] for r in st["preview"]] == ["4000000002"]
    assert any("skipped, does not match your filters (workplace is hybrid" in line for line in st["log"])
    assert st["today"]["job"]["used"] == 2                         # a skipped job still counts toward the daily cap


def test_precheck_skips_known_and_wrong_location_cards_without_opening(mk):
    c = mk()
    rid = start(c, max_jobs="10", enrich="")
    nxt(c, rid)
    card(c, rid, 1)                                                     # already collected
    cards = [{"id": "4000000001", "location": "Bengaluru"}, {"id": "4000000002", "location": "India (Remote)"},
             {"id": "4000000003", "location": "Berlin, Germany"}, {"id": "4000000004", "location": ""},
             {"id": "4000000005", "location": "Bengaluru, Karnataka, India (Hybrid)"}]
    keep = c.post(f"/api/ext/precheck/{rid}", json={"cards": cards}).get_json()["read"]
    assert keep == ["4000000002", "4000000004", "4000000005"]
    st = c.get(f"/api/ext/status/{rid}").get_json()
    assert st["jobs"]["skipped"] == 1 and st["today"]["job"]["used"] == 1   # Berlin skipped, no read used
    assert any("skipped without opening (card location Berlin, Germany)" in line for line in st["log"])


def test_company_details_from_job_panel_box_skip_the_company_page(mk):
    c = mk()
    rid = start(c, max_jobs="1")
    nxt(c, rid)
    data = {**job(1, "velsera"), "box_industry": "Biotechnology Research", "company_size": "501-1000"}
    c.post(f"/api/ext/card/{rid}", json={"job_id": "4000000001", "data": data})
    c.post(f"/api/ext/page_done/{rid}", json={"page": 0, "ids": ["4000000001"], "n_new": 1, "has_more": False})
    t = nxt(c, rid)
    assert t["type"] == "done"                                          # no company page opened
    row = c.get(f"/api/ext/status/{rid}").get_json()["preview"][0]
    assert row["company_industry"] == "Biotechnology Research" and row["company_size"] == "501-1,000"
    assert row["industry_source"] == "job page (About the company)"


def test_unknown_filter_values_are_ignored(mk):
    c = mk()
    r = c.post("/api/ext/start", data={"keywords": "x", "work_types": ["moon"], "date_posted": "1999", "sort": "weird"}).get_json()
    q = parse_qs(urlsplit(r["url"]).query)
    assert "f_WT" not in q and "f_TPR" not in q and q["sortBy"] == ["DD"]


def test_full_run_cards_then_companies_once_then_export(mk):
    c = mk()
    rid = start(c)
    nxt(c, rid)
    assert card(c, rid, 1, contacts="https://www.linkedin.com/in/x") is True
    assert card(c, rid, 2, "beta") is True
    assert card(c, rid, 3) is False                    # target 3 reached
    assert card(c, rid, 4) is False                    # nothing beyond the target is saved
    c.post(f"/api/ext/page_done/{rid}", json={"page": 0, "ids": [str(4000000000 + i) for i in range(1, 6)], "n_new": 3, "has_more": True})
    seen = []
    for _ in range(2):
        t = nxt(c, rid)
        assert t["type"] == "company" and t["url"].endswith("/about/")
        seen.append(t["company_url"])
        ok = t["company_url"].endswith("/acme/")
        c.post(f"/api/ext/company_result/{rid}", json={"company_url": t["company_url"], "data":
               {"status": "ok", "industry": "Software Development", "size": "51-200"} if ok else
               {"status": "not found", "note": "no labelled Industry / Company size on the About page"}})
    assert sorted(seen) == ["https://www.linkedin.com/company/acme/", "https://www.linkedin.com/company/beta/"]
    t = nxt(c, rid)
    assert t["type"] == "done" and t["status"] == "done"
    st = c.get(f"/api/ext/status/{rid}").get_json()
    assert st["jobs"]["read"] == 3 and st["pages"] == {"search": 1, "job": 3, "company": 2}
    rows = {r["job_id"]: r for r in st["preview"]}
    assert set(rows) == {"4000000001", "4000000002", "4000000003"}
    r1, r2 = rows["4000000001"], rows["4000000002"]
    assert r1["company_industry"] == "Software Development" and r1["industry_source"] == "company page" and r1["company_size"] == "51-200"
    assert r1["contact_profile_links"] == "https://www.linkedin.com/in/x" and r1["data_notes"] == ""
    assert r2["company_industry"] == "" and "Company industry & size not available (not shown on the company page)" in r2["data_notes"]
    assert "No hiring contact shown" in r2["data_notes"]
    x = c.get(f"/api/ext/download/{rid}/xlsx")
    assert x.status_code == 200 and x.data[:2] == b"PK"
    assert c.get(f"/api/ext/download/{rid}/csv").data.decode("utf-8-sig").startswith("Job Title,Location,Workplace,Job Description,Job URL,Job ID,Company Name,Company Industry,Company Size")
    assert c.get("/api/ext/latest").get_json()["id"] == rid


def test_next_result_page_keeps_filters_and_known_jobs_are_skipped(mk):
    c = mk()
    rid = start(c, max_jobs="10", enrich="")
    nxt(c, rid)
    card(c, rid, 1)
    c.post(f"/api/ext/page_done/{rid}", json={"page": 0, "ids": ["4000000001"], "n_new": 1, "has_more": True})
    t = nxt(c, rid)
    q = parse_qs(urlsplit(t["url"]).query)
    assert t["type"] == "search" and q["start"] == ["25"] and q["f_WT"] == ["2,3"] and t["known_ids"] == ["4000000001"]
    c.post(f"/api/ext/page_done/{rid}", json={"page": 1, "ids": [], "n_new": 0, "has_more": True})
    assert nxt(c, rid)["type"] == "done"               # empty page ends the search; enrichment off


def test_second_run_reuses_jobs_and_companies(mk):
    c = mk()
    rid = start(c, max_jobs="10")
    nxt(c, rid)
    card(c, rid, 1)
    c.post(f"/api/ext/page_done/{rid}", json={"page": 0, "ids": ["4000000001"], "n_new": 1, "has_more": False})
    t = nxt(c, rid)
    c.post(f"/api/ext/company_result/{rid}", json={"company_url": t["company_url"], "data": {"status": "ok", "industry": "IT", "size": "11-50"}})
    assert nxt(c, rid)["type"] == "done"
    rid2 = start(c, max_jobs="10")
    t = nxt(c, rid2)
    assert t["known_ids"] == ["4000000001"]
    assert c.post(f"/api/ext/precheck/{rid2}", json={"cards": [{"id": "4000000001"}]}).get_json()["read"] == []
    c.post(f"/api/ext/page_done/{rid2}", json={"page": 0, "ids": ["4000000001"], "n_new": 0, "has_more": False})
    assert nxt(c, rid2)["type"] == "done"              # company already known: not opened again
    st = c.get(f"/api/ext/status/{rid2}").get_json()
    assert st["pages"] == {"search": 1, "job": 0, "company": 0} and st["jobs"]["reused"] == 1
    assert st["preview"][0]["company_industry"] == "IT" and "earlier run" in st["preview"][0]["data_notes"]


def test_run_stops_at_exactly_the_number_asked_for(mk):
    c = mk()
    # an earlier run collected 8 jobs
    old = start(c, max_jobs="8", enrich="")
    nxt(c, old)
    for i in range(1, 9):
        card(c, old, i)
    c.post(f"/api/ext/stop/{old}")
    # now ask for 10: the 8 known jobs count (not re-opened), only 2 new ones are read, then it stops
    rid = start(c, max_jobs="10", enrich="")
    nxt(c, rid)
    cards = [{"id": str(4000000000 + i), "location": ""} for i in range(1, 15)]
    keep = c.post(f"/api/ext/precheck/{rid}", json={"cards": cards}).get_json()["read"]
    assert keep[:2] == ["4000000009", "4000000010"]
    assert card(c, rid, 9) is True and card(c, rid, 10) is False      # 10 reached: extension stops clicking
    assert card(c, rid, 11) is False                                    # nothing past the target is saved
    c.post(f"/api/ext/page_done/{rid}", json={"page": 0, "ids": [x["id"] for x in cards], "n_new": 2, "has_more": True})
    t = nxt(c, rid)
    assert t["type"] == "done" and t["reason"] == "finished: 10 of 10 jobs collected"   # no second result page
    st = c.get(f"/api/ext/status/{rid}").get_json()
    assert st["count"] == 10 and len(st["preview"]) == 10 and st["jobs"]["reused"] == 8 and st["jobs"]["read"] == 2


def test_run_ended_is_logged_once_even_if_stop_is_pressed_twice(mk):
    c = mk()
    rid = start(c)
    c.post(f"/api/ext/stop/{rid}")
    c.post(f"/api/ext/stop/{rid}")
    st = c.get(f"/api/ext/status/{rid}").get_json()
    assert sum("Run ended" in line for line in st["log"]) == 1 and st["state"] == "stopped"


def test_end_message_when_linkedin_runs_out_of_jobs(mk):
    c = mk()
    rid = start(c, max_jobs="10", enrich="")
    nxt(c, rid)
    card(c, rid, 1)
    c.post(f"/api/ext/page_done/{rid}", json={"page": 0, "ids": ["4000000001"], "n_new": 1, "has_more": False})
    assert nxt(c, rid)["reason"] == "finished: 1 of 10 jobs collected (LinkedIn has no more matching jobs for this search)"


def test_linkedin_warning_stops_run_immediately(mk):
    c = mk()
    rid = start(c)
    nxt(c, rid)
    c.post(f"/api/ext/linkedin_stop/{rid}", json={"reason": "security check", "url": "https://www.linkedin.com/checkpoint/x"})
    assert card(c, rid, 1) is False
    t = nxt(c, rid)
    assert t["type"] == "done" and t["status"] == "blocked" and "security check" in t["reason"]


def test_user_stop_and_only_one_active_run(mk):
    c = mk()
    rid = start(c)
    assert c.post("/api/ext/start", data={"keywords": "x"}).status_code == 409
    c.post(f"/api/ext/stop/{rid}")
    assert nxt(c, rid)["status"] == "stopped"
    start(c)  # allowed again after stop


def test_daily_job_read_limit(mk):
    c = mk(job_pages_per_day=2)
    rid = start(c, max_jobs="10")
    nxt(c, rid)
    assert card(c, rid, 1) is True
    card(c, rid, 2)
    assert card(c, rid, 3) is False
    t = nxt(c, rid)
    assert t["type"] == "done" and t["status"] == "limit" and "2 job reads" in t["reason"]


def test_search_page_limit_per_run(mk):
    c = mk(max_search_pages_per_run=1)
    rid = start(c, max_jobs="50", enrich="")
    nxt(c, rid)
    c.post(f"/api/ext/page_done/{rid}", json={"page": 0, "ids": ["4000000001"], "n_new": 1, "has_more": True})
    assert nxt(c, rid)["type"] == "done"


def test_failed_card_is_noted_not_guessed(mk):
    c = mk()
    rid = start(c, enrich="")
    nxt(c, rid)
    c.post(f"/api/ext/card/{rid}", json={"job_id": "4000000007", "error": "detail panel did not show this job"})
    st = c.get(f"/api/ext/status/{rid}").get_json()
    # reported in the run log, never an empty row in the results or downloads
    assert st["preview"] == [] and st["jobs"]["failed"] == 1
    assert any("Job 4000000007: not read (detail panel did not show this job)" in l for l in st["log"])


def test_bad_ids_and_company_key(mk):
    c = mk()
    assert c.get("/api/ext/status/../x").status_code == 404
    assert c.get("/api/ext/download/abc/../../x").status_code == 404
    assert c.post("/api/ext/start", data={"keywords": " "}).status_code == 400
    assert company_key("https://in.linkedin.com/company/acme-inc/about/?x=1") == "https://www.linkedin.com/company/acme-inc/"
    assert company_key("https://www.linkedin.com/in/someone") == ""


def test_debug_snapshot_saved_locally_with_safe_name(mk, tmp_path):
    c = mk()
    rid = start(c)
    r = c.post(f"/api/ext/debug/{rid}", json={"kind": "results-page", "url": "https://www.linkedin.com/jobs/search/",
                                               "counts": {"searchCards": [0]}, "html": "<main>hi</main>"}).get_json()
    c.post(f"/api/ext/debug/{rid}", json={"kind": "../../evil", "html": "x"})
    saved = sorted(p.name for p in (tmp_path / "debug").iterdir())
    assert saved == [f"{rid}_evil.html", f"{rid}_evil.json", f"{rid}_results-page.html", f"{rid}_results-page.json"]
    assert not (tmp_path / "evil.html").exists()
    assert (tmp_path / "debug" / f"{rid}_results-page.html").read_text(encoding="utf-8") == "<main>hi</main>"
    assert "html" not in (tmp_path / "debug" / f"{rid}_results-page.json").read_text(encoding="utf-8").split('"counts"')[0]
    assert r["file"].endswith(f"{rid}_results-page.html")


def test_dashboard_page_is_the_search_form(mk):
    html = mk().get("/").data.decode()
    assert "JobHarvest" in html and 'name="keywords"' in html and 'name="work_types"' in html
    assert "Past 24 hours" in html and "Easy Apply" in html and "Under 10 applicants" in html
    assert "Guest (no login)" not in html and "Collect jobs from this search" not in html


def test_export_columns_and_excel_cell_limit(tmp_path):
    from openpyxl import load_workbook
    from ljt import export
    rows = [{"job_title": "Dev", "company_name": "Acme", "job_description": "x" * 40000}]
    export.write_xlsx(rows, tmp_path / "a.xlsx")
    export.write_csv(rows, tmp_path / "a.csv")
    ws = load_workbook(tmp_path / "a.xlsx").active
    head = [c.value for c in ws[1]]
    assert head[:4] == ["Job Title", "Location", "Workplace", "Job Description"]
    # all company details sit side by side
    assert head[6:11] == ["Company Name", "Company Industry", "Company Size", "Company URL", "Industry Source"]
    assert ws["A2"].value == "Dev" and len(ws["D2"].value) <= 32000
    assert (tmp_path / "a.csv").read_text(encoding="utf-8-sig").startswith("Job Title,Location,Workplace")


def test_results_are_cleaned_for_display_and_export(mk):
    c = mk()
    rid = start(c, max_jobs="1", enrich="")
    nxt(c, rid)
    raw = {"job_title": "| Java Full Stack Developer", "company_name": " TestUnity ",
           "company_url": "https://www.linkedin.com/company/testunity/", "location": "India (Remote)",
           "job_description": "About the job\n\n**WE'RE HIRING**\n\n\n\n* Java\n- Spring Boot\n   AWS   ",
           "contact_profile_links": "https://www.linkedin.com/in/ivo-ve%C4%8De%C5%99a-2a94291/; https://www.linkedin.com/in/x/",
           "company_size": "1001-5000", "pane_tags": ["Remote", "Full-time", "Easy Apply"], "posted": "India · 5 days ago · Over 100 applicants"}
    c.post(f"/api/ext/card/{rid}", json={"job_id": "4000000001", "data": raw})
    r = c.get(f"/api/ext/status/{rid}").get_json()["preview"][0]
    assert r["job_title"] == "Java Full Stack Developer" and r["company_name"] == "TestUnity"
    assert r["job_description"] == "WE'RE HIRING\n\n• Java\n• Spring Boot\nAWS"
    assert r["location"] == "India" and r["workplace"] == "Remote" and r["employment_type"] == "Full-time"
    assert r["company_size"] == "1,001-5,000" and r["posted_date"] == "5 days ago"
    assert r["contact_profile_links"] == "https://www.linkedin.com/in/ivo-večeřa-2a94291/\nhttps://www.linkedin.com/in/x/"


def test_job_saved_without_title_is_read_again_not_reused(mk):
    c = mk()
    rid = start(c, max_jobs="5", enrich="")
    nxt(c, rid)
    c.post(f"/api/ext/card/{rid}", json={"job_id": "4000000001", "data": {"job_title": "", "job_description": "x"}})
    c.post(f"/api/ext/stop/{rid}")
    rid2 = start(c, max_jobs="5", enrich="")
    assert nxt(c, rid2)["known_ids"] == []                          # the untitled read is not 'already collected'
    assert c.post(f"/api/ext/precheck/{rid2}", json={"cards": [{"id": "4000000001"}]}).get_json()["read"] == ["4000000001"]


@pytest.mark.sqlite_only
def test_database_uses_wal_and_busy_timeout(tmp_path):
    from ljt.extstore import ExtStore
    s = ExtStore(str(tmp_path / "w.sqlite"))
    assert s.db.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert s.db.execute("PRAGMA busy_timeout").fetchone()[0] == 30000


def test_seen_again_updates_last_seen_not_a_new_row_and_export_all_filters(mk, tmp_path):
    import io, openpyxl, datetime
    c = mk()
    rid = start(c, max_jobs="10")
    nxt(c, rid)
    card(c, rid, 1)
    card(c, rid, 2, comp="beta")
    c.post(f"/api/ext/page_done/{rid}", json={"page": 0, "ids": ["4000000001", "4000000002"], "n_new": 2, "has_more": False})
    c.post(f"/api/ext/stop/{rid}")
    rid2 = start(c, max_jobs="10")
    nxt(c, rid2)
    c.post(f"/api/ext/precheck/{rid2}", json={"cards": [{"id": "4000000001"}]})
    r = c.get("/api/ext/export.xlsx")
    ws = openpyxl.load_workbook(io.BytesIO(r.data)).active
    head = [x.value for x in ws[1]]
    assert ws.max_row == 3                                   # 2 jobs, no duplicate for the job seen twice
    assert head[-2:] == ["Date Collected (IST)", "Last Seen (IST)"]
    assert isinstance(ws.cell(2, len(head)).value, datetime.datetime)   # real Excel dates
    r = c.get("/api/ext/export.csv?text=Java Dev 2|nothing")
    lines = r.data.decode("utf-8-sig").strip().splitlines()
    assert len(lines) == 2 and "Java Dev 2" in lines[1]
    assert c.get(f"/api/ext/export.csv?run_id={rid2}").data.decode("utf-8-sig").count("Java Dev") == 1
    assert c.get("/api/ext/export.csv?date_from=2020-1-1").status_code == 400


def test_history_lists_past_searches_newest_first(mk):
    c = mk()
    rid = start(c, max_jobs="10")
    nxt(c, rid)
    card(c, rid, 1)
    c.post(f"/api/ext/stop/{rid}")
    rid2 = start(c, keywords="Python developer")
    h = c.get("/api/ext/history").get_json()
    assert [r["id"] for r in h] == [rid2, rid]
    assert h[0]["keywords"] == "Python developer" and h[0]["status"] == "running"
    assert h[1]["count"] == 1 and h[1]["target"] == 10 and h[1]["status"] == "stopped"


def test_browse_matches_filtered_download_and_export_has_no_type_or_posted(mk):
    import io, openpyxl
    c = mk()
    rid = start(c, max_jobs="10")
    nxt(c, rid)
    card(c, rid, 1)
    card(c, rid, 2, comp="beta")
    j = c.get("/api/ext/browse?text=Java Dev 2").get_json()
    assert j["total"] == 1 and j["rows"][0]["job_title"] == "Java Dev 2"
    assert c.get("/api/ext/browse").get_json()["total"] == 2
    head = [x.value for x in openpyxl.load_workbook(io.BytesIO(c.get("/api/ext/export.xlsx").data)).active[1]]
    assert "Employment Type" not in head and "Posted" not in head and "Job Title" in head


def test_precheck_skips_cards_whose_workplace_is_not_the_one_asked_for(mk):
    c = mk()
    rid = start(c, max_jobs="10", work_types=["remote"])
    nxt(c, rid)
    cards = [{"id": "4100000001", "location": "Bengaluru (Hybrid)"}, {"id": "4100000002", "location": "Bengaluru, Karnataka, India (On-site)"},
             {"id": "4100000003", "location": "India (Remote)"}, {"id": "4100000004", "location": "Bengaluru"}]
    assert c.post(f"/api/ext/precheck/{rid}", json={"cards": cards}).get_json()["read"] == ["4100000003", "4100000004"]
    log = "\n".join(c.get(f"/api/ext/status/{rid}").get_json()["log"])
    assert "skipped without opening (card says Hybrid)" in log and "skipped without opening (card says On-site)" in log


def test_filtered_location_uses_place_aliases(mk):
    c = mk()
    rid = start(c, max_jobs="10")
    nxt(c, rid)
    card(c, rid, 1)                                       # saved with location "Bengaluru (Remote)"
    assert c.get("/api/ext/browse?location=Bangalore").get_json()["total"] == 1
    assert c.get("/api/ext/browse?location=Bengaluru, Karnataka, India").get_json()["total"] == 1
    assert c.get("/api/ext/browse?location=Hyderabad").get_json()["total"] == 0


def test_failed_reads_do_not_count_or_appear_as_empty_rows(mk):
    c = mk()
    rid = start(c, max_jobs="2")
    nxt(c, rid)
    assert c.post(f"/api/ext/card/{rid}", json={"job_id": "4200000001", "error": "No tab with id: 5"}).get_json()["continue_"]
    card(c, rid, 2)
    assert c.post(f"/api/ext/card/{rid}", json={"job_id": "4200000003", "error": "detail panel did not show this job"}).get_json()["continue_"]
    assert not card(c, rid, 4)                            # 2 real jobs = target reached
    st = c.get(f"/api/ext/status/{rid}").get_json()
    assert st["count"] == 2 and all(r["job_title"] for r in st["preview"])


def test_company_line_on_card_is_not_taken_as_location(mk):
    c = mk()
    rid = start(c, max_jobs="10", work_types=[])
    nxt(c, rid)
    cards = [{"id": "4300000001", "location": "Accenture in India"}, {"id": "4300000002", "location": "PwC Acceleration Center India"},
             {"id": "4300000003", "location": "Pune, Maharashtra, India"}]
    assert c.post(f"/api/ext/precheck/{rid}", json={"cards": cards}).get_json()["read"] == ["4300000001", "4300000002"]


def test_more_companies_hands_out_several_within_limits(mk):
    c = mk()
    rid = start(c, max_jobs="3")
    nxt(c, rid)
    for i, comp in enumerate(["acme", "beta", "gamma"], 1):
        card(c, rid, i, comp=comp)
    c.post(f"/api/ext/page_done/{rid}", json={"page": 0, "ids": [], "n_new": 3, "has_more": False})
    first = nxt(c, rid)
    assert first["type"] == "company"
    more = c.get(f"/api/ext/more_companies/{rid}?k=2").get_json()
    assert len(more) == 2 and len({first["company_url"], *[m["company_url"] for m in more]}) == 3
    assert c.get(f"/api/ext/more_companies/{rid}?k=2").get_json() == []       # none left; the run is NOT ended by this
    assert c.get(f"/api/ext/state/{rid}").get_json()["state"] == "running"
    assert c.get(f"/api/ext/status/{rid}").get_json()["pages"]["company"] == 3


def test_quickcheck_flags_a_wrong_job_type_from_the_panel_labels_only(mk):
    c = mk()
    rid = start(c, max_jobs="10", job_types=["part-time"], work_types=["remote"], easy_apply="")
    nxt(c, rid)
    q = lambda tags, loc="Bengaluru (Remote)": c.post(f"/api/ext/quickcheck/{rid}", json={"tags": tags, "location": loc}).get_json()["mismatch"]
    assert q(["Remote", "Contract"]) == "job type is contract, not part-time"
    assert q(["Remote", "Part-time"]) is None
    assert q(["Remote", "Part-time", "Contract"]) is None          # shows the asked type too: kept
    assert q([]) is None                                           # labels not drawn yet: never a guess, read in full
    assert q(["Hybrid", "Part-time"]) == "workplace is hybrid, not remote"
    # the quick skip is recorded exactly like a full-read skip (not counted, not in results)
    c.post(f"/api/ext/card/{rid}", json={"job_id": "4500000001", "data": {**job(1), "pane_tags": ["Remote", "Contract"]}})
    st = c.get(f"/api/ext/status/{rid}").get_json()
    assert st["count"] == 0 and st["jobs"]["skipped"] == 1
