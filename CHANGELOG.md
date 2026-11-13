# JobHarvest changelog

All changes made on 2026-11-13 (times IST), newest last. Version = browser extension version
(`extension/manifest.json`). Commit = git commit in this repo.

## Before git (morning, same day)
| Change | Files |
|---|---|
| Results page: Location box suggests places like the search form | `templates/results.html` |
| Request-origin check: other websites can no longer start/stop runs (403) | `app.py`, `tests/test_origin.py` |
| Every database access goes through the store lock (no clashes between requests) | `ljt/extstore.py` |
| Waitress server locally, browser opens automatically, `output/` next to the app | `app.py` |
| Windows packages: `JobHarvest.exe` (PyInstaller) + Python package with `Start JobHarvest.bat` | `build.ps1`, `DEPLOY.md` |

## Commits
| Time | Commit | Version | Change |
|---|---|---|---|
| 12:59 | `1800916` | 3.10.0 | **Hosting**: PostgreSQL via `DATABASE_URL` (SQLite stays local default), `render.yaml`, `wsgi.py`, extension works with the local dashboard or any `*.onrender.com` dashboard |
| 14:14 | `c34be84` | | Postgres fixes found on Neon (empty-parameter call, `scramp` pin); Render region next to the database |
| 14:39 | `8eaf549` | | Render + Neon both in **Singapore** (was US: every request crossed the world) |
| 14:51 | `26375be` | | Neon **direct** address instead of the pooler (fixed random "unnamed prepared statement does not exist") |
| 15:15 | `dc5289f` | 3.10.1 | When LinkedIn's search page does not draw a job, read it on the job's own page |
| 15:25 | `759fdf3` | | Extension download unzips straight into a loadable folder |
| 15:43 | `aaf64c5` | 3.10.2 | Restored up to 8 reading windows (3.10.1's cap of 3 had slowed runs) |
| 15:54 | `9d99f64` | 3.10.3 | Skip LinkedIn's padding ("may not be exact matches") unless the card shows the wanted workplace |
| 16:14 | `eca7d6c` | 3.11.0 | **Fast mode**: LinkedIn's public job pages fetched in parallel (10 jobs ~6 s, 50 jobs ~45 s, was 1.5-5 min) |
| 16:22 | `7779d0e` | | Fast mode also saves the job poster as hiring contact when the job shows one |
| | `df9a7bd` | | Render refuses to start without a PostgreSQL `DATABASE_URL` (no silent temporary database) |
| | (this) | 3.11.1 | Start keeps you in the dashboard: the LinkedIn window opens in the background (still comes to the front on a LinkedIn warning); extra reading windows closed at the end |

## Where it runs
- **Local**: `python app.py` -> http://127.0.0.1:5000, data in `output/signedin.sqlite3`.
- **Hosted**: Render web service (Singapore) + Neon PostgreSQL (Singapore). Separate data from local.
- Extension: one install serves both; it reports to whichever dashboard pressed Start.

## Tests
105 offline tests (`python -m pytest -q`). `TEST_DATABASE_URL` runs them on PostgreSQL - only ever on a throwaway
database or Neon branch (they drop the tables).
