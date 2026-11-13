// Background worker. When you press Start on the dashboard it opens LinkedIn in a NEW WINDOW of your signed-in
// browser with your filters applied, clicks each job in the results list (4-8 s apart), reads the detail panel,
// moves to the next results page, then reads each new company's About page once. It stops at once on any
// LinkedIn warning and leaves that page open. All waiting happens here (not in the page), so it keeps working
// even if the LinkedIn window is behind other windows.
importScripts("config.js");
const C = self.LJT_CONFIG;

let running = null;
let pagesSinceBreak = 0;

const sleep = ms => new Promise(r => setTimeout(r, ms));
const rand = (a, b) => a + Math.random() * (b - a);

// The dashboard this run belongs to: the local one (C.SERVER) or a hosted one. Taken from the page that pressed
// Start, accepted only for the addresses in C.DASHBOARDS, and kept in storage so a restarted worker still knows it.
let SERVER = C.SERVER;
const dashboardOrigin = url => {
  try { const o = new URL(url).origin; return C.DASHBOARDS.some(re => re.test(o)) ? o : ""; } catch { return ""; }
};
async function api(path, body) {
  const r = await fetch(`${SERVER}/api/ext${path}`, body === undefined ? {} :
    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!r.ok) throw new Error(`dashboard server answered HTTP ${r.status}`);
  return r.json();
}
const log = (rid, msg) => api(`/log/${rid}`, { msg }).catch(() => {});

// Waits that keep the service worker alive (an extension API call resets Chrome's idle timer).
async function pause(ms) {
  const end = Date.now() + ms;
  while (Date.now() < end) { await sleep(Math.min(5000, end - Date.now())); await chrome.runtime.getPlatformInfo(); }
}

async function politePause(rid, kind = "page") {
  const P = C.PACING;
  if (pagesSinceBreak >= P.breakEveryPages) {
    const ms = rand(P.breakMinMs, P.breakMaxMs);
    await log(rid, `Short break (${Math.round(ms / 1000)} s) after ${pagesSinceBreak} pages/jobs.`);
    await pause(ms);
    pagesSinceBreak = 0;
  }
  await pause(kind === "card" ? rand(P.cardMinMs, P.cardMaxMs) : rand(P.minPauseMs, P.maxPauseMs));
  pagesSinceBreak++;
}

// Calls one reader function in the LinkedIn tab, injecting the readers first if the page is new.
async function call(tabId, fn, args = []) {
  const run = () => chrome.scripting.executeScript({ target: { tabId },
    func: (name, a) => (self[name] ? self[name](...a) : "__ljt_missing__"), args: [fn, args] });
  let [{ result }] = await run();
  if (result === "__ljt_missing__") {
    await chrome.scripting.executeScript({ target: { tabId }, files: ["config.js", "extract.js", "readers.js"] });
    [{ result }] = await run();
  }
  return result;
}

// Polls a reader until it returns something truthy; checks for LinkedIn warnings on every poll.
async function waitUntil(tabId, fn, args = [], ms = C.PACING.renderWaitMs, every = 500) {
  const end = Date.now() + ms;
  for (;;) {
    const warn = await call(tabId, "__ljtCheck").catch(() => null);
    if (warn) return { stop: warn };
    const v = await call(tabId, fn, args).catch(() => null);
    if (v) return { ok: v };
    if (Date.now() > end) return {};
    await sleep(every);
  }
}

// LinkedIn draws the hiring team and "About the company" only in a window that is on screen. If they did not
// appear (the reading window was hidden behind another window), bring that window to the front for a moment, load
// the sections again, then give focus back. One window at a time.
let focusLock = Promise.resolve();
async function loadSections(rid, tabId, id) {
  await waitUntil(tabId, "__ljtLoadSections", [id], 8000, 300);
  if (await call(tabId, "__ljtCompanyDrawn", [id]).catch(() => true)) return;
  const run = async () => {
    const tab = await chrome.tabs.get(tabId).catch(() => null);
    if (!tab) return;
    const before = await chrome.windows.getLastFocused().catch(() => null);
    await chrome.windows.update(tab.windowId, { focused: true }).catch(() => {});
    await call(tabId, "__ljtResetSections").catch(() => {});
    await waitUntil(tabId, "__ljtLoadSections", [id], 6000, 300);
    const ok = await call(tabId, "__ljtCompanyDrawn", [id]).catch(() => false);
    if (before && before.id !== tab.windowId) await chrome.windows.update(before.id, { focused: true }).catch(() => {});
    if (!ok) await log(rid, `Job ${id}: the hiring team / company box did not appear even with its window in front.`);
  };
  const p = focusLock.then(run, run); focusLock = p.catch(() => {}); await p;
}

async function navigate(tabId, url) {
  const loaded = new Promise(resolve => {
    const timer = setTimeout(() => { chrome.tabs.onUpdated.removeListener(fn); resolve(false); }, C.PACING.pageLoadTimeoutMs);
    function fn(id, info) {
      if (id === tabId && info.status === "complete") { clearTimeout(timer); chrome.tabs.onUpdated.removeListener(fn); resolve(true); }
    }
    chrome.tabs.onUpdated.addListener(fn);
  });
  await chrome.tabs.update(tabId, { url });
  return loaded;
}

// The main LinkedIn window opens BEHIND the dashboard: you stay in JobHarvest while the run works in the background.
// (A LinkedIn warning still brings it to the front - see stopForWarning.)
async function openLinkedInWindow(dashboardWindowId) {
  const win = await chrome.windows.create({ url: "about:blank", focused: false, type: "normal", width: 1300, height: 900 });
  const tabId = win.tabs[0].id;
  try { await chrome.tabs.update(tabId, { autoDiscardable: false }); } catch {}
  if (dashboardWindowId) await chrome.windows.update(dashboardWindowId, { focused: true }).catch(() => {});
  return tabId;
}

async function stopForWarning(rid, tabId, reason) {
  const tab = await chrome.tabs.get(tabId).catch(() => null);
  await api(`/linkedin_stop/${rid}`, { reason, url: tab ? tab.url : "" });
  if (tab) await chrome.windows.update(tab.windowId, { focused: true }).catch(() => {});
}

// When the page doesn't look as expected, save its HTML (on this PC only) so the readers can be fixed exactly.
const snapped = new Set();
async function snapshot(rid, tabId, kind) {
  if (snapped.has(rid + kind)) return;
  snapped.add(rid + kind);
  try {
    const snap = await call(tabId, "__ljtDebugSnapshot", [kind]);
    const r = await api(`/debug/${rid}`, snap);
    await log(rid, `Saved a snapshot of this page for diagnosis: ${r.file}`);
  } catch (e) { await log(rid, "Could not save a page snapshot: " + e.message); }
}

// Waits until the results list changes after a filter (or gives up quietly after `ms`).
async function waitResultsChange(tabId, before, ms = 8000) {
  const end = Date.now() + ms;
  while (Date.now() < end) {
    await sleep(500);
    const warn = await call(tabId, "__ljtCheck").catch(() => null);
    if (warn) return { stop: warn };
    const now = await call(tabId, "__ljtResultsSignature").catch(() => before);
    if (now && now !== before) { await sleep(600); return { changed: true }; }
  }
  return { changed: false };
}

// Sets each filter with LinkedIn's own filter buttons on the AI search page. A filter that cannot be set is
// logged (with a page snapshot for diagnosis) and skipped; every job is still checked against it afterwards.
const OPEN_METHODS = ["mouse", "enter", "space", "label", "click"];
let openMethod = null;   // the way LinkedIn's filter lists opened last time (tried first next time)

async function applyUiFilters(rid, tabId, filters) {
  const ready = await waitUntil(tabId, "__ljtCardsReady");
  if (ready.stop) return ready;
  // LinkedIn keeps filters from earlier sessions (e.g. "Remote"). Clear them first so only yours apply.
  const left = (await call(tabId, "__ljtActiveFilters").catch(() => [])) || [];
  // Filters set in LinkedIn's "All filters" (salary, company, industry, ...) have no button in the filter bar, but
  // they are in the address. The search was opened with keywords only, so every f_... there is a leftover.
  const NAMES = { f_SAL: "Salary", f_C: "Company", f_I: "Industry", f_F: "Job function", f_T: "Job title", f_PP: "City",
                  f_TPR: "Date posted", f_E: "Experience level", f_WT: "Workplace type", f_JT: "Job type", f_AL: "Easy Apply",
                  f_EA: "Under 10 applicants", f_JIYN: "In my network", f_VJ: "Verified", f_BE: "Benefits", f_CR: "Country" };
  const tabNow = await chrome.tabs.get(tabId).catch(() => null);
  try {
    for (const k of new URL((tabNow && tabNow.url) || "about:blank").searchParams.keys())
      if (/^f_/.test(k)) { const n = NAMES[k] || k; if (!left.includes(n)) left.push(n); }
  } catch {}
  if (left.length) {
    const before = await call(tabId, "__ljtResultsSignature").catch(() => "");
    if (await call(tabId, "__ljtClickReset").catch(() => false)) {
      await log(rid, `Cleared filters left on from an earlier LinkedIn session: ${left.join(", ")}.`);
      const w = await waitResultsChange(tabId, before);
      if (w.stop) return w;
    } else await log(rid, `Filters left on from an earlier LinkedIn session: ${left.join(", ")} (no Reset button found).`);
    // Still a leftover filter in the address (Reset missing or it kept e.g. the salary filter): reopen the same search
    // without any f_... filter, then set only yours.
    const after = await chrome.tabs.get(tabId).catch(() => null);
    try {
      const u = new URL((after && after.url) || "");
      const extra = [...u.searchParams.keys()].filter(k => /^f_/.test(k));
      if (extra.length) {
        extra.forEach(k => u.searchParams.delete(k));
        await log(rid, `Removing leftover LinkedIn filters from the search: ${extra.map(k => NAMES[k] || k).join(", ")}.`);
        await politePause(rid);
        await navigate(tabId, u.toString());
        const again = await waitUntil(tabId, "__ljtCardsReady");
        if (again.stop) return again;
      }
    } catch {}
  }
  for (const f of filters) {
    if ((await api(`/state/${rid}`)).state !== "running") return {};
    await sleep(rand(700, 1400));
    // The previous filter's "Show results" reloads the page: wait for this filter's button to be back.
    const bar = await waitUntil(tabId, "__ljtPillReady", [f.pill, f.options || []], 12000);
    if (bar.stop) return bar;
    const what = f.toggle ? f.pill : `${f.pill} = ${f.options.join(", ")}`;
    const before = await call(tabId, "__ljtResultsSignature").catch(() => "");
    if (f.toggle) {
      if (await call(tabId, "__ljtToggleIsOn", [f.pill]).catch(() => null) === true) { await log(rid, `LinkedIn filter already on: ${f.pill}.`); continue; }
      let c = {};
      for (const m of ["label", "mouse", "click"]) {
        c = await call(tabId, "__ljtClickFilter", [f.pill, [], m]).catch(e => ({ error: e.message }));
        if (c.error) break;
        await sleep(700);
        if (await call(tabId, "__ljtToggleIsOn", [f.pill]).catch(() => null) !== false) break;   // on (or unknown): done
      }
      if (c.error) { await log(rid, `Could not apply LinkedIn filter ${what}: ${c.error}. Jobs are still checked against it.`); await snapshot(rid, tabId, "filter-bar"); continue; }
      if (await call(tabId, "__ljtToggleIsOn", [f.pill]).catch(() => null) === false) {
        await log(rid, `Could not apply LinkedIn filter ${what}: it did not switch on. Jobs are still checked against it.`);
        await snapshot(rid, tabId, "filter-" + f.pill); continue;
      }
      const w = await waitResultsChange(tabId, before);
      if (w.stop) return w;
      await log(rid, `Applied LinkedIn filter: ${what}${w.changed ? "" : " (results did not visibly change)"}.`);
      continue;
    }
    // Open the list: try the ways a person opens it, until it opens. The method that works is remembered.
    let open = {}, c = {};
    const methods = openMethod ? [openMethod, ...OPEN_METHODS.filter(m => m !== openMethod)] : OPEN_METHODS;
    for (const m of methods) {
      c = await call(tabId, "__ljtClickFilter", [f.pill, f.options, m]).catch(e => ({ error: e.message }));
      if (c.error) break;
      open = await waitUntil(tabId, "__ljtDropdownReady", [f.pill, f.options], 2500);
      if (open.stop) return open;
      if (open.ok) { if (openMethod !== m) { openMethod = m; await log(rid, `LinkedIn filter lists open with: ${m}.`); } break; }
      await call(tabId, "__ljtCloseFilter", [f.pill, f.options]).catch(() => {});
    }
    if (c.error) { await log(rid, `Could not apply LinkedIn filter ${what}: ${c.error}. Jobs are still checked against it.`); await snapshot(rid, tabId, "filter-bar"); continue; }
    if (!open.ok) {
      await log(rid, `Could not apply LinkedIn filter ${what}: its list did not open (tried ${methods.join(", ")}). Jobs are still checked against it.`);
      await snapshot(rid, tabId, "filter-" + f.pill);
      await call(tabId, "__ljtCloseFilter", [f.pill, f.options]).catch(() => {});
      continue;
    }
    await sleep(400);
    const sel = await call(tabId, "__ljtSelectOptions", [f.pill, f.options]).catch(e => ({ error: e.message }));
    if (sel.error || !sel.picked.length) {
      await log(rid, `Could not apply LinkedIn filter ${what}: ${sel.error || "options not found"}${sel.offered ? ` (LinkedIn offers: ${sel.offered.join(" | ")})` : ""}. Jobs are still checked against it.`);
      await snapshot(rid, tabId, "filter-" + f.pill);
      await call(tabId, "__ljtCloseFilter", [f.pill]).catch(() => {});
      continue;
    }
    await sleep(500);
    if (!(await call(tabId, "__ljtConfirmFilter", [f.pill, f.options]).catch(() => false))) await call(tabId, "__ljtCloseFilter", [f.pill, f.options]).catch(() => {});
    const w = await waitResultsChange(tabId, before);
    if (w.stop) return w;
    await log(rid, `Applied LinkedIn filter: ${f.pill} = ${sel.picked.join(", ")}` +
      (sel.missing.length ? ` (not offered: ${sel.missing.join(", ")})` : "") + (w.changed ? "." : " (results did not visibly change)."));
  }
  const again = await waitUntil(tabId, "__ljtCardsReady");
  return again.stop ? again : {};
}

// A card line that is really a place ("Pune, Maharashtra, India", "India (Remote)", "Bengaluru"), not a company
// line such as "Accenture in India".
const placeLike = loc => !!loc && (/,|\((remote|hybrid|on-site)\)/i.test(loc) ||
  (/^[A-Za-z .'-]+$/.test(loc) && loc.trim().split(/\s+/).length <= 3 && !/\bin\b/i.test(loc)));

// Diagnosis: the first job of a run read without any hiring contact is saved (panel + what the people section held),
// so the reader can be matched to LinkedIn's real markup.
const contactNoted = new Set();
// Fallback when LinkedIn's search page does not draw a job: open the job's OWN page (/jobs/view/<id>/) in this tab
// and read it there with the same readers. Returns the data, {stop} on a LinkedIn warning, or null (+ a snapshot).
async function readJobPage(rid, tab, id) {
  if (!(await navigate(tab, `https://www.linkedin.com/jobs/view/${id}/`))) return null;
  const shown = await waitUntil(tab, "__ljtPaneReady", [id], 15000);
  if (shown.stop) return { stop: shown };
  if (!shown.ok) { await snapshot(rid, tab, "job-page"); return null; }
  await sleep(C.PACING.settleMs);
  if (await call(tab, "__ljtExpandDescription").catch(() => false)) await sleep(400);
  await loadSections(rid, tab, id);
  const data = await call(tab, "__ljtReadPane", [id]).catch(() => null);
  if (!data || !data.job_title || !data.job_description) { await snapshot(rid, tab, "job-page"); return null; }
  await noteContacts(rid, tab, id, data);
  return data;
}
let fallbackTab = null;   // one reader window for job pages, opened when first needed, closed when the run ends
async function fallbackReader(mainTab) {
  if (fallbackTab && await chrome.tabs.get(fallbackTab).catch(() => null)) return fallbackTab;
  fallbackTab = (await openWorkerTabs(mainTab, 1))[0] || null;
  return fallbackTab;
}

async function noteContacts(rid, tab, id, data) {
  if (!data || data.contact_profile_links || contactNoted.has(rid)) return;
  contactNoted.add(rid);
  const ps = data.people_section || {};
  await log(rid, `Job ${id}: no hiring contact found (hiring heading: ${ps.hiring_heading ? "yes" : "no"}, ` +
    `"People you can reach out to": ${ps.people_heading ? "yes" : "no"}${(ps.seen || []).length ? ", people: " + ps.seen.join(" | ") : ""}). Saving this page for diagnosis.`);
  await snapshot(rid, tab, "no-contacts");
}

// Skip a job that breaks the filters as soon as its panel shows its labels (e.g. "Contract" when Part-time was asked),
// before reading the description, scrolling for the hiring team and the company box. Returns the quick data if it is
// a mismatch (saved as "skipped" by the server), else null.
async function quickSkip(rid, tab, id, cardLocation) {
  const quick = await call(tab, "__ljtReadPane", [id]).catch(() => null);
  if (!quick) return null;
  const loc = cardLocation || quick.location || "";
  const r = await api(`/quickcheck/${rid}`, { tags: quick.pane_tags || [], location: loc }).catch(() => ({}));
  if (!r.mismatch) return null;
  if (cardLocation) quick.location = cardLocation;
  return quick;
}

async function tabClosed(rid) {
  await log(rid, "The LinkedIn window was closed, so the run stopped. Jobs collected so far are kept. Keep that window open during a run (it can be behind other windows).");
  await api(`/stop/${rid}`, {});
  return {};
}

// Extra LinkedIn windows (one tab each) for reading several jobs at once.
async function openWorkerTabs(mainTab, k) {
  const main = await chrome.tabs.get(mainTab).catch(() => null);
  if (!main) return [];
  // Each extra reader gets its OWN small window where its tab is the active one: LinkedIn draws the lower parts of
  // a job ("Meet the hiring team") only in a visible tab, never in a background tab. Closing the tab closes it.
  const win = await chrome.windows.get(main.windowId).catch(() => null);
  const tabs = [];
  for (let i = 0; i < k; i++) {
    const w = await chrome.windows.create({ url: "about:blank", focused: false, type: "normal", width: 900, height: 820,
      left: ((win && win.left) || 0) + 40 * (i + 1), top: ((win && win.top) || 0) + 40 * (i + 1) }).catch(() => null);
    const t = w && w.tabs && w.tabs[0];
    if (t) tabs.push(t.id);
  }
  // Remembered so they are closed even if the run ends unexpectedly.
  const { workerTabs = [] } = await chrome.storage.session.get("workerTabs");
  await chrome.storage.session.set({ workerTabs: [...workerTabs, ...tabs] });
  return tabs;
}

// One results page: list the jobs, click each new one, read the detail panel, send it to the dashboard.
async function doSearchPage(rid, t, tabId) {
  const pageDone = (ids, n, more) => api(`/page_done/${rid}`, { page: t.page, ids, n_new: n, has_more: more });
  const ready = await waitUntil(tabId, "__ljtCardsReady");
  if (ready.stop) return ready;
  if (!ready.ok) {
    await log(rid, `Result page ${t.page + 1}: no job cards found on the page.`);
    await snapshot(rid, tabId, "results-page");
    await pageDone([], 0, false); return {};
  }
  for (let i = 0; i < 5; i++) { await call(tabId, "__ljtScrollList", [i, 5]).catch(() => {}); await sleep(250); }
  const list = await call(tabId, "__ljtListCards");
  if (list.no_results) { await log(rid, "LinkedIn shows no matching jobs for these filters."); await snapshot(rid, tabId, "results-page"); }
  else await log(rid, `Result page ${t.page + 1}: found ${list.ids.length} jobs.`);
  // Server drops cards already collected or whose card shows another location, so they are never clicked.
  const toOpen = (await api(`/precheck/${rid}`, { cards: list.cards || list.ids.map(id => ({ id })) })).read || [];

  // 1. In the main tab: cards further down are drawn only when near the screen, so the first check may not have
  //    seen "Bengaluru (Hybrid)". Scroll each one into view and check it again (a wrong one is never opened).
  const queue = [], cardLoc = {};
  for (const id of toOpen) {
    if (!(await chrome.tabs.get(tabId).catch(() => null))) return tabClosed(rid);
    const listed = (list.cards || []).find(c => c.id === id);
    if (!listed || !listed.location) {
      let info = await call(tabId, "__ljtCardInfo", [id]).catch(() => null);
      if (info && !info.location) { await sleep(350); info = await call(tabId, "__ljtCardInfo", [id]).catch(() => null); }
      if (info && info.location) {
        const again = (await api(`/precheck/${rid}`, { cards: [info] })).read || [];
        if (!again.includes(id)) continue;
        cardLoc[id] = info.location;
      }
    } else cardLoc[id] = listed.location;
    queue.push(id);
  }

  let n = 0, stopped = null, enough = false;
  const retry = [];
  const send = async res => { n++; const r = await api(`/card/${rid}`, res); if (!r.continue_) enough = true; };

  // 2. Several LinkedIn tabs read jobs at the same time. Each opens LinkedIn's own job-search address for one job
  //    (?currentJobId=...), which shows that job in the detail panel, and reads it with the usual reader.
  // More jobs to read -> more windows (about one per 5 jobs), between PARALLEL_TABS and MAX_PARALLEL_TABS, so a
  // bigger run takes about as long as a small one.
  // Time budget: enough windows that the jobs still needed are read in about READ_BUDGET_MS (one job takes a window
  // about JOB_MS incl. the hiring team), between PARALLEL_TABS and MAX_PARALLEL_TABS.
  const st0 = await api(`/state/${rid}`).catch(() => ({}));
  const need = Math.min(queue.length, Math.max(1, Math.ceil(((st0.target || queue.length) - (st0.read || 0)) * 1.3)));
  const want = Math.ceil(need * (C.PACING.jobMs || 4500) / (C.PACING.readBudgetMs || 35000));
  const k = Math.min(Math.max(C.PARALLEL_TABS || 1, want), C.MAX_PARALLEL_TABS || C.PARALLEL_TABS || 1, queue.length);
  if (k > 1 && t.ai_url) {
    const tabs = await openWorkerTabs(tabId, k);
    if (tabs.length > 1) await log(rid, `Reading ${queue.length} jobs with ${tabs.length} LinkedIn windows at once.`);
    const worker = async (wt, i) => {
      await sleep(i * 400);                                     // stagger the tabs
      while (queue.length && !stopped && !enough) {
        if ((await api(`/state/${rid}`)).state !== "running") { enough = true; break; }
        const id = queue.shift();
        await pause(rand(C.PACING.parallelMinMs, C.PACING.parallelMaxMs));
        const u = new URL(t.ai_url); u.searchParams.set("currentJobId", id);
        if (!(await navigate(wt, u.toString()))) { retry.push(id); continue; }
        const shown = await waitUntil(wt, "__ljtPaneReady", [id], 12000);
        if (shown.stop) { stopped = shown; break; }
        if (!shown.ok) {   // search page did not draw this job: read it on its own page in this window
          const d = await readJobPage(rid, wt, id);
          if (d && d.stop) { stopped = d.stop; break; }
          if (d) { if (placeLike(cardLoc[id])) d.location = cardLoc[id]; if (!stopped && !enough) await send({ job_id: id, data: d }); }
          else retry.push(id);
          continue;
        }
        await sleep(C.PACING.settleMs);
        const skipNow = await quickSkip(rid, wt, id, placeLike(cardLoc[id]) ? cardLoc[id] : "");
        if (skipNow) { if (!stopped && !enough) await send({ job_id: id, data: skipNow }); continue; }
        if (await call(wt, "__ljtExpandDescription").catch(() => false)) await sleep(400);
        await loadSections(rid, wt, id);   // draws the hiring team + "About the company" before reading
        const data = await call(wt, "__ljtReadPane", [id]).catch(() => null);
        if (!data || !data.job_title || !data.job_description) { retry.push(id); continue; }   // read again in the main tab
        if (placeLike(cardLoc[id])) data.location = cardLoc[id];   // the card's place line ("India (Remote)" keeps its workplace)
        await noteContacts(rid, wt, id, data);
        if (!stopped && !enough) await send({ job_id: id, data });
      }
    };
    // Done when all tabs finish, or at once when enough jobs are collected (tabs still loading a job are closed).
    let allDone = false;
    const all = Promise.all(tabs.map((wt, i) => worker(wt, i))).then(() => { allDone = true; });
    const enoughNow = new Promise(r => { const iv = setInterval(() => { if (enough || stopped || allDone) { clearInterval(iv); r(); } }, 200); });
    await Promise.race([all, enoughNow]);
    for (const wt of tabs) await chrome.tabs.remove(wt).catch(() => {});
    if (stopped) { await pageDone(list.ids, n, false); return stopped; }
    if (retry.length && !enough) await log(rid, `${retry.length} job(s) did not show in the extra tabs; reading them in the main tab.`);
  }

  // 3. Main tab, one job at a time: everything when only one tab is used, plus any job the extra tabs could not show.
  for (const id of enough ? [] : [...retry, ...queue]) {
    if ((await api(`/state/${rid}`)).state !== "running") break;
    // The LinkedIn tab was closed (or discarded by the browser): stop now, never record empty "not read" jobs.
    if (!(await chrome.tabs.get(tabId).catch(() => null))) return tabClosed(rid);
    await politePause(rid, "card");
    const clicked = await call(tabId, "__ljtClickCard", [id]).catch(e => ({ error: e.message }));
    let res;
    if (clicked && clicked.error) res = { job_id: id, error: clicked.error };
    else {
      const shown = await waitUntil(tabId, "__ljtPaneReady", [id]);
      if (shown.stop) { await pageDone(list.ids, n, false); return shown; }
      if (!shown.ok) {
        await snapshot(rid, tabId, "detail-panel");
        const ft = await fallbackReader(tabId);
        const d = ft ? await readJobPage(rid, ft, id) : null;
        if (d && d.stop) { await pageDone(list.ids, n, false); return d.stop; }
        res = d ? { job_id: id, data: d } : { job_id: id, error: "job did not show on the search page or on its own page" };
        if (d) await log(rid, `Job ${id}: read from its own page (the search page did not show it).`);
      }
      else {
        await sleep(C.PACING.settleMs); // let description, hiring team and company box draw
        const skipNow = await quickSkip(rid, tabId, id, "");
        if (skipNow) { await send({ job_id: id, data: skipNow }); if (enough) break; continue; }
        if (await call(tabId, "__ljtExpandDescription").catch(() => false)) await sleep(400);
        await loadSections(rid, tabId, id);   // draws the hiring team + "About the company" before reading
        res = { job_id: id, data: await call(tabId, "__ljtReadPane", [id]) };
        await noteContacts(rid, tabId, id, res.data);
        if (!res.data.job_title || !res.data.job_description) await snapshot(rid, tabId, "detail-panel");
      }
    }
    if (res.error && /no tab with id/i.test(res.error)) continue;   // tab gone: the check above stops the run
    await send(res);
    if (enough) break;
  }
  await pageDone(list.ids, n, !!list.has_more);
  return {};
}

async function doCompany(rid, t, tabId) {
  const ready = await waitUntil(tabId, "__ljtCompanyReady", [], C.PACING.companyWaitMs || C.PACING.renderWaitMs);
  if (ready.stop) return ready;
  const data = ready.ok ? await call(tabId, "__ljtReadCompany") : { status: "not found", note: "About details did not appear within the wait time" };
  if (data.status !== "ok") await snapshot(rid, tabId, "company-page");
  await api(`/company_result/${rid}`, { company_url: t.company_url, data });
  return {};
}

// Clicks "Next" and waits until the first job in the list changes. Returns true, or "none" if there is no Next.
async function nextAiPage(tabId) {
  const before = await call(tabId, "__ljtFirstJobId").catch(() => null);
  if (!(await call(tabId, "__ljtClickNext").catch(() => false))) return "none";
  const end = Date.now() + C.PACING.renderWaitMs;
  while (Date.now() < end) {
    await sleep(500);
    const now = await call(tabId, "__ljtFirstJobId").catch(() => null);
    if (now && now !== before) return true;
  }
  return true; // list did not change in time; already-collected jobs are skipped, so nothing is read twice
}

// ---------- FAST MODE: LinkedIn's public job pages, fetched directly and in parallel (no windows, no rendering) ----------
// Search (10 cards per request), job page (~0.7 s) and company page (~1 s) are plain HTML that the server parses
// (ljt/guest.py). Fetched WITHOUT cookies from this browser (your own connection). On HTTP 429/5xx it waits and retries;
// if LinkedIn keeps refusing, the run switches back to the normal LinkedIn-window method.
// One steady pace for ALL public requests (LinkedIn allows ~2-3 per second per connection; bursts get HTTP 429).
// Each request takes the next free time slot; a 429 widens the gap, every success narrows it back to the minimum.
const PACE = { gap: 0, next: 0 };
async function slot() {
  if (!PACE.gap) PACE.gap = C.FAST.minGapMs;
  const now = Date.now(), at = Math.max(now, PACE.next);
  PACE.next = at + PACE.gap;
  if (at > now) await sleep(at - now);
}
async function guestFetch(url) {
  for (let attempt = 0; attempt < 4; attempt++) {
    await slot();
    const r = await fetch(url, { credentials: "omit", headers: { "Accept": "text/html" } }).catch(() => null);
    if (r && r.ok) { PACE.gap = Math.max(C.FAST.minGapMs, PACE.gap * 0.93); return await r.text(); }
    if (r && r.status !== 429 && r.status < 500) return null;
    if (r && r.status === 429) PACE.gap = Math.min(C.FAST.maxGapMs, PACE.gap * 1.6);
    await sleep(800 * (attempt + 1));
  }
  return null;
}
async function pool(items, n, fn) {           // run fn over items with at most n at once
  const queue = [...items];
  await Promise.all(Array.from({ length: Math.min(n, queue.length) }, async (_, i) => {
    await sleep(i * 120);
    while (queue.length) { const it = queue.shift(); if (await fn(it) === "stop") queue.length = 0; }
  }));
}
async function fastSearchPage(rid, t) {
  const t0 = Date.now();
  const htmls = await Promise.all(t.guest.urls.map(guestFetch));
  if (!htmls.some(Boolean)) return null;                                   // refused -> caller falls back
  const r = await api(`/guest_search/${rid}`, { page: t.page, htmls: htmls.filter(Boolean) });
  await log(rid, `Result page ${t.page + 1} (fast): ${r.ids.length} jobs listed, ${r.read.length} to read, ${C.FAST.jobsAtOnce} at a time.`);
  let n = 0, enough = false;
  await pool(r.read, C.FAST.jobsAtOnce, async id => {
    if (enough) return "stop";
    const html = await guestFetch(t.guest.job_base + id);
    const res = await api(`/guest_job/${rid}`, { job_id: id, html: html || "", card_location: (r.locations || {})[id] || "",
                                                  error: html ? "" : "public job page did not load (LinkedIn refused)" });
    n++;
    if (!res.continue_) { enough = true; return "stop"; }
  });
  await api(`/page_done/${rid}`, { page: t.page, ids: r.ids, n_new: n, has_more: r.has_more && !enough });
  await log(rid, `Result page ${t.page + 1} (fast): done in ${((Date.now() - t0) / 1000).toFixed(1)} s.`);
  return {};
}
async function fastCompanies(rid, t) {
  const batch = [t, ...(await api(`/more_companies/${rid}?k=${C.FAST.companiesAtOnce - 1}`).catch(() => []))];
  await log(rid, `Reading ${batch.length} company page(s) at once (fast).`);
  let refused = 0;
  await pool(batch, C.FAST.companiesAtOnce, async c => {
    const html = await guestFetch(c.guest_url);
    if (!html) refused++;
    await api(`/guest_company/${rid}`, { company_url: c.company_url, html: html || "", error: html ? "" : "public company page did not load" });
  });
  return refused === batch.length ? null : {};
}

async function runLoop(rid, tabId) {
  if (running) return;
  running = rid;
  await chrome.storage.session.set({ activeRun: rid, tabId });
  // Keep this background worker alive for the whole run (the browser stops an "idle" worker after ~30 s,
  // which used to cut a run off in the middle).
  const keepAlive = setInterval(() => chrome.runtime.getPlatformInfo(() => {}), 20000);
  let homeUrl = null, aiMode = !!(await chrome.storage.local.get("aiSearch")).aiSearch;
  let fast = C.FAST && C.FAST.enabled;   // public pages first; the LinkedIn window is the fallback
  try {
    await log(rid, "Extension opened LinkedIn in a new window. Leave that window open (it can be behind other windows).");
    for (;;) {
      const t = await api(`/next/${rid}`);
      if (t.type === "done") {
        if (t.status !== "blocked" && homeUrl) await chrome.tabs.update(tabId, { url: homeUrl }).catch(() => {});
        break;
      }
      if (t.type === "search" && t.page === 0) homeUrl = t.url;
      if (fast && t.type === "search" && t.guest) {
        if (await fastSearchPage(rid, t)) continue;
        fast = false;
        await log(rid, "Fast mode: LinkedIn did not answer the public job search, so this run continues in the LinkedIn window.");
      }
      if (fast && t.type === "company" && t.guest_url) {
        if (await fastCompanies(rid, t)) continue;
        fast = false;
        await log(rid, "Fast mode: LinkedIn did not answer the public company pages, so this run continues in the LinkedIn window.");
        await api(`/company_result/${rid}`, { company_url: t.company_url, data: { status: "error", note: "public page refused" } });
        continue;
      }
      // Company pages: read several at the same time (main tab + extra tabs), like the jobs.
      if (t.type === "company" && (C.PARALLEL_TABS || 1) > 1) {
        if (!(await chrome.tabs.get(tabId).catch(() => null))) { await tabClosed(rid); break; }
        const batch = [t, ...(await api(`/more_companies/${rid}?k=${C.PARALLEL_TABS - 1}`).catch(() => []))];
        const tabs = [tabId, ...(batch.length > 1 ? await openWorkerTabs(tabId, batch.length - 1) : [])];
        if (tabs.length > 1) await log(rid, `Reading ${tabs.length} company pages at once.`);
        const results = await Promise.all(tabs.map(async (tab, i) => {
          const c = batch[i];
          await sleep(i * 600);
          await pause(rand(C.PACING.parallelMinMs, C.PACING.parallelMaxMs));
          if (!(await navigate(tab, c.url))) {
            await api(`/company_result/${rid}`, { company_url: c.company_url, data: { status: "error", note: "page did not load" } });
            return {};
          }
          return doCompany(rid, c, tab);
        }));
        // A company the extra tabs were not given (more than tabs) is picked up by the next round.
        for (const c of batch.slice(tabs.length))
          await api(`/company_result/${rid}`, { company_url: c.company_url, data: { status: "error", note: "not read (no free tab)" } });
        for (const wt of tabs.slice(1)) await chrome.tabs.remove(wt).catch(() => {});
        const warn = results.find(r => r && r.stop);
        if (warn) { await stopForWarning(rid, tabId, warn.stop); break; }
        continue;
      }
      await politePause(rid);
      if (!(await chrome.tabs.get(tabId).catch(() => null))) { await log(rid, "The LinkedIn window was closed, so the run stopped."); await api(`/stop/${rid}`, {}); break; }
      let ok;
      if (t.type === "search" && aiMode && t.page > 0) {
        // New AI-search layout: the address has no page number, so go to the next page with its "Next" button.
        ok = await nextAiPage(tabId);
        if (ok === "none") { await log(rid, "No more result pages."); await api(`/page_done/${rid}`, { page: t.page, ids: [], n_new: 0, has_more: false }); continue; }
      } else if (t.type === "search" && t.page === 0 && aiMode && t.ai_url) {
        homeUrl = t.ai_url;   // this account uses LinkedIn's AI search: open it directly (saves a page load)
        await log(rid, `Opening LinkedIn's job search for "${new URL(t.ai_url).searchParams.get("keywords")}", then setting your filters with LinkedIn's filter buttons.`);
        ok = await navigate(tabId, t.ai_url);
      } else {
        ok = await navigate(tabId, t.url);
        if (ok && t.type === "search" && t.page === 0 && t.ai_url && await call(tabId, "__ljtIsAiSearch").catch(() => false)) {
          // LinkedIn sent us to its new AI job search, which ignores the classic filter parameters.
          aiMode = true;
          await chrome.storage.local.set({ aiSearch: true });
          homeUrl = t.ai_url;
          const query = new URL(t.ai_url).searchParams.get("keywords");
          await log(rid, `LinkedIn opened its new AI job search, which drops the filter settings. Searching for "${query}", then setting your filters with LinkedIn's filter buttons. Each job is also checked against your filters.`);
          await politePause(rid);
          ok = await navigate(tabId, t.ai_url);
        }
      }
      if (!ok) {
        const why = `page did not load in ${C.PACING.pageLoadTimeoutMs / 1000} s`;
        if (t.type === "company") await api(`/company_result/${rid}`, { company_url: t.company_url, data: { status: "error", note: why } });
        else { await log(rid, `Result page ${t.page + 1}: ${why}.`); await api(`/page_done/${rid}`, { page: t.page, ids: [], n_new: 0, has_more: false }); }
        continue;
      }
      // Stop (or the target being reached) is honoured right after each page load.
      if ((await api(`/state/${rid}`)).state !== "running") continue;   // next() then returns "done"
      if (t.type === "search" && t.page === 0 && aiMode && (t.ui_filters || []).length) {
        const f = await applyUiFilters(rid, tabId, t.ui_filters);
        if (f.stop) { await stopForWarning(rid, tabId, f.stop); break; }
        const tab = await chrome.tabs.get(tabId).catch(() => null);
        if (tab && tab.url) homeUrl = tab.url;          // the filtered page is where the window returns at the end
      }
      const res = t.type === "search" ? await doSearchPage(rid, t, tabId) : await doCompany(rid, t, tabId);
      if (res.stop) { await stopForWarning(rid, tabId, res.stop); break; }
    }
  } catch (e) {
    await log(rid, "Extension error: " + e.message);
    await api(`/stop/${rid}`, {}).catch(() => {});
  } finally {
    clearInterval(keepAlive);
    running = null;
    const { workerTabs } = await chrome.storage.session.get("workerTabs");
    for (const t of workerTabs || []) await chrome.tabs.remove(t).catch(() => {});   // no reader window left open
    fallbackTab = null;                                                              // (it was one of them)
    await chrome.storage.session.remove(["activeRun", "tabId", "workerTabs"]);
  }
}

chrome.runtime.onMessage.addListener((msg, _sender, reply) => {
  if (msg && msg.type === "ping") reply({ ok: true, version: chrome.runtime.getManifest().version, busy: running });
  else if (msg && msg.type === "start" && /^[a-z0-9]{1,32}$/i.test(msg.runId || "")) {
    if (running) { reply({ ok: false, error: "another run is in progress" }); return false; }
    const origin = dashboardOrigin(_sender.origin || _sender.url || "");
    if (!origin) { reply({ ok: false, error: "this page is not a JobHarvest dashboard" }); return false; }
    SERVER = origin;
    chrome.storage.session.set({ server: origin });
    chrome.storage.local.set({ dashboard: origin });
    // Answer at once (the dashboard must not wait on the window); problems after this go to the run log.
    reply({ ok: true });
    openLinkedInWindow(_sender.tab && _sender.tab.windowId).then(tabId => runLoop(msg.runId, tabId), async e => {
      await log(msg.runId, "Could not open the LinkedIn window: " + e.message);
      await api(`/stop/${msg.runId}`, {}).catch(() => {});
    });
  }
  return false;
});

// If the browser stopped this background worker in the middle of a run, NEVER restart that run by itself (that
// looked like a new search starting without pressing Start). End it cleanly instead: the jobs collected so far are
// kept, the leftover reader windows are closed, and a new run only starts from the dashboard's Start button.
chrome.storage.session.get(["activeRun", "tabId", "workerTabs", "server"]).then(async ({ activeRun, workerTabs, server }) => {
  if (server) SERVER = server;
  for (const t of workerTabs || []) await chrome.tabs.remove(t).catch(() => {});
  if (activeRun) {
    await log(activeRun, "The browser stopped the extension in the middle of this run, so the run ended here. Jobs collected so far are kept. Press Start for a new run.");
    await api(`/stop/${activeRun}`, {}).catch(() => {});
  }
  await chrome.storage.session.remove(["activeRun", "tabId", "workerTabs"]);
});
