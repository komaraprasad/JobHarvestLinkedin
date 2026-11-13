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

  const titleEl = first([".job-details-jobs-unified-top-card__job-title h1", ".job-details-jobs-unified-top-card__job-title",
    ".jobs-unified-top-card__job-title", ".top-card-layout__title"]);
  const compEl = first([".job-details-jobs-unified-top-card__company-name a", ".job-details-jobs-unified-top-card__company-name",
    ".jobs-unified-top-card__company-name a", ".topcard__org-name-link", ".topcard__flavor"]);
  const compA = compEl && (compEl.closest("a") || compEl.querySelector("a[href*='/company/']") || (compEl.tagName === "A" ? compEl : null));
  const locEl = first([".job-details-jobs-unified-top-card__primary-description-container .tvm__text",
    ".job-details-jobs-unified-top-card__bullet", ".topcard__flavor--bullet"]);
  const descEl = first(["#job-details", ".jobs-description__content", ".jobs-box__html-content", ".show-more-less-html__markup"]);

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
  const box = first([".jobs-company__box", "section.jobs-company", ".jobs-company"]);
  const m = box && clean(box.innerText || box.textContent).match(SIZE_RE);
  if (m) size = m[1].replace(/\s/g, ""); else notes.push("company size not shown on this page");

  // Contacts: only hiring-team blocks or links written in the description.
  const links = [];
  HIRER.forEach(s => document.querySelectorAll(s + " a[href]").forEach(a => { if (PROFILE_RE.test(a.href)) links.push(strip(a.href)); }));
  if (descEl) {
    descEl.querySelectorAll("a[href]").forEach(a => { if (PROFILE_RE.test(a.href)) links.push(strip(a.href)); });
    (descEl.innerText || "").replace(/https?:\/\/(?:[a-z]{2,3}\.)?linkedin\.com\/(?:in|pub)\/[A-Za-z0-9\-_%.]+\/?/gi, u => { links.push(u); return u; });
  }
  const seen = new Set(), contacts = links.filter(u => { const k = u.replace(/\/$/, "").toLowerCase(); return !seen.has(k) && seen.add(k); });
  if (!contacts.length) notes.push("no hiring-team or profile links shown");

  const description = descEl ? (descEl.innerText || descEl.textContent).replace(/\n{3,}/g, "\n\n").trim() : "";
  if (!description) notes.push("description not found (expand 'See more' or open the job page)");
  if (!titleEl) notes.push("job title not found");

  return {
    job_id: jobId,
    job_title: titleEl ? clean(titleEl.textContent) : "",
    company_name: compEl ? clean(compEl.textContent) : "",
    company_industry: industry,
    company_size: size,
    contact_profile_links: contacts.join("; "),
    job_description: description,
    location: locEl ? clean(locEl.textContent) : "",
    job_url: jobId ? `https://www.linkedin.com/jobs/view/${jobId}/` : strip(url),
    company_url: compA ? strip(compA.href).replace(/(\/company\/[^/]+).*$/, "$1/") : "",
    industry_source: industrySource,
    data_notes: notes.join("; "),
    saved_at: new Date().toISOString().slice(0, 19).replace("T", " "),
  };
};
