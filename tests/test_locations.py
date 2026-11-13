"""Location handling: locations.py (used unchanged) wired into the Jobs Collector."""
import json
from urllib.parse import parse_qs, urlsplit

import pytest

from app import create_app
from ljt.geo_directory import DIRECTORY
from ljt.locations import lead_in_place, resolve, resolve_many
from ljt.place_search import job_in_places, plan, region_facet, suggest


# ---------- the three required tests ----------
def test_bangalore_resolves_to_the_bengaluru_id():
    r = resolve("Bangalore", None, DIRECTORY)
    assert r == {"name": "Bengaluru, Karnataka, India", "id": "105214831", "exact": True, "local_terms": []}


def test_banga_india_widens_to_india_and_keeps_only_banga():
    r = resolve_many([{"text": "Banga, India", "id": ""}], DIRECTORY)
    assert r["regions"] == [{"id": "102713980", "text": "India"}]
    assert r["local_terms"] == ["banga"]
    assert lead_in_place("Banga, Punjab, India", r["local_terms"]) is True
    assert lead_in_place("Bengaluru, Karnataka, India", r["local_terms"]) is False
    assert lead_in_place("Pune, Maharashtra, India", r["local_terms"]) is False


def test_empty_location_is_never_rejected():
    assert lead_in_place("", ["banga"]) is True
    assert lead_in_place("   ", ["banga"]) is True
    assert job_in_places("", ["India"], []) is True
    assert job_in_places("", ["Banga, India"], ["banga"]) is True


# ---------- REGION facet, suggestions, search plan ----------
def test_region_facet_format():
    regions = resolve_many([{"text": "Bangalore", "id": ""}, {"text": "Chennai", "id": ""}], DIRECTORY)["regions"]
    assert region_facet(regions) == ("(type:REGION,values:List((id:105214831,text:Bengaluru%2C Karnataka%2C India,selectionType:INCLUDED),"
                                     "(id:106832467,text:Chennai%2C Tamil Nadu%2C India,selectionType:INCLUDED)))")


def test_no_region_filter_when_a_place_has_no_id():
    p = plan([{"text": "Bangalore", "id": ""}, {"text": "Atlantis", "id": ""}])
    assert p["regions"] == [] and p["facet"] == "" and p["geo_id"] == ""
    assert "atlantis" in p["local_terms"] and "bengaluru" in p["local_terms"]


def test_suggestions_aliases_first_then_directory_one_per_id():
    s = suggest("bang")
    assert s[0] == {"text": "Bengaluru, Karnataka, India", "id": "105214831"}
    assert len([x for x in s if x["id"] == "105214831"]) == 1
    assert suggest("che")[0]["id"] == "106832467"
    assert {"text": "United States", "id": "103644278"} in suggest("usa")
    assert suggest("b") == []


def test_plan_one_place_and_several_places_in_one_country():
    one = plan([{"text": "Bangalore", "id": ""}])
    assert one["geo_id"] == "105214831" and one["location_text"] == "Bengaluru, Karnataka, India" and one["local_terms"] == []
    two = plan([{"text": "Bengaluru, Karnataka, India", "id": "105214831"}, {"text": "Chennai", "id": ""}])
    assert two["geo_id"] == "102713980" and two["location_text"] == "India"      # job search takes one geoId
    assert job_in_places("Chennai (Hybrid)", two["names"], two["local_terms"]) is True
    assert job_in_places("Pune, Maharashtra, India", two["names"], two["local_terms"]) is False


@pytest.mark.parametrize("loc, ok", [("Bengaluru (Hybrid)", True), ("India (Remote)", True), ("Karnataka, India", True),
                                     ("Berlin, Germany", False)])
def test_country_place_accepts_its_cities(loc, ok):
    p = plan([{"text": "India", "id": "102713980"}])
    assert job_in_places(loc, p["names"], p["local_terms"]) is ok


# ---------- world_geo.db (read-only; skipped when the file is not there) ----------
from ljt import geo_db  # noqa: E402

needs_db = pytest.mark.skipif(not geo_db.available(), reason="world_geo.db not present")


@needs_db
def test_directory_includes_every_linkedin_id_from_world_geo_db():
    ids = {d["id"] for d in DIRECTORY}
    assert {"105658603", "104153106", "90000091"} <= ids        # Madurai, Indore, Greater Seattle Area
    assert resolve("Madurai, Tamil Nadu, India", None, DIRECTORY)["id"] == "105658603"
    assert all(d["id"].isdigit() for d in DIRECTORY)            # rows without an ID never enter the directory


@needs_db
def test_suggestions_include_places_without_an_id():
    s = suggest("banga")
    assert s[0]["id"] == "105214831" and {"text": "Banga, India", "id": ""} in s


@needs_db
@pytest.mark.parametrize("loc, ok", [("Madurai (Hybrid)", True), ("Lahore", False), ("Lahore, Pakistan", False),
                                     ("Hyderabad", True), ("Remote", True), ("Austin, Texas", False)])
def test_country_check_uses_world_geo_db(loc, ok):
    from ljt.job_location import job_in_requested_place
    assert job_in_requested_place("india", loc) is ok


@needs_db
def test_geo_db_is_opened_read_only():
    import sqlite3
    with pytest.raises(sqlite3.OperationalError):
        geo_db._db().execute("CREATE TABLE x (y)")


@pytest.mark.parametrize("loc, ok", [
    ("India (Remote)", True),                 # skipped wrongly in the live run of 2026-11-11 17:23
    ("Bengaluru, Karnataka, India (Remote)", True), ("Remote", True),
    ("Pune, Maharashtra, India (Remote)", False),   # a remote job tied to another city is not Bengaluru
    ("United States (Remote)", False), ("Pune, Maharashtra, India", False)])
def test_remote_job_for_the_whole_country_covers_the_city(loc, ok):
    p = plan([{"text": "Bengaluru, Karnataka, India", "id": "105214831"}])
    assert job_in_places(loc, p["names"], p["local_terms"]) is ok


# ---------- through the app ----------
@pytest.fixture
def client(tmp_path):
    return create_app(db_path=str(tmp_path / "e.sqlite"), out_dir=str(tmp_path)).test_client()


def test_suggest_endpoint(client):
    assert client.get("/api/ext/locations/suggest?q=gurg").get_json()[0] == {"text": "Gurugram, Haryana, India", "id": "104869687"}


def test_start_with_location_chips_sends_geoid_and_logs_region_facet(client):
    places = [{"text": "Bengaluru, Karnataka, India", "id": "105214831"}, {"text": "Chennai, Tamil Nadu, India", "id": "106832467"}]
    r = client.post("/api/ext/start", data={"keywords": "java", "places": json.dumps(places), "max_jobs": "10"}).get_json()
    q = parse_qs(urlsplit(r["url"]).query)
    assert q["geoId"] == ["102713980"] and q["location"] == ["India"]
    st = client.get(f"/api/ext/status/{r['id']}").get_json()
    assert any("REGION facet: (type:REGION,values:List((id:105214831" in line for line in st["log"])
    t = client.get(f"/api/ext/next/{r['id']}").get_json()
    assert parse_qs(urlsplit(t["ai_url"]).query)["keywords"][0] == "java in Bengaluru, Karnataka, India or Chennai, Tamil Nadu, India"


def test_widened_place_filters_collected_jobs(client):
    r = client.post("/api/ext/start", data={"keywords": "java", "places": json.dumps([{"text": "Banga, India", "id": ""}]),
                                             "max_jobs": "5", "enrich": ""}).get_json()
    rid = r["id"]
    assert parse_qs(urlsplit(r["url"]).query)["geoId"] == ["102713980"]
    client.get(f"/api/ext/next/{rid}")
    for i, loc in ((1, "Banga, Punjab, India"), (2, "Bengaluru, Karnataka, India"), (3, "")):
        client.post(f"/api/ext/card/{rid}", json={"job_id": str(4100000000 + i),
                    "data": {"job_title": f"J{i}", "job_description": "x", "location": loc, "pane_tags": []}})
    st = client.get(f"/api/ext/status/{rid}").get_json()
    assert sorted(x["job_id"] for x in st["preview"]) == ["4100000001", "4100000003"]   # Bengaluru skipped, empty kept
    assert st["jobs"]["skipped"] == 1


def test_saved_jobs_filtered_by_place_with_like(client):
    r = client.post("/api/ext/start", data={"keywords": "java", "max_jobs": "5", "enrich": ""}).get_json()
    rid = r["id"]
    client.get(f"/api/ext/next/{rid}")
    for i, loc in ((1, "Bengaluru, Karnataka, India"), (2, "Pune, Maharashtra, India"), (3, "Bangalore Urban, Karnataka")):
        client.post(f"/api/ext/card/{rid}", json={"job_id": str(4200000000 + i), "data": {"job_title": f"J{i}", "job_description": "x", "location": loc}})
    got = client.get("/api/ext/saved_jobs?place=Bangalore").get_json()
    assert sorted(j["job_id"] for j in got) == ["4200000001", "4200000003"]
    got = client.get("/api/ext/saved_jobs?place=Bangalore&place=Pune").get_json()
    assert len(got) == 3
    assert client.get("/api/ext/saved_jobs?place=Mysuru").get_json() == []
