// Page readers, injected by the background worker into the LinkedIn tab it opened.
// Every function here is INSTANT (no waiting inside the page): the background worker does all the waiting and
// pacing, so Chrome's throttling of hidden/occluded windows cannot stall a run.
// Actions on the page: scrolling the results list, clicking a job card, the description's "more", and "Next".
//
// Works on both LinkedIn job-search layouts:
//  - classic  /jobs/search/          (class names such as .job-details-jobs-unified-top-card__job-title)
//  - new (2026 "AI search")  /jobs/search-results/   random class names; verified against a real page on
//    2026-11-11: cards are div[role=button][componentkey="job-card-component-ref-<jobId>"], the detail panel's
//    title is a link to /jobs/view/<jobId>/, sections are headed "About the job" / "About the company", and the
//    company About page uses plain <p> labels ("Industry", "Company size") followed by the value.
(() => {
  const C = self.LJT_CONFIG;
  const clean = s => (s || "").replace(/\s+/g, " ").trim();
  const q = (sels, root = document) => { for (const s of sels) { try { const e = root.querySelector(s); if (e) return e; } catch {} } return null; };
  const qa = (sels, root = document) => { for (const s of sels) { try { const l = root.querySelectorAll(s); if (l.length) return [...l]; } catch {} } return []; };
  const SIZE_RE = /(\d[\d,]*\s*-\s*\d[\d,]*|\d[\d,]*\+)\s+employees/i;
  const bodyText = () => (document.body && document.body.innerText || "");

  // LinkedIn warning, captcha, sign-in page or not signed in -> reason string; otherwise null.
  self.__ljtCheck = function () {
    const url = location.href;
    for (const p of C.STOP_URL_PARTS) if (url.includes(p)) return `LinkedIn sent the tab to ${p.replace(/\//g, "")} page`;
    const text = bodyText().slice(0, 20000);
    for (const re of C.STOP_TEXT) if (re.test(text)) return `page says "${(text.match(re) || [""])[0]}"`;
    if (document.querySelector(".authwall-join-form, .nav__button-secondary, a[data-tracking-control-name*='guest_homepage']"))
      return "not signed in to LinkedIn in this browser (sign in, then start again)";
    return null;
  };

  self.__ljtIsAiSearch = () => location.pathname.includes("/jobs/search-results");

  // ---------- finding jobs on the page ----------
  const ID_IN_HREF = [/\/jobs\/view\/(?:[^/?#]*?-)?(\d{6,20})/, /[?&]currentJobId=(\d{6,20})/];
  const URN_RE = /urn:li:(?:fsd_|fs_normalized_)?jobPosting:(\d{6,20})/;
  const KEY_RE = /job-card-component-ref-(\d{6,20})/;

  function idOf(el) {
    const direct = el.getAttribute && (el.getAttribute("data-occludable-job-id") || el.getAttribute("data-job-id"));
    if (direct && /^\d{6,20}$/.test(direct)) return direct;
    const key = el.getAttribute && el.getAttribute("componentkey");
    if (key) { const m = key.match(KEY_RE); if (m) return m[1]; }
    if (el.tagName === "A" && el.href) for (const re of ID_IN_HREF) { const m = el.href.match(re); if (m) return m[1]; }
    if (el.attributes) for (const a of el.attributes) { const m = a.value && a.value.match(URN_RE); if (m) return m[1]; }
    return null;
  }

  // Job ID -> clickable card element, in page order.
  function findJobs() {
    const found = new Map();
    const add = (id, el) => { if (id && !found.has(id)) found.set(id, el); };
    for (const el of qa(C.SEL.searchCards)) {             // new layout first (componentkey cards), then classic
      const inner = el.querySelector && el.querySelector("[data-job-id]");
      add(idOf(el) || (inner && inner.getAttribute("data-job-id")), el);
    }
    if (!found.size) {                                      // last resort: any job link / id outside the detail panel
      const pane = q(C.SEL.detailPane);
      for (const el of document.querySelectorAll("a[href*='/jobs/view/'], [data-job-id], [data-occludable-job-id], [data-entity-urn*='obPosting']")) {
        if (pane && pane.contains(el)) continue;
        add(idOf(el), el.closest("li") || el);
      }
    }
    return found;
  }

  self.__ljtDebugSnapshot = function (kind) {
    const counts = {};
    for (const [k, sels] of Object.entries(C.SEL)) if (Array.isArray(sels) && typeof sels[0] === "string")
      counts[k] = sels.map(s => { try { return document.querySelectorAll(s).length; } catch { return "bad selector"; } });
    // whole page: LinkedIn places dropdowns/popovers outside <main>
    const clone = document.body.cloneNode(true);
    clone.querySelectorAll("script, style, svg, img, video, iframe, noscript").forEach(e => e.remove());
    return {
      kind, url: location.href, title: document.title, counts,
      jobLinks: document.querySelectorAll("a[href*='/jobs/view/'], a[href*='currentJobId=']").length,
      jobsFound: findJobs().size, html: clone.outerHTML.slice(0, 3000000),
    };
  };

  // ---------- results list ----------
  self.__ljtCardsReady = () => findJobs().size > 0 || !!q(C.SEL.searchNoResults) ||
    /no matching jobs found|no results found/i.test(bodyText().slice(0, 5000));

  // Scrolls the element that actually scrolls the results (found from the first card), so every card draws.
  self.__ljtScrollList = function (i, steps) {
    const first = findJobs().values().next().value;
    let box = first && first.parentElement;
    while (box && box !== document.body) {
      const st = getComputedStyle(box);
      if (box.scrollHeight > box.clientHeight + 50 && /(auto|scroll)/.test(st.overflowY)) break;
      box = box.parentElement;
    }
    if (box && box !== document.body) box.scrollTop = box.scrollHeight * (i + 1) / steps;
    else window.scrollTo(0, document.body.scrollHeight * (i + 1) / steps);
    return true;
  };

  function nextButton() {
    const b = q(C.SEL.searchNextButton) ||
      [...document.querySelectorAll("button")].find(x => /^next$/i.test(clean(x.textContent)) || /^(view )?next( page)?$/i.test(x.getAttribute("aria-label") || ""));
    return b && !(b.disabled || b.getAttribute("aria-disabled") === "true") ? b : null;
  }

  // Card text on the new layout is: title, company, location, "Posted …" (duplicates removed).
  function cardLocation(card) {
    const lines = [...new Set((card.innerText || "").split("\n").map(clean).filter(Boolean))]
      .filter(l => !/^(posted|viewed|promoted|easy apply|actively reviewing|be an early applicant|\d+ (minute|hour|day|week|month)s? ago|·)/i.test(l));
    const loc = lines.find((l, i) => i >= 2 && /(remote|hybrid|on-site|,|india|united|area)/i.test(l));
    return loc || "";
  }

  // One card's location line, after scrolling it into view (LinkedIn only draws card text near the screen).
  self.__ljtCardInfo = function (id) {
    const card = findJobs().get(String(id));
    if (!card) return null;
    card.scrollIntoView({ block: "center" });
    return { id: String(id), location: cardLocation(card) };
  };

  self.__ljtListCards = function () {
    const jobs = findJobs();
    const ids = [...jobs.keys()];
    const cards = ids.map(id => ({ id, location: cardLocation(jobs.get(id)) }));
    // LinkedIn's own total ("22 results"): when every result is already on this page, there is no page 2.
    const m = /^\s*([\d,]+)\+? results?\s*$/im.exec(document.body.innerText || "");
    const total = m ? parseInt(m[1].replace(/,/g, ""), 10) : 0;
    const allHere = total > 0 && ids.length >= total && !/[?&]start=[1-9]/.test(location.search);
    return { ids, cards, total, has_more: !allHere && !!nextButton(), no_results: !ids.length };
  };

  // Paging on the new layout: click "Next" (the address does not carry the page number).
  self.__ljtFirstJobId = () => findJobs().keys().next().value || null;
  self.__ljtClickNext = function () {
    const b = nextButton();
    if (!b) return false;
    b.scrollIntoView({ block: "center" }); b.click();
    return true;
  };

  // ---------- one job: click its card, wait (in the worker) for the panel, then read ----------
  // A job's own page (/jobs/view/<id>/, used when the search page does not draw the job): the title is the <h1>.
  const viewPageId = () => (location.pathname.match(/\/jobs\/view\/(\d+)/) || [])[1] || null;
  const titleLink = id => [...document.querySelectorAll(`a[href*='/jobs/view/${id}']`)].find(a => clean(a.textContent)) ||
    (viewPageId() === id ? [...document.querySelectorAll("main h1, h1")].find(h => clean(h.textContent)) || null : null);
  const shownJobId = () => {
    const u = new URL(location.href).searchParams.get("currentJobId");
    if (u) return u;
    if (viewPageId()) return viewPageId();
    const a = q(C.SEL.paneJobLink);
    const m = a && a.href.match(/\/jobs\/view\/(\d+)/);
    return m ? m[1] : null;
  };

  // The detail panel = the smallest block around this job's title link that also holds "About the job".
  function paneRoot(id) {
    const classic = q(C.SEL.detailPane);
    if (classic) return classic;
    let el = titleLink(id);
    while (el && el !== document.body) {
      if ([...el.querySelectorAll("h1, h2, h3")].some(h => /^\s*about the job\s*$/i.test(h.textContent || ""))) return el;
      el = el.parentElement;
    }
    return null;
  }

  self.__ljtClickCard = function (id) {
    const card = findJobs().get(id);
    if (!card) return { error: "card no longer in the list" };
    card.scrollIntoView({ block: "center" });
    if (shownJobId() !== id) {
      const target = q(C.SEL.cardClickTarget, card) || (card.matches("a, [role=button]") ? card : card.querySelector("a, [role=button]")) || card;
      target.click();
    }
    return { ok: true };
  };

  // Ready when the address says this job is shown AND its own content has drawn (title link / classic title).
  self.__ljtPaneReady = id => shownJobId() === id && (!!(q(C.SEL.jobReady) && q(C.SEL.paneTitle)) || (!!titleLink(id) && !!paneRoot(id)));

  self.__ljtExpandDescription = function () {
    const root = paneRoot(shownJobId()) || document;
    const more = q(C.SEL.descriptionMoreButton, root) ||
      [...root.querySelectorAll("button")].find(b => /^(…|\.\.\.)?\s*(see )?more$/i.test(clean(b.textContent)));
    if (more) { more.click(); return true; }
    return false;
  };

  // LinkedIn draws the lower parts of the job panel (the people section, "About the company") only while they are
  // on screen. One step per call: scroll the panel DOWN BY ABOUT HALF A SCREEN (never jump, or a section in between
  // is skipped and never drawn). True once the people section and "About the company" are drawn, or when the panel's
  // real end is reached (a job without them). Never "done" before scrolling.
  // Has the bottom "About the company" box been drawn (it lists "... employees")? LinkedIn only draws it in a window
  // that is actually on screen, so false here after scrolling means the window was hidden behind another one.
  self.__ljtCompanyDrawn = function (id) {
    const root = paneRoot(id); if (!root) return false;
    const h = [...root.querySelectorAll("h1, h2, h3")].find(x => /^about the company$/i.test(clean(x.textContent)));
    let box = h && h.parentElement;
    for (let i = 0; i < 4 && box && !/employees/i.test(box.innerText || ""); i++) box = box.parentElement;
    return !!box && /employees/i.test(box.innerText || "");
  };
  self.__ljtResetSections = function () { self.__ljtLS = null; return true; };

  self.__ljtLoadSections = function (id) {
    const root = paneRoot(id);
    if (!root) return false;
    const st = (self.__ljtLS = self.__ljtLS && self.__ljtLS.id === id ? self.__ljtLS : { id, steps: 0, lastTop: -1, still: 0 });
    const H = [...root.querySelectorAll("h1, h2, h3, h4, strong")].find(h =>
      /^(meet the hiring team|hiring team|job poster|meet the job poster|people you can reach out to)$/i.test(clean(h.textContent)));
    let hiringDrawn = false;
    if (H) {
      const next = [...root.querySelectorAll("h1, h2, h3")].find(h => h !== H && !H.contains(h) &&
        (H.compareDocumentPosition(h) & Node.DOCUMENT_POSITION_FOLLOWING));
      hiringDrawn = [...root.querySelectorAll("a[href*='/in/']")].some(a => (H.compareDocumentPosition(a) & Node.DOCUMENT_POSITION_FOLLOWING) &&
        (!next || (a.compareDocumentPosition(next) & Node.DOCUMENT_POSITION_FOLLOWING)));
    }
    const C_ = [...root.querySelectorAll("h1, h2, h3")].find(h => /^about the company$/i.test(clean(h.textContent)));
    let companyDrawn = false;
    if (C_) {
      let box = C_.parentElement;
      for (let i = 0; i < 4 && box && !/employees/i.test(box.innerText || ""); i++) box = box.parentElement;
      companyDrawn = !!box && /employees/i.test(box.innerText || "");
    }
    // Scrolling goes top -> bottom, so once "About the company" (the last part) is drawn every part above it has been
    // on screen: done when the people section is drawn too, or there is none.
    if (companyDrawn && (hiringDrawn || !H)) return true;
    // The box that actually scrolls the panel: an inner box of the panel or one of its outer boxes (the tallest).
    const scrollable = e => e && e.scrollHeight > e.clientHeight + 50 && /(auto|scroll)/.test(getComputedStyle(e).overflowY);
    const cands = [...root.querySelectorAll("div, section, main")].filter(scrollable);
    for (let e = root; e && e !== document.body; e = e.parentElement) if (scrollable(e)) cands.push(e);
    cands.sort((x, y) => y.scrollHeight - x.scrollHeight);
    // Prefer the box that scrolls the job panel itself (nearest scrolling box around "About the job"). The tallest
    // box is often the job LIST, and scrolling that never draws the panel's people / company sections.
    const aboutJob = [...root.querySelectorAll("h1, h2, h3")].find(h => /^\s*about the job\s*$/i.test(h.textContent || ""));
    let own = null;
    for (let e = aboutJob && aboutJob.parentElement; e && e !== document.body; e = e.parentElement) if (scrollable(e)) { own = e; break; }
    const scroller = own || document.scrollingElement;   // no own box: the page itself scrolls the panel
    const atEnd = scroller.scrollTop + scroller.clientHeight >= scroller.scrollHeight - 20;
    st.still = scroller.scrollTop === st.lastTop ? st.still + 1 : 0;
    st.lastTop = scroller.scrollTop;
    // End of a job without those sections: at the real end after scrolling, or nothing moves any more.
    // Sections at the bottom draw a moment AFTER they come on screen, so stay at the end for a few checks (~1 s)
    // before giving up; if they draw, the page grows and scrolling continues.
    st.endHits = st.steps >= 1 && (atEnd || st.still >= 2) ? (st.endHits || 0) + 1 : 0;
    if (st.endHits >= 4) return true;
    if (st.endHits) {
      // The panel's box is at its end, but in a small window its bottom can still be below the window's edge, where
      // LinkedIn never draws. Bring the bottom part itself into the window (this scrolls every box around it too).
      const tail = (C_ && !companyDrawn && C_) || (H && !hiringDrawn && H) || scroller.lastElementChild;
      if (tail && tail.scrollIntoView) tail.scrollIntoView({ block: "center" });
      return false;
    }
    st.steps++;
    if (H && !hiringDrawn) H.scrollIntoView({ block: "center" });      // keep the people section on screen while it fills
    else scroller.scrollTop += Math.max(250, Math.round(scroller.clientHeight * 0.5));
    return false;
  };

  const TAGS = ["Remote", "Hybrid", "On-site", "Full-time", "Part-time", "Contract", "Temporary", "Internship", "Volunteer", "Easy Apply"];

  self.__ljtReadPane = function (id) {
    const root = paneRoot(id);
    self.__ljtPaneRoot = root;          // extract.js reads inside this block
    const data = self.__ljtExtract();
    self.__ljtPaneRoot = null;
    data.job_id = id;
    data.job_url = `https://www.linkedin.com/jobs/view/${id}/`;
    const tl = titleLink(id);
    if (!data.job_title && tl) data.job_title = clean(tl.textContent);
    // Card text (new layout): title, company, location, posted - used only for location when the panel has none.
    const card = findJobs().get(id);
    const lines = card ? [...new Set((card.innerText || "").split("\n").map(clean).filter(Boolean))] : [];
    if (!data.location && lines.length) {
      const ci = lines.findIndex(l => data.company_name && l === data.company_name);
      const cand = ci >= 0 ? lines[ci + 1] : null;
      if (cand && !/^(posted|viewed|promoted|easy apply|\d+ (day|week|month|hour))/i.test(cand)) data.location = cand;
    }
    // Workplace / job type / Easy Apply as shown on the job (for checking the filters; never guessed).
    const top = tl ? (() => { let e = tl; for (let i = 0; i < 5 && e.parentElement; i++) e = e.parentElement; return e; })() : root;
    const topText = top ? (top.innerText || "") : "";
    // No card on the page (job opened by its own address): the panel's top line starts with the location,
    // e.g. "Bengaluru, Karnataka, India · 2 months ago · Over 100 people clicked apply".
    if (!data.location) {
      const m = topText.split("\n").map(clean)
        .find(l => / · /.test(l) && /\b(ago|applicants?|clicked|people|reposted|posted)\b/i.test(l));
      const cand = m && clean(m.split(" · ")[0]);
      if (cand && cand.length < 80 && !/\b(ago|applicants?|clicked)\b/i.test(cand)) data.location = cand;
    }
    data.pane_tags = TAGS.filter(t => new RegExp(`(^|\\n|\\s)${t}(\\s|\\n|$)`).test(topText));
    // "5 days ago" from the panel's top line, else "Posted 1 month ago" from the card (the server keeps just that part)
    data.posted = (topText.slice(0, 400) + "\n" + lines.join("\n")).slice(0, 800);
    if (data.job_title && data.company_name && data.job_description) {
      data.data_notes = (data.data_notes || "").split("; ").filter(n => !/^(job title not found|description not found)/.test(n)).join("; ");
    }
    return data;
  };

  // ---------- LinkedIn's own filter buttons (Date posted, Experience level, …, Easy Apply) ----------
  // Found by their visible text, never by class names. Only buttons ABOVE the results list are considered.
  const visible = el => !!el && el.getClientRects().length > 0 && getComputedStyle(el).visibility !== "hidden";
  const norm = s => clean(s).toLowerCase().replace(/[▾▼⌄⏷]/g, "").replace(/\s*\(\d[\d,+]*\)\s*$/, "").trim();
  const CLICKABLE = "button, [role=button], a[role=button], [role=switch], [role=checkbox]";

  function listTop() {
    const first = findJobs().values().next().value;
    return first ? first.getBoundingClientRect().top + window.scrollY : Infinity;
  }

  // Real LinkedIn markup (2026-11-11): each filter is div[aria-label="Filter by <Name>"] holding a checkbox
  // (checked = filter active) and a <label>. Dropdown filters sit inside div[role=button][aria-expanded];
  // toggles (Easy Apply, Under 10 applicants) are just the checkbox + label. An active dropdown filter can show
  // its VALUE instead of its name (e.g. "Filter by Remote" for Workplace type), so `alts` are tried too.
  function filterBox(name) {
    const want = `filter by ${name}`.toLowerCase();
    return [...document.querySelectorAll("[aria-label]")].find(e => e.tagName !== "INPUT" &&
      (e.getAttribute("aria-label") || "").trim().toLowerCase() === want) || null;
  }

  function findPill(label, alts = []) {
    for (const name of [label, ...alts]) {
      const box = filterBox(name);
      if (!box) continue;
      const input = box.querySelector("input[type=checkbox]");
      const lab = input && input.id && box.querySelector(`label[for="${CSS.escape(input.id)}"]`);
      return box.closest("[role=button]") || lab || box;
    }
    const L = label.toLowerCase(), top = listTop();
    const cands = [...document.querySelectorAll(CLICKABLE)].filter(visible)
      .filter(b => !b.closest("[componentkey^='job-card-component-ref-']") && b.getBoundingClientRect().top + window.scrollY < top);
    return cands.find(b => norm(b.textContent) === L) ||
      cands.find(b => norm(b.getAttribute("aria-label") || "").startsWith(L)) ||
      cands.find(b => norm(b.textContent).startsWith(L)) || null;
  }

  function filterIsOn(label, alts = []) {
    for (const name of [label, ...alts]) {
      const box = filterBox(name);
      const input = box && box.querySelector("input[type=checkbox]");
      if (input) return input.checked;
    }
    return null;
  }

  // Filters left on from an earlier LinkedIn session (e.g. "Remote"), by name.
  self.__ljtActiveFilters = () => [...document.querySelectorAll("[aria-label^='Filter by ' i]")]
    .filter(e => e.tagName !== "INPUT" && (e.querySelector("input[type=checkbox]") || {}).checked)
    .map(e => e.getAttribute("aria-label").replace(/^filter by /i, "")).filter((v, i, a) => a.indexOf(v) === i && !/^jobs$/i.test(v));

  self.__ljtClickReset = function () {
    const b = [...document.querySelectorAll("button, [role=button], a")].filter(visible).find(x => /^reset$/i.test(clean(x.textContent)));
    if (!b) return false;
    b.click();
    return true;
  };

  const OPTION_SEL = "input[type=checkbox], input[type=radio], [role=checkbox], [role=radio], [role=option], [role=menuitemcheckbox], [role=menuitemradio]";

  // The dropdown that belongs to a filter button: its aria-controls target, else the visible popup holding options.
  function openDropdown(label, alts = []) {
    const pill = findPill(label, alts);
    const ctl = pill && pill.getAttribute("aria-controls");
    const byId = ctl && document.getElementById(ctl);
    if (byId && visible(byId) && byId.querySelector(OPTION_SEL)) return byId;
    // New LinkedIn (seen 2026-11-12): the open list is a floating layer <div popover data-floating-ui-focusable> under <body>.
    const floating = [...document.querySelectorAll("[popover], [data-floating-ui-focusable]")]
      .filter(c => visible(c) && c.querySelector(OPTION_SEL) && !c.querySelector("[componentkey^='job-card-component-ref-']"));
    if (floating.length) return floating[floating.length - 1];
    const pops = [...document.querySelectorAll("[role=dialog], [role=menu], [role=listbox], [aria-modal=true], fieldset, form, ul, div[data-basic-filter-parameter-name]")]
      .filter(visible).filter(c => c.querySelector(OPTION_SEL) && !c.closest("[componentkey^='job-card-component-ref-']") &&
        !c.querySelector("[aria-label^='Filter by ' i]") && !c.closest("[aria-label^='Filter by ' i]") && !c.querySelector("[componentkey^='job-card-component-ref-']"));
    if (!pops.length) return null;
    // the smallest popup that holds options = the dropdown itself (not the whole page)
    pops.sort((a, b) => a.querySelectorAll("*").length - b.querySelectorAll("*").length);
    return pops[0];
  }

  // The clickable thing for one option label, and whether it is already selected.
  // Option names differ between LinkedIn versions: "Entry level" / "Entry-level", "Mid-Senior level" / "Senior".
  const optKey = s => norm(s).replace(/[-‐‑–—]/g, " ").replace(/\s+level$/, "").replace(/\s+/g, " ").trim();
  const OPT_ALIASES = { "mid senior": ["senior"], "senior": ["mid senior"] };
  function optionFor(box, label) {
    // New LinkedIn: <input aria-label="Past 24 hours"> + an EMPTY <label>; the text sits in a separate <p>. Match the input itself.
    const keys = [optKey(label), ...(OPT_ALIASES[optKey(label)] || [])];
    for (const k of keys) {
      const inp = [...box.querySelectorAll("input[type=checkbox], input[type=radio]")].find(i => optKey(i.getAttribute("aria-label") || "") === k);
      if (inp) return { el: inp, checked: inp.checked };
    }
    const L = label.toLowerCase();
    const els = [...box.querySelectorAll("label, " + OPTION_SEL + ", li, button, span, div")].filter(visible);
    const hit = els.find(e => norm(e.textContent) === L) || els.find(e => norm(e.textContent).startsWith(L + " ")) ||
      els.find(e => norm(e.getAttribute("aria-label") || "") === L);
    if (!hit) return null;
    const input = hit.matches("input") ? hit : (hit.querySelector("input[type=checkbox], input[type=radio]") ||
      (hit.tagName === "LABEL" && hit.htmlFor && document.getElementById(hit.htmlFor)) ||
      (hit.closest("li, label, div") && hit.closest("li, label, div").querySelector("input[type=checkbox], input[type=radio]")));
    const roleEl = hit.closest("[role=checkbox], [role=radio], [role=option], [role=menuitemcheckbox], [role=menuitemradio]") || hit;
    const checked = input ? input.checked : ["true"].includes(roleEl.getAttribute("aria-checked") || roleEl.getAttribute("aria-selected"));
    return { el: hit.tagName === "LABEL" || !input ? hit : input, checked };
  }

  self.__ljtFilterButtons = () => {
    const top = listTop();
    return [...document.querySelectorAll(CLICKABLE)].filter(visible)
      .filter(b => b.getBoundingClientRect().top + window.scrollY < top).map(b => clean(b.textContent)).filter(t => t && t.length < 40).slice(0, 40);
  };

  // A real-looking mouse click (pointer + mouse events at the element's centre), as a person's click produces.
  function mouseClick(el) {
    const r = el.getBoundingClientRect();
    const o = { bubbles: true, cancelable: true, composed: true, view: window, button: 0, buttons: 1,
                clientX: r.left + r.width / 2, clientY: r.top + r.height / 2 };
    const p = { ...o, pointerId: 1, pointerType: "mouse", isPrimary: true };
    el.dispatchEvent(new PointerEvent("pointerover", p)); el.dispatchEvent(new MouseEvent("mouseover", o));
    el.dispatchEvent(new PointerEvent("pointerdown", p)); el.dispatchEvent(new MouseEvent("mousedown", o));
    if (el.focus) el.focus();
    el.dispatchEvent(new PointerEvent("pointerup", { ...p, buttons: 0 })); el.dispatchEvent(new MouseEvent("mouseup", { ...o, buttons: 0 }));
    el.dispatchEvent(new MouseEvent("click", { ...o, buttons: 0 }));
  }

  function keyPress(el, key) {
    if (el.focus) el.focus();
    const code = key === " " ? "Space" : key;
    const o = { key, code, keyCode: key === " " ? 32 : 13, which: key === " " ? 32 : 13, bubbles: true, cancelable: true, composed: true };
    el.dispatchEvent(new KeyboardEvent("keydown", o)); el.dispatchEvent(new KeyboardEvent("keypress", o)); el.dispatchEvent(new KeyboardEvent("keyup", o));
  }

  // method: "label" | "mouse" | "enter" | "space" | "click". The worker tries them in turn until the list opens.
  self.__ljtClickFilter = function (label, alts = [], method = "click") {
    const pill = findPill(label, alts);
    if (!pill) return { error: `no "${label}" button on the page` };
    pill.scrollIntoView({ block: "center" });
    const box = (() => { for (const n of [label, ...alts]) { const b = filterBox(n); if (b) return b; } return null; })();
    const input = box && box.querySelector("input[type=checkbox]");
    const lab = input && input.id ? document.querySelector(`label[for="${CSS.escape(input.id)}"]`) : (box && box.querySelector("label"));
    const button = (box && box.closest("[role=button]")) || pill;
    if (method === "label" && lab) mouseClick(lab);
    else if (method === "mouse") mouseClick(button);
    else if (method === "enter") keyPress(button, "Enter");
    else if (method === "space") keyPress(button, " ");
    else button.click();
    return { ok: true, method };
  };

  // After "Show results" LinkedIn re-renders the page; the filter bar is briefly missing.
  self.__ljtPillReady = (label, alts = []) => !!findPill(label, alts) && findJobs().size > 0;

  self.__ljtToggleIsOn = label => {
    const on = filterIsOn(label);
    if (on !== null) return on;
    const p = findPill(label);
    const v = p && (p.getAttribute("aria-pressed") || p.getAttribute("aria-checked"));
    return v ? v === "true" : null;
  };

  self.__ljtDropdownReady = (label, alts = []) => {
    const box = (() => { for (const n of [label, ...alts]) { const b = filterBox(n); if (b) return b; } return null; })();
    const button = box && box.closest("[role=button]");
    if (button && button.getAttribute("aria-expanded") === "true") return true;
    return !!openDropdown(label, alts);
  };

  self.__ljtSelectOptions = function (label, options) {
    const box = openDropdown(label, options);
    if (!box) return { error: "the filter list did not open" };
    const picked = [], missing = [];
    for (const o of options) {
      const opt = optionFor(box, o);
      if (!opt) { missing.push(o); continue; }
      if (!opt.checked) opt.el.click();
      if (opt.el.matches("input") && !opt.el.checked) mouseClick(opt.el);   // React ignored the plain click
      if (opt.el.matches("input") && !opt.el.checked) { missing.push(o); continue; }
      picked.push(o);
    }
    return { picked, missing, offered: [...box.querySelectorAll("label, " + OPTION_SEL)].map(e => clean(e.textContent || e.getAttribute("aria-label") || "")).filter(Boolean).slice(0, 20) };
  };

  // Press the dropdown's own confirm button ("Show 123 results", "Apply", "Done"). Returns false if there is none
  // (some dropdowns apply immediately).
  self.__ljtConfirmFilter = function (label, alts = []) {
    const isConfirm = b => /^(show\b.*results?|apply|done|show results|see results)/i.test(clean(b.textContent) || b.getAttribute("aria-label") || "");
    const inBar = b => !!b.closest("[aria-label^='Filter by ' i]") || !!b.closest("nav");
    // New LinkedIn's "Show results" is an <a href> link, not a button.
    const BTN = "button, [role=button], a";
    // The confirm button usually sits OUTSIDE the options list, in the popup around it: walk outwards.
    let box = openDropdown(label, alts);
    for (let i = 0; box && i < 6; i++, box = box.parentElement) {
      const btn = [...box.querySelectorAll(BTN)].filter(visible).find(b => isConfirm(b) && !inBar(b) && b.getAttribute("aria-disabled") !== "true");
      if (btn) { btn.click(); return true; }
    }
    const any = [...document.querySelectorAll(BTN)].filter(visible).find(b => isConfirm(b) && !inBar(b));
    if (any) { any.click(); return true; }
    return false;
  };

  self.__ljtCloseFilter = function (label, alts = []) {
    if (!openDropdown(label, alts)) return true;
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", code: "Escape", keyCode: 27, bubbles: true }));
    document.body.click();
    return true;
  };

  self.__ljtResultsSignature = () => {
    const ids = [...findJobs().keys()].slice(0, 5).join(",");
    const count = (bodyText().match(/\b(\d[\d,+]*)\s+results?\b/i) || [""])[0];
    return ids + "|" + count;
  };

  // ---------- company About page: ONLY the labelled "Industry" and "Company size" values ----------
  // Classic: <dt>Label</dt><dd>value</dd>.  New: <p>Label</p> followed by the value as the next text.
  function labelled(label) {
    const dt = [...document.querySelectorAll("dt")].find(e => clean(e.textContent).toLowerCase() === label);
    if (dt) {
      let dd = dt.nextElementSibling;
      while (dd && dd.tagName !== "DD") dd = dd.tagName === "DT" ? null : dd.nextElementSibling;
      if (dd) return [clean(dd.textContent)];
    }
    const walker = document.createTreeWalker(document.querySelector("main") || document.body, NodeFilter.SHOW_TEXT);
    for (let n = walker.nextNode(); n; n = walker.nextNode()) {
      if (clean(n.nodeValue).toLowerCase() !== label) continue;
      const out = [];
      for (let m = walker.nextNode(); m && out.length < 2; m = walker.nextNode()) { const t = clean(m.nodeValue); if (t) out.push(t); }
      return out;   // the value (and the line after it, e.g. "262 associated members")
    }
    return null;
  }

  self.__ljtCompanyReady = () => !!labelled("industry") || !!labelled("company size") || C.SEL.pageNotFound.some(r => r.test(bodyText()));

  self.__ljtReadCompany = function () {
    if (C.SEL.pageNotFound.some(r => r.test(bodyText()))) return { status: "not found", note: "company page does not exist" };
    const ind = labelled("industry"), sz = labelled("company size");
    const industry = ind && ind[0] && !/^(company size|headquarters|website|founded|type)$/i.test(ind[0]) ? ind[0] : "";
    let size = "";
    if (sz) for (const t of sz) { const m = t.match(SIZE_RE); if (m) { size = m[1].replace(/\s/g, ""); break; } }
    if (!industry && !size) return { status: "not found", note: "no labelled Industry / Company size on the About page" };
    return { status: "ok", industry, size, note: !industry ? "Industry label not shown" : !size ? "Company size label not shown" : "" };
  };
})();
