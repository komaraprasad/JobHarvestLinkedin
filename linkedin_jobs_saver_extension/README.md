# LinkedIn Jobs Saver (browser extension, manual)

Saves the LinkedIn job **you are looking at** when you click the extension's **Save this job** button,
then exports everything you saved to Excel/CSV (same columns as the Python tool).

## What it does and does not do
- Reads the open job page **only when you open the popup**. Nothing runs in the background.
- Never clicks, scrolls, opens pages, or sends requests. You browse LinkedIn normally; it only copies what is on screen.
- Never guesses: a value that is not clearly shown stays blank and `Data Notes` says why.
  Industry is filled only from a labelled "Industries" field; company size only from an explicit "N employees" text.
- Saved jobs stay in this browser's extension storage until you export or **Clear all**.

## Install (Edge or Chrome, Windows)
1. Open `edge://extensions` (or `chrome://extensions`).
2. Turn on **Developer mode**.
3. Click **Load unpacked** and select this `extension` folder.
4. Pin the extension (puzzle icon → pin) so the button is visible.

## Use
1. Open a job on LinkedIn (`linkedin.com/jobs/view/...`, or click a job in search results so it shows on the right).
2. If the description is collapsed, click **See more** first.
3. Click the extension icon → check the preview → **Save this job**.
4. When done: **Excel** or **CSV** to download.

## Important
- When you are signed in, this runs as **your account**. Keep it manual and at human pace; do not automate clicking with it.
  LinkedIn's User Agreement prohibits automated collection; check with your manager before wide use.
- Contact profile links are personal data (GDPR/DPDP): keep and share only what is needed.

## Verified vs unverified
Verified offline: exports open in openpyxl with the right columns (special characters, Unicode, 32,000-char cell cap);
extraction on a guest-layout sample (class names used by the Python tool on live guest pages) and a **synthetic**
signed-in-layout sample. **Not verified:** real signed-in LinkedIn pages — those class names change often, so check the
popup preview on your first few jobs and report any field that is blank when it is visible on the page.
