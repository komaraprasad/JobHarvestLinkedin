# JobHarvest (in-house tool, formerly "LinkedIn Jobs Collector")

You enter a role, location and LinkedIn filters in a local dashboard and press **Start**. The tool opens LinkedIn
in your own signed-in browser with those filters, collects the jobs, and gives you Excel/CSV.

- **Local dashboard** (`app.py`, http://127.0.0.1:5000): where you work. Search form with LinkedIn's filters,
  live run log, results preview, Excel / CSV download. Stores results and enforces the safety limits.
- **Browser extension** (`extension/`): the "hands". Opens the LinkedIn search in a new window, clicks each job,
  reads the detail panel, goes to the next results page, then reads each company's About page once.

Nothing works without the extension and a LinkedIn sign-in in the same browser.

## Fields exported
Job Title · Company Name · Company Industry · Company Size · Contact Profile Link(s) · Job Description
(plus Location, Workplace, Job URL, Job ID, Company URL, Industry Source, Date Collected, Last Seen)

Blank means "not shown on LinkedIn". The tool never guesses.

## Setup (Windows 11, PowerShell, inside this folder)
```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m pytest -q          # offline tests, should show 91 passed
python app.py                # keep running, then open http://127.0.0.1:5000
```
Install the extension: `edge://extensions` → Developer mode → **Load unpacked** → select the `extension` folder.
Details: `extension/README.md`.

## Usage
1. Start `python app.py`, open http://127.0.0.1:5000 (it must say **Extension connected**) and sign in to
   LinkedIn in the same browser.
2. Enter role, location and filters (date posted, workplace type, experience level, job type, Easy Apply,
   under 10 applicants, sort), choose jobs wanted (start with 10), press **Start**.
3. LinkedIn opens in a new window with your filters; leave it open. Watch the run in the dashboard.
4. Download Excel or CSV from the dashboard.

## Safety limits (enforced in code)
- Random 3-5 s pause before every page load and 1.2-2.5 s before each job click, plus an 8-12 s break every 25.
- Per run: max 100 new jobs, 6 result pages, 60 company pages. Per day: 30 result pages, 300 job reads,
  200 company pages.
- Stops at once on a security check, captcha, "unusual activity", sign-in page or rate-limit text.
- Only job results, job details and company About pages are read. No profiles, messages or applying.
- No passwords, cookies or login automation. Jobs collected before are skipped; each company is read once.

## Risk (be honest with the manager)
This runs as **your LinkedIn account**. LinkedIn's User Agreement prohibits automated collection; the limits
reduce the risk of restriction, they do not remove it. Contact profile links are personal data (GDPR/DPDP):
store and share them only as needed.

## Verified vs unverified
Verified offline (2026-11-11): 75 tests (91 as of 2026-11-13) (run logic, locations, limits, de-duplication, warning stop, exports, dashboard),
and the full flow in Edge with the extension against **fake LinkedIn pages** on localhost (dashboard form →
Start → new window with the filters → click each job → next page → company pages once → Excel/CSV; a
security-check page stops the run).
**Not verified:** real signed-in LinkedIn pages. Selectors live in `extension/config.js` and may need adjusting
after the first real run.

Guest (no-login) mode was removed on 2026-11-11; a backup of the earlier version is in
`..\linkedin_jobs_tool_backup_before_removing_guest_mode.zip`.

## Layout
`app.py` dashboard · `templates/index.html` dashboard page · `ljt/extapi.py` API for the extension ·
`ljt/extstore.py` run state, limits, de-duplication (SQLite) · `ljt/search.py` search filters ·
`ljt/locations.py` location resolution (provided module, unchanged) · `ljt/geo_directory.py` LinkedIn location IDs ·
`ljt/geo_db.py` read-only access to `world_geo.db` (158k places; adds LinkedIn IDs, suggestions, city→country) ·
`ljt/place_search.py` connects locations.py to searches (suggestions, REGION facet, geoId, per-job check) ·
`ljt/export.py` xlsx/csv · `extension/` browser extension (`config.js` = all LinkedIn selectors and pacing).

## Building the team packages
`powershell -ExecutionPolicy Bypass -File build.ps1` runs the tests, then builds into `dist\`:
- `JobHarvest-<ver>.zip` – standalone JobHarvest.exe (no Python needed; may be blocked by Windows Application Control
  on managed PCs because it is unsigned).
- `JobHarvest-python-<ver>.zip` – same app + `Start JobHarvest.bat` (needs Python 3.10+; works where the exe is blocked).
Hand out the zip together with `DEPLOY.md` (copied in as README.md). Each person runs their own copy.
