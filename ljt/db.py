"""One small database interface for ExtStore: SQLite (local file, tests) or PostgreSQL (hosted, DATABASE_URL).

ExtStore writes SQLite-style SQL ("?" placeholders, LIKE, rowid). For PostgreSQL it is translated here:
"?" -> "%s", LIKE -> ILIKE (SQLite's LIKE ignores case), rowid -> rid (an identity column that PostgreSQL tables
get instead). Rows are read by column name in both cases. All callers hold ExtStore.lock, so one connection is used
by one thread at a time.
"""
import re
import sqlite3

SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, created TEXT, params TEXT, target INTEGER, status TEXT,
  end_reason TEXT, search_page INTEGER DEFAULT 0, search_done INTEGER DEFAULT 0, empty_pages INTEGER DEFAULT 0,
  search_pages INTEGER DEFAULT 0, job_pages INTEGER DEFAULT 0, company_pages INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS jobs (job_id TEXT PRIMARY KEY, title TEXT, company_name TEXT, company_url TEXT,
  location TEXT, posted TEXT, description TEXT, contacts TEXT, job_industry TEXT, job_size TEXT, notes TEXT,
  collected_at TEXT);
CREATE TABLE IF NOT EXISTS run_jobs (run_id TEXT, job_id TEXT, status TEXT, note TEXT, seq INTEGER,
  PRIMARY KEY (run_id, job_id));
CREATE TABLE IF NOT EXISTS companies (url TEXT PRIMARY KEY, industry TEXT, size TEXT, status TEXT, note TEXT,
  read_at TEXT);
CREATE TABLE IF NOT EXISTS daily (day TEXT, kind TEXT, n INTEGER, PRIMARY KEY (day, kind));
CREATE TABLE IF NOT EXISTS log (run_id TEXT, ts TEXT, msg TEXT);
"""
# Columns added after the first release (old local databases get them on start).
SQLITE_ADDED = (("runs", "search_base"), ("jobs", "tags"), ("jobs", "last_seen"))

# Same tables for PostgreSQL. 'rid' is last so positional INSERT ... VALUES (...) keeps working.
PG_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, created TEXT, params TEXT, target INTEGER, status TEXT,
  end_reason TEXT, search_page INTEGER DEFAULT 0, search_done INTEGER DEFAULT 0, empty_pages INTEGER DEFAULT 0,
  search_pages INTEGER DEFAULT 0, job_pages INTEGER DEFAULT 0, company_pages INTEGER DEFAULT 0, search_base TEXT,
  rid BIGINT GENERATED ALWAYS AS IDENTITY);
CREATE TABLE IF NOT EXISTS jobs (job_id TEXT PRIMARY KEY, title TEXT, company_name TEXT, company_url TEXT,
  location TEXT, posted TEXT, description TEXT, contacts TEXT, job_industry TEXT, job_size TEXT, notes TEXT,
  collected_at TEXT, tags TEXT, last_seen TEXT);
CREATE TABLE IF NOT EXISTS run_jobs (run_id TEXT, job_id TEXT, status TEXT, note TEXT, seq INTEGER,
  PRIMARY KEY (run_id, job_id));
CREATE TABLE IF NOT EXISTS companies (url TEXT PRIMARY KEY, industry TEXT, size TEXT, status TEXT, note TEXT,
  read_at TEXT);
CREATE TABLE IF NOT EXISTS daily (day TEXT, kind TEXT, n INTEGER, PRIMARY KEY (day, kind));
CREATE TABLE IF NOT EXISTS log (run_id TEXT, ts TEXT, msg TEXT, rid BIGINT GENERATED ALWAYS AS IDENTITY);
CREATE INDEX IF NOT EXISTS log_run ON log (run_id, rid);
CREATE INDEX IF NOT EXISTS run_jobs_job ON run_jobs (job_id);
"""


def is_postgres(target):
    return isinstance(target, str) and target.startswith(("postgres://", "postgresql://"))


def connect(target):
    return PgDB(target) if is_postgres(target) else SqliteDB(target)


class SqliteDB:
    kind = "sqlite"

    def __init__(self, path):
        self.conn = sqlite3.connect(path, check_same_thread=False, timeout=30)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")      # readers never block the writer
        self.conn.execute("PRAGMA busy_timeout=30000")
        self.conn.executescript(SQLITE_SCHEMA)
        for table, col in SQLITE_ADDED:
            try:
                self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} TEXT")
            except sqlite3.OperationalError:
                pass

    def execute(self, sql, params=()):
        return self.conn.execute(sql, params)

    def commit(self):
        self.conn.commit()


_PLACEHOLDER = re.compile(r"\?")
_LIKE = re.compile(r"\bLIKE\b", re.I)
_ROWID = re.compile(r"\browid\b", re.I)


def to_pg(sql):
    sql = sql.replace("%", "%%")                 # literal % (e.g. LIKE 'Run ended:%') when parameters are passed
    sql = _PLACEHOLDER.sub("%s", sql)
    sql = _LIKE.sub("ILIKE", sql)
    return _ROWID.sub("rid", sql)


class _Rows:
    """A finished PostgreSQL statement: rows as dicts (by column name), like sqlite3.Row."""

    def __init__(self, cur):
        self.rowcount = cur.rowcount
        names = [d[0] for d in cur.description] if cur.description else []
        self._rows = [dict(zip(names, r)) for r in cur.fetchall()] if names else []

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)

    def __iter__(self):
        return iter(self._rows)


def pg_connect_args(url):
    """postgres://user:pass@host:port/db?sslmode=require -> pg8000 keyword arguments (TLS unless sslmode=disable)."""
    import ssl
    from urllib.parse import parse_qs, unquote, urlsplit
    u = urlsplit(url)
    q = {k: v[-1] for k, v in parse_qs(u.query).items()}
    args = {"user": unquote(u.username or ""), "password": unquote(u.password or ""), "host": u.hostname or "localhost",
            "port": u.port or 5432, "database": (u.path or "/").lstrip("/") or "postgres", "timeout": 30}
    if q.get("sslmode", "require") != "disable":
        args["ssl_context"] = ssl.create_default_context()
    return args


class PgDB:
    """PostgreSQL (pure-Python pg8000 driver) in autocommit mode: each statement is saved at once and ExtStore's
    lock serialises callers. Reconnects once when the server dropped the connection (Neon suspends idle databases)."""
    kind = "postgres"

    def __init__(self, url):
        import pg8000.dbapi
        self._pg, self._args = pg8000.dbapi, pg_connect_args(url)
        self._connect()
        for stmt in PG_SCHEMA.split(";"):
            if stmt.strip():
                self._run(stmt, ())

    def _connect(self):
        self.conn = self._pg.connect(**self._args)
        self.conn.autocommit = True

    def _run(self, q, params):
        cur = self.conn.cursor()
        try:
            cur.execute(q, tuple(params or ()))
            return _Rows(cur)
        finally:
            cur.close()

    def execute(self, sql, params=()):
        q = to_pg(sql) if params else to_pg(sql).replace("%%", "%")
        try:
            return self._run(q, tuple(params))
        except (self._pg.InterfaceError, OSError):    # connection closed by the server: reconnect, try once more
            self._connect()
            return self._run(q, tuple(params))

    def commit(self):
        pass                                      # autocommit
