"""Set TEST_DATABASE_URL=postgres://... to run the whole suite against PostgreSQL instead of SQLite files.
Each test then starts from empty tables. USE A THROWAWAY DATABASE (or a Neon branch): its tables are dropped."""
import os

import pytest

from ljt import db

PG = os.environ.get("TEST_DATABASE_URL", "")
TABLES = ("runs", "jobs", "run_jobs", "companies", "daily", "log")


@pytest.fixture(autouse=True)
def _postgres_instead_of_sqlite(monkeypatch, request):
    if not PG:
        yield
        return
    if request.node.get_closest_marker("sqlite_only"):
        pytest.skip("checks SQLite-specific settings")
    fresh = [True]
    real = db.connect

    def connect(target):
        if db.is_postgres(target):
            return real(target)
        if fresh[0]:                       # first store of this test: drop everything, then recreate
            conn = real(PG)
            for t in TABLES:
                conn.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
            fresh[0] = False
        return real(PG)
    monkeypatch.setattr(db, "connect", connect)
    yield


def pytest_configure(config):
    config.addinivalue_line("markers", "sqlite_only: test checks SQLite-only behaviour")
