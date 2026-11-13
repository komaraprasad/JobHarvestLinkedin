# Deploy JobHarvest on Render (free) with a Neon database (free)

Result: one link, e.g. `https://jobharvest.onrender.com`, that the team opens. **No login: anyone with the link can
see all collected jobs (incl. contact links) and start runs.** Share it only inside the team.

Each user still needs (once): the JobHarvest extension (v3.10.0+) in Edge/Chrome and a LinkedIn sign-in in that
browser. The LinkedIn reading happens in their browser, as their account; the website only stores and shows results.

## 1. Database: Neon (free, data kept permanently)
1. Sign up at https://neon.tech -> **New project** (region: AWS Singapore / closest to you).
2. Dashboard -> **Connect** -> copy the connection string
   (`postgresql://user:password@ep-....neon.tech/neondb?sslmode=require`). Keep it secret.
   Tables are created automatically on first start.

## 2. Code on GitHub (private repo)
In PowerShell, inside the `linkedin_jobs_tool` folder:
```
git init
git add .
git commit -m "JobHarvest: hosted (Render + Postgres) support"
```
Create an empty **private** repo on github.com, then:
```
git remote add origin https://github.com/<you>/jobharvest.git
git branch -M main
git push -u origin main
```
`.gitignore` keeps out `output/` (your collected data), `.venv/`, builds and backups. `world_geo.db` (28 MB) is included; it is needed.

## 3. Web service: Render
1. Sign up at https://render.com with GitHub -> **New + -> Blueprint** -> pick the repo (it reads `render.yaml`).
2. When asked for **DATABASE_URL**, paste the Neon connection string -> **Apply**.
3. Wait for the build (~3 min). Open `https://<service-name>.onrender.com` - the dashboard appears.

Manual alternative (New + -> Web Service): Runtime Python · Build `pip install -r requirements.txt` ·
Start `gunicorn wsgi:app --workers 1 --threads 8 --timeout 120 --bind 0.0.0.0:$PORT` · Instance Free ·
env vars `PYTHON_VERSION=3.13.5`, `DATABASE_URL=<Neon string>`. **Keep 1 worker.**

## 4. Each team member
1. Open the link -> download the extension (`/extension.zip`), unzip, `edge://extensions` -> Developer mode ->
   **Load unpacked** -> the unzipped folder. Card must say **JobHarvest 3.10.0**.
2. Sign in to LinkedIn in the same browser, reload the dashboard: **Extension connected** -> Start.

## Know before you share
- **Free Render sleeps after 15 min idle**: the first visit then takes ~1 min. Runs keep it awake.
- **One run at a time for the whole team**, and the daily LinkedIn limits are shared by everyone (they were made
  for one account). A second person pressing Start gets "Another run is still active".
- Exports and debug snapshots are temporary on Render (lost on restart); the data itself is in Neon.
- The extension accepts dashboards on `127.0.0.1:5000`, `localhost:5000` and `*.onrender.com` only. Another host
  (own domain) -> add it in `extension/config.js` (DASHBOARDS) and `extension/manifest.json`.
- Moving existing local data: not automatic. The hosted app starts empty.
- LinkedIn's User Agreement prohibits automated collection; contact links are personal data (GDPR/DPDP).

## Check the database before going live (optional, recommended)
Create a **separate Neon branch** (Branches -> New branch, e.g. `test`) and run the full test suite against it -
it DROPS its tables, so never point it at the live branch:
```
$env:TEST_DATABASE_URL = "<connection string of the test branch>"
.venv\Scripts\python.exe -m pytest -q
```
