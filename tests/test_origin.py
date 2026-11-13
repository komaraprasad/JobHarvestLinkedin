"""Only the dashboard page and the browser extension may change things; other websites get 403."""
import pytest

from app import create_app


@pytest.fixture
def client(tmp_path):
    return create_app(db_path=str(tmp_path / "t.sqlite3"), out_dir=str(tmp_path)).test_client()


@pytest.mark.parametrize("origin,code", [
    ("https://evil.example", 403),
    ("http://127.0.0.1:5000", 400),           # allowed through; 400 = no keywords given
    ("http://localhost:5000", 400),
    ("chrome-extension://abcdef", 400),
    (None, 400),
])
def test_start_origin(client, origin, code):
    headers = {"Origin": origin} if origin else {}
    assert client.post("/api/ext/start", data={}, headers=headers).status_code == code


def test_get_is_not_blocked(client):
    assert client.get("/api/ext/history", headers={"Origin": "https://evil.example"}).status_code == 200


def test_hosted_dashboard_own_origin_is_allowed_behind_proxy(client):
    proxy = {"X-Forwarded-Proto": "https", "X-Forwarded-Host": "jobharvest.onrender.com"}
    assert client.post("/api/ext/start", data={}, headers={**proxy, "Origin": "https://jobharvest.onrender.com"}).status_code == 400
    assert client.post("/api/ext/start", data={}, headers={**proxy, "Origin": "https://other.onrender.com"}).status_code == 403


def test_render_without_database_url_refuses_to_start(monkeypatch, tmp_path):
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        create_app(out_dir=str(tmp_path))


def test_dashboard_knows_the_shipped_extension_version(client):
    import json, os
    v = json.load(open(os.path.join(os.path.dirname(__file__), "..", "extension", "manifest.json"), encoding="utf-8"))["version"]
    html = client.get("/").get_data(as_text=True)
    assert f'const EXT_LATEST = "{v}";' in html and 'id="extUpdate"' in html
