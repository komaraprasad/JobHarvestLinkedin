# JobHarvest – setup for team members (Windows)

Two packages - use the first one that runs on your PC:
- `JobHarvest-<version>.zip` - no install needed. Company PCs with Windows Application Control may block it
  ("An Application Control policy has blocked this file"); then use the second one or ask IT to allow it.
- `JobHarvest-python-<version>.zip` - needs Python 3.10+ (python.org, tick "Add to PATH"); double-click
  **Start JobHarvest.bat** instead of JobHarvest.exe in step 2 (first start needs internet for about a minute).

1. Unzip the package anywhere you can write to (e.g. Documents). Keep the folder together.
2. Double-click **JobHarvest.exe**. A console window opens and the dashboard opens at http://127.0.0.1:5000.
   Keep the console window open while you use it; close it to stop. Results are saved in the `output` folder next to the exe.
   (If Windows SmartScreen warns about an unknown app: More info -> Run anyway.)
3. Install the extension once: in the dashboard download **extension.zip** (or http://127.0.0.1:5000/extension.zip),
   unzip it, open `edge://extensions` (or `chrome://extensions`), turn on **Developer mode**, **Load unpacked**,
   select the unzipped `jobharvest-extension` folder.
4. Sign in to LinkedIn in that same browser, reload the dashboard: it must say **Extension connected**.
5. Enter role, location, filters and number of jobs (start with 10), press **Start**, download Excel/CSV at the end.

Port 5000 must be free. Each person runs their own copy: own results, own LinkedIn account, own daily limits.

**Risk:** this runs as your LinkedIn account. LinkedIn's User Agreement prohibits automated collection; the built-in
limits reduce the risk of restriction, they do not remove it. Contact profile links are personal data (GDPR/DPDP).
