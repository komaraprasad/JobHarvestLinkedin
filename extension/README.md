# JobHarvest extension (v3.11.0)

The extension is the "hands" of the local JobHarvest dashboard (http://127.0.0.1:5000).
You work in the dashboard; the extension does the LinkedIn part in your own signed-in browser.

## Install (Edge or Chrome)
1. Open `edge://extensions` (or `chrome://extensions`) and turn on **Developer mode**.
2. **Load unpacked** and select this `extension` folder. Keep the folder.
3. After an update: press **Reload** on the extension card, then reload the dashboard page (F5). The card must say **JobHarvest 3.11.0**.

## Use
1. Start the dashboard: in the project folder `.venv\Scripts\python.exe app.py`, open http://127.0.0.1:5000.
   It must say **Extension connected**. Sign in to LinkedIn in the same browser.
2. Enter role, location and filters (date posted, workplace type, experience, job type, Easy Apply,
   under 10 applicants, sort), jobs wanted, then press **Start**.
3. LinkedIn opens in a **new window** with those filters. The extension clicks each job (4-8 s apart), reads
   the detail panel, goes to the next results page until it has the number you asked for, then reads each new
   company's About page once. Leave that window open (it can be behind other windows).
4. Watch the dashboard; download **Excel** or **CSV** when it ends. **Stop** keeps what was collected.

The toolbar popup can also **Save this job** for the single job you are looking at.

### Safety rules (enforced in code)
- Random **3-5 s pause before every page load** and **1.2-2.5 s before each job click**, plus an 8-12 s break every 25.
- Per run: max **100 new jobs**, **6** result pages, **60** company pages. Per day: **30** result pages,
  **300** job reads, **200** company pages (the dashboard shows today's usage).
- Stops **immediately** on a security check / captcha / "unusual activity" / sign-in page / rate-limit text and
  brings that window to the front so you can see it. Do not run again that day.
- Only job results, job details and company About pages. No profiles, messages, applying or saving jobs.
- No passwords, cookies or login automation. Nothing is guessed: unreadable values stay blank with a reason.
- Jobs collected before are skipped; each company is read once and reused.

All LinkedIn selectors, warning phrases and pacing live in `config.js`.

## Risk (read this)
This runs as **your LinkedIn account**. LinkedIn's User Agreement prohibits automated collection; the limits
reduce the risk of restriction, they do not remove it. Contact links are personal data (GDPR/DPDP).

## LinkedIn's new "AI job search" page
On some accounts LinkedIn sends /jobs/search/ to its newer /jobs/search-results/ page, which drops the filter
settings. The extension then searches for role + place ("python developer in Hyderabad, Telangana, India";
LinkedIn turns the place into its location filter), clears filters left on from an earlier LinkedIn session,
and sets each of your filters with LinkedIn's own filter buttons (Date posted, Experience level, Workplace type,
Employment type, Easy Apply, Under 10 applicants). Every step is written to the run log. If a filter cannot be
set, a page snapshot is saved to output/debug for diagnosis and the run continues; every job is still checked
against the filters it shows (location, Remote/Hybrid/On-site, job type, Easy Apply).

## Verified vs unverified
Verified on the REAL LinkedIn pages saved from the first live run (2026-11-11, new layout): 25 of 25 jobs found
on the results page, title / company / location / description / company size read from the detail panel, and
Industry + Company size read from the company About page.
Verified offline (2026-11-11) in Edge with this extension loaded, against **fake LinkedIn pages** on localhost:
dashboard form → Start → new window with the filters in the address → 4 jobs clicked and read across 2 result
pages → 3 companies read once → Excel/CSV. A security-check page stops the run at once. 14 server tests pass. Also verified on a fake page WITHOUT LinkedIn's classic class names (newer layout): jobs found from plain job links, details read from the "About the job" section.
**Not verified:** real signed-in LinkedIn pages. Send the run log + the HTML of any field that comes out blank.

## Fast mode (default since 3.11.0)
Jobs are read from LinkedIn's lightweight public job pages instead of opening each job in a window:
search (10 jobs per request), job page and company page are fetched directly from this browser, several at once,
at one steady pace (~4 requests/s, slowing down automatically when LinkedIn answers "too many requests").
Measured on real LinkedIn (2026-11-13): 10 jobs ~6 s, 50 jobs ~40 s, 100 jobs ~100 s - the limit is LinkedIn's
rate per connection (~2-3 requests/s); every new job costs one request plus one per company not seen before.
Not on public pages: hiring-team contacts and the Remote/Hybrid label (LinkedIn's own filter still applies).
If LinkedIn refuses the public pages, the run continues automatically with the LinkedIn-window method.
Settings: `FAST` in `config.js` (`enabled: false` turns it off).
