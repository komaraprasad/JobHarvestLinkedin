// Injected into the active LinkedIn tab ONLY when you click "Save" in the popup.
// Reads what is already on screen. Never clicks, scrolls, navigates or fetches anything.
// Rule (same as the Python tool): never guess. Blank + a Data Note when a value is not clearly shown.
window.__ljtExtract = function () {
  const SIZE_RE = /(\d[\d,]*\s*-\s*\d[\d,]*|\d[\d,]*\+)\s+employees/i;
  const PROFILE_RE = /^https?:\/\/(?:[a-z]{2,3}\.)?linkedin\.com\/(?:in|pub)\/[A-Za-z0-9\-_%.]+\/?/i;
  const HIRER = [".hirer-card__hirer-information", ".hirer-card__container", ".job-details-people-who-can-help__section",
    ".jobs-poster", ".message-the-recruiter", ".base-main-card--hirer"];
  const clean = s => (s || "").replace(/\s+/g, " ").trim();
  const first = sels => { for (const s of sels) { const e = document.querySelector(s); if (e && clean(e.textContent)) return e; } return null; };
  const strip = u => (u || "").split("?")[0];
  const notes = [];

  const url = location.href;
  const idMatch = url.match(/\/jobs\/view\/(?:[^/?]*-)?(\d+)/) || url.match(/[?&]currentJobId=(\d+)/);
  const jobId = idMatch ? idMatch[1] : "";

  // Fallbacks for LinkedIn layouts without the known class names: work inside the job detail panel and use its
  // structure (main heading, company link, the "About the job" section) instead of class names.
  const pane = self.__ljtPaneRoot || first([".jobs-search__job-details", ".jobs-details", ".scaffold-layout__detail"]) || document.body;
  const section = re => {         // the block under a heading such as "About the job" (climb until it holds text)
    const h = [...pane.querySelectorAll("h1, h2, h3, strong")].find(e => re.test(clean(e.textContent)));
    if (!h) return null;
    let box = h.parentElement;
    while (box && box !== pane && clean(box.innerText || box.textContent).length < clean(h.textContent).length + 60) box = box.parentElement;
    return box;
  };
  const aboutJob = section(/^about the job$/i);
  const aboutCompany = section(/^about the company$/i);
  // Classic layout: a "Meet the hiring team" section. New layout (seen 2026-11-12): one "People you can reach out to"
  // section ABOVE "About the job" that mixes the hiring team / job poster with LinkedIn's suggestions (school alumni,
  // connections). Inside it, only people labelled as hiring are taken.
  const HIRING_RE = /^(meet the hiring team|hiring team|job poster|meet the job poster)$/i;
  const PEOPLE_RE = /^people you can reach out to$/i;
  const HIRER_LABEL = /(hiring team|job poster|is hiring|#hiring|recruit|talent acquisition|hiring manager)/i;
  const SUGGESTION_LABEL = /(school alumni|alumni from|connections?\b|works? here|worked here|mutual)/i;
  const heads = [...pane.querySelectorAll("h1, h2, h3, h4, strong")];
  const hiringHead = heads.find(e => HIRING_RE.test(clean(e.textContent)));
  const peopleHead = heads.find(e => PEOPLE_RE.test(clean(e.textContent)));
  const linksAfter = head => {                 // profile links between a heading and the next section heading
    const big = [...pane.querySelectorAll("h1, h2, h3")];
    const next = big.find(h => h !== head && (head.compareDocumentPosition(h) & Node.DOCUMENT_POSITION_FOLLOWING) && !head.contains(h));
    return [...pane.querySelectorAll("a[href]")].filter(a => (head.compareDocumentPosition(a) & Node.DOCUMENT_POSITION_FOLLOWING) &&
      (!next || (a.compareDocumentPosition(next) & Node.DOCUMENT_POSITION_FOLLOWING)) && PROFILE_RE.test(a.href));
  };
  // The label that applies to a person: the person's own card text, else the nearest sub-heading above it.
  const labelOf = (a, head) => {
    let card = a;
    for (let i = 0; i < 6 && card.parentElement && card.parentElement !== pane; i++) {
      card = card.parentElement;
      if (card.querySelectorAll("a[href*='/in/']").length > 1 && i > 1) break;   // stop before the list of several people
      const t = clean(card.innerText || card.textContent);
      if (HIRER_LABEL.test(t)) return "hiring";
      if (SUGGESTION_LABEL.test(t)) return "suggestion";
    }
    const subs = [...pane.querySelectorAll("p, span, h3, h4, div")].filter(e => e.childElementCount <= 1 &&
      (head.compareDocumentPosition(e) & Node.DOCUMENT_POSITION_FOLLOWING) && (e.compareDocumentPosition(a) & Node.DOCUMENT_POSITION_FOLLOWING) &&
      (HIRER_LABEL.test(clean(e.textContent)) || SUGGESTION_LABEL.test(clean(e.textContent))) && clean(e.textContent).length < 80);
    const last = subs[subs.length - 1];
    return !last ? "" : HIRER_LABEL.test(clean(last.textContent)) ? "hiring" : "suggestion";
  };
  const hiringLinks = [];
  if (hiringHead) linksAfter(hiringHead).forEach(a => hiringLinks.push(strip(a.href)));
  if (peopleHead) linksAfter(peopleHead).forEach(a => { if (labelOf(a, peopleHead) === "hiring") hiringLinks.push(strip(a.href)); });
  // For diagnosis: what the people section offered (never exported).
  const peopleSeen = peopleHead ? linksAfter(peopleHead).map(a => `${labelOf(a, peopleHead) || "unlabelled"}:${strip(a.href)}`) : [];
  const titleEl = first([".job-details-jobs-unified-top-card__job-title h1", ".job-details-jobs-unified-top-card__job-title",
    ".jobs-unified-top-card__job-title", ".top-card-layout__title"]) ||
    (pane !== document.body ? [...pane.querySelectorAll("a[href*='/jobs/view/']")].find(a => clean(a.textContent)) : null) ||
    pane.querySelector("h1");
  const compEl = first([".job-details-jobs-unified-top-card__company-name a", ".job-details-jobs-unified-top-card__company-name",
    ".jobs-unified-top-card__company-name a", ".topcard__org-name-link", ".topcard__flavor"]) ||
    [...pane.querySelectorAll("a[href*='/company/']")].find(a => clean(a.textContent));
  const compA = compEl && (compEl.closest("a") || compEl.querySelector("a[href*='/company/']") || (compEl.tagName === "A" ? compEl : null));
  const locEl = first([".job-details-jobs-unified-top-card__primary-description-container .tvm__text",
    ".job-details-jobs-unified-top-card__bullet", ".topcard__flavor--bullet"]);
  const descEl = first(["#job-details", ".jobs-description__content", ".jobs-box__html-content", ".show-more-less-html__markup"]) || aboutJob;

  // Industry: only from a LABELLED field ("Industries" job criteria). Not inferred from layout.
  let industry = "", industrySource = "";
  document.querySelectorAll(".description__job-criteria-item").forEach(item => {
    const h = item.querySelector(".description__job-criteria-subheader"), v = item.querySelector(".description__job-criteria-text");
    if (h && v && clean(h.textContent).toLowerCase() === "industries" && clean(v.textContent)) {
      industry = clean(v.textContent); industrySource = "job posting";
    }
  });
  if (!industry) notes.push("industry not shown as a labelled field on this page");

  // Company size: only an explicit "<range> employees" inside the company box of THIS job.
  let size = "";
  const box = first([".jobs-company__box", "section.jobs-company", ".jobs-company"]) || aboutCompany;
  const m = box && clean(box.innerText || box.textContent).match(SIZE_RE);
  if (m) size = m[1].replace(/\s/g, ""); else notes.push("company size not shown on this page");

  // Industry from the panel's "About the company" box, which LinkedIn shows as
  // "<Industry> • <N> employees • <M> on LinkedIn". Taken only from the line right before "<N> employees".
  let boxIndustry = "";
  if (aboutCompany) {
    const lines = (aboutCompany.innerText || "").split("\n").map(clean).filter(l => l && !/^[•·|]$/.test(l));
    const i = lines.findIndex(l => SIZE_RE.test(l) && /^\S/.test(l) && !/[•·]/.test(l.replace(SIZE_RE, "")));
    const prev = i > 0 ? lines[i - 1] : "";
    if (prev && !/(followers?|^follow$|employees|on linkedin|^about the company$)/i.test(prev) && prev.length <= 80) boxIndustry = prev;
  }

  // Contacts: only hiring-team blocks or links written in the description.
  const links = [];
  HIRER.forEach(s => document.querySelectorAll(s + " a[href]").forEach(a => { if (PROFILE_RE.test(a.href)) links.push(strip(a.href)); }));
  links.push(...hiringLinks);
  if (descEl) {
    descEl.querySelectorAll("a[href]").forEach(a => { if (PROFILE_RE.test(a.href)) links.push(strip(a.href)); });
    (descEl.innerText || "").replace(/https?:\/\/(?:[a-z]{2,3}\.)?linkedin\.com\/(?:in|pub)\/[A-Za-z0-9\-_%.]+\/?/gi, u => { links.push(u); return u; });
  }
  // Fallback (v3.9.0, on request): no hiring team shown -> the profiles under "People you can reach out to".
  // LinkedIn suggests these (people at the company, alumni, connections); they are NOT the hiring team, so
  // the Data Notes say so. Most jobs show only this block (real export, Nov 2026: 10 of 10).
  if (!links.length) {
    const REACH_RE = /^people you can reach out to$/i;
    const roots = pane !== document.body ? [pane, document] : [document];
    for (const root of roots) {
      const head = [...root.querySelectorAll("h1, h2, h3, h4, strong, span")].find(e => REACH_RE.test(clean(e.textContent)));
      if (!head) continue;
      let blk = head.parentElement;            // climb until the block holds a profile link
      // ...but never so far up that the block also holds another section (links there are not contacts).
      const otherSection = b => [...b.querySelectorAll("h1, h2, h3")].some(h => h !== head && !h.contains(head) && !head.contains(h) &&
        /^(about the job|about the company|more jobs|similar jobs|job search faster)/i.test(clean(h.textContent)));
      for (let i = 0; blk && i < 6 && !blk.querySelector("a[href*='/in/']"); i++) {
        if (otherSection(blk.parentElement || blk)) break;
        blk = blk.parentElement;
      }
      if (blk && !otherSection(blk)) blk.querySelectorAll("a[href]").forEach(a => { if (PROFILE_RE.test(a.href)) links.push(strip(a.href)); });
      if (links.length) { notes.push("contacts are LinkedIn's 'People you can reach out to' suggestions, not the hiring team"); break; }
      // A name with no profile link (e.g. "Muthu and others in your network"): record what is shown, never guess a URL.
      const shown = blk ? clean((blk.innerText || "").replace(/people you can reach out to/i, "")).replace(/\s*\n\s*/g, " ").slice(0, 150) : "";
      if (shown) { notes.push(`'People you can reach out to' shows: ${shown} (no profile link on the page)`); break; }
    }
  }
  const seen = new Set(), contacts = links.filter(u => { const k = u.replace(/\/$/, "").toLowerCase(); return !seen.has(k) && seen.add(k); });
  if (!contacts.length) notes.push("no hiring-team, reach-out or profile links shown");

  const description = descEl ? (descEl.innerText || descEl.textContent).replace(/\n{3,}/g, "\n\n").trim() : "";
  if (!description) notes.push("description not found (expand 'See more' or open the job page)");
  if (!titleEl) notes.push("job title not found");

  return {
    job_id: jobId,
    job_title: titleEl ? clean(titleEl.textContent) : "",
    company_name: compEl ? clean(compEl.textContent) : "",
    company_industry: industry,
    company_size: size,
    box_industry: boxIndustry,
    contact_profile_links: contacts.join("; "),
    people_section: { hiring_heading: !!hiringHead, people_heading: !!peopleHead, seen: peopleSeen.slice(0, 12) },
    job_description: description,
    location: locEl ? clean(locEl.textContent) : "",
    job_url: jobId ? `https://www.linkedin.com/jobs/view/${jobId}/` : strip(url),
    company_url: compA ? strip(compA.href).replace(/(\/company\/[^/]+).*$/, "$1/") : "",
    industry_source: industrySource,
    data_notes: notes.join("; "),
    saved_at: new Date().toISOString().slice(0, 19).replace("T", " "),
  };
};
