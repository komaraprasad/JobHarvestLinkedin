"""Fast mode: LinkedIn's public job pages (real responses saved 2026-11-13 in tests/fixtures) parsed on the server."""
import os

import pytest

from app import create_app
from ljt import guest

FIX = os.path.join(os.path.dirname(__file__), "fixtures")
read = lambda name: open(os.path.join(FIX, name), encoding="utf-8").read()
FORM = {"keywords": "AI Engineer", "location": "Bengaluru, Karnataka, India", "work_types": ["remote"],
        "job_types": ["full-time"], "easy_apply": "on", "max_jobs": "3", "enrich": "on"}


def test_parse_search_cards():
    cards = guest.parse_search(read("guest_search.html"))
    assert len(cards) == 10 and len({c["id"] for c in cards}) == 10
    assert cards[0] == {"id": "4458367240", "title": "AI Engineer", "company": "NextNation",
                        "location": "Bengaluru, Karnataka, India", "listed": "2026-08-27"}


def test_parse_job_page():
    d = guest.parse_job(read("guest_job.html"))
    assert (d["job_title"], d["company_name"], d["location"]) == ("AI Engineer", "NextNation", "Bengaluru, Karnataka, India")
    assert d["company_url"] == "https://in.linkedin.com/company/nextnationco"
    assert d["job_description"].startswith("Location: Onsite - HSR Layout") and len(d["job_description"]) > 500
    assert d["pane_tags"] == ["Full-time"] and d["posted"] == "2 months ago" and d["seniority"] == "Entry level"
    assert "<" not in d["job_description"]


def test_parse_company_page():
    assert guest.parse_company(read("guest_company.html")) == {"industry": "Education", "size": "51-200", "status": "ok", "note": ""}
    assert guest.parse_company("<html></html>")["status"] == "not found"


def test_search_url_keeps_classic_filters():
    u = guest.search_url("https://www.linkedin.com", {"keywords": "AI Engineer", "f_WT": "2", "geoId": "1", "location": ""}, 20)
    assert u.startswith("https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?")
    assert "f_WT=2" in u and "start=20" in u and "location=" not in u


@pytest.fixture
def c(tmp_path):
    return create_app(db_path=str(tmp_path / "g.sqlite3"), out_dir=str(tmp_path)).test_client()


def test_fast_mode_end_to_end(c):
    rid = c.post("/api/ext/start", data=FORM).get_json()["id"]
    t = c.get(f"/api/ext/next/{rid}").get_json()
    assert t["type"] == "search" and len(t["guest"]["urls"]) == 3
    assert [u.split("start=")[1] if "start=" in u else "0" for u in t["guest"]["urls"]] == ["0", "10", "20"]
    s = c.post(f"/api/ext/guest_search/{rid}", json={"page": 0, "htmls": [read("guest_search.html")]}).get_json()
    assert len(s["ids"]) == 10 and "4458367240" in s["read"] and s["has_more"] is True
    # job page: saved even though Easy Apply was asked for (public pages never show it) - LinkedIn's f_AL filter applies
    r = c.post(f"/api/ext/guest_job/{rid}", json={"job_id": "4458367240", "html": read("guest_job.html")}).get_json()
    assert r["continue_"] is True
    # unreadable page: noted as not read, not counted
    assert c.post(f"/api/ext/guest_job/{rid}", json={"job_id": "4447329688", "html": "<html></html>"}).get_json()["continue_"] is True
    c.post(f"/api/ext/page_done/{rid}", json={"page": 0, "ids": s["ids"], "n_new": 1, "has_more": False})
    comp = c.get(f"/api/ext/next/{rid}").get_json()
    assert comp["type"] == "company" and comp["guest_url"] == "https://www.linkedin.com/company/nextnationco/"
    c.post(f"/api/ext/guest_company/{rid}", json={"company_url": comp["company_url"], "html": read("guest_company.html")})
    assert c.get(f"/api/ext/next/{rid}").get_json()["type"] == "done"
    rows = c.get(f"/api/ext/status/{rid}").get_json()["preview"]
    assert len(rows) == 1
    row = rows[0]
    assert (row["job_title"], row["company_name"], row["company_industry"], row["company_size"]) == ("AI Engineer", "NextNation", "Education", "51-200")
