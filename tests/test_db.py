"""SQLite-style SQL is translated correctly for PostgreSQL (no server needed for these)."""
from ljt.db import is_postgres, pg_connect_args, to_pg


def test_placeholders_like_and_rowid():
    assert to_pg("SELECT ts FROM log WHERE run_id=? AND msg LIKE 'Run ended:%' ORDER BY rowid DESC") == \
        "SELECT ts FROM log WHERE run_id=%s AND msg ILIKE 'Run ended:%%' ORDER BY rid DESC"
    assert to_pg("lower(location) LIKE ?") == "lower(location) ILIKE %s"


def test_upsert_is_valid_for_both():
    sql = "INSERT INTO daily VALUES (?,?,1) ON CONFLICT(day,kind) DO UPDATE SET n=daily.n+1"
    assert to_pg(sql) == "INSERT INTO daily VALUES (%s,%s,1) ON CONFLICT(day,kind) DO UPDATE SET n=daily.n+1"


def test_url_parsing():
    a = pg_connect_args("postgresql://u%40x:p%23w@ep-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require")
    assert (a["user"], a["password"], a["host"], a["port"], a["database"]) == ("u@x", "p#w", "ep-1.aws.neon.tech", 5432, "neondb")
    assert "ssl_context" in a
    assert "ssl_context" not in pg_connect_args("postgres://u:p@localhost:5433/x?sslmode=disable")
    assert is_postgres("postgres://x") and is_postgres("postgresql://x") and not is_postgres("C:/out/a.sqlite3")
