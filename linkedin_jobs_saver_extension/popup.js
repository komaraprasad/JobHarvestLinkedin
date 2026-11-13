const $ = id => document.getElementById(id);
let current = null;

const el = (tag, text, cls) => { const e = document.createElement(tag); if (text != null) e.textContent = text; if (cls) e.className = cls; return e; };
const msg = (kind, text) => { $("msg").className = "msg " + kind; $("msg").textContent = text; };
const getJobs = async () => (await chrome.storage.local.get("jobs")).jobs || [];
const setJobs = jobs => chrome.storage.local.set({ jobs });

async function readTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab || !/^https:\/\/([a-z]+\.)?linkedin\.com\/jobs\//.test(tab.url || "")) {
    $("job").replaceChildren(el("div", "Open a LinkedIn job (linkedin.com/jobs/view/… or a job selected in search) and click the icon again.", "empty"));
    return;
  }
  try {
    // Runs once, in the tab you are looking at, because you opened this popup (activeTab).
    await chrome.scripting.executeScript({ target: { tabId: tab.id }, files: ["extract.js"] });
    const [{ result }] = await chrome.scripting.executeScript({ target: { tabId: tab.id }, func: () => window.__ljtExtract() });
    current = result;
    renderJob(result);
    $("save").disabled = !(result && (result.job_title || result.job_id));
  } catch (e) {
    $("job").replaceChildren(el("div", "Could not read this page: " + e.message, "empty"));
  }
}

function renderJob(j) {
  const box = $("job"); box.replaceChildren();
  box.appendChild(el("h3", j.job_title || "(no title found)"));
  box.appendChild(el("div", j.company_name || "(no company found)", "co"));
  const dl = el("dl");
  const add = (k, v) => { dl.appendChild(el("dt", k)); const dd = el("dd"); dd.appendChild(v ? document.createTextNode(v) : el("span", "blank", "blank")); dl.appendChild(dd); };
  add("Industry", j.company_industry && `${j.company_industry} (${j.industry_source})`);
  add("Company size", j.company_size);
  add("Contacts", j.contact_profile_links && `${j.contact_profile_links.split(";").length} link(s)`);
  add("Description", j.job_description && `${j.job_description.length.toLocaleString()} chars`);
  add("Notes", j.data_notes);
  box.appendChild(dl);
}

async function renderList() {
  const jobs = await getJobs();
  $("count").textContent = `${jobs.length} saved`;
  const ul = $("list"); ul.replaceChildren();
  if (!jobs.length) { ul.appendChild(el("li", "Nothing saved yet.", "empty")); return; }
  jobs.slice().reverse().forEach(j => {
    const li = el("li"); li.appendChild(el("span", `${j.job_title} · ${j.company_name}`));
    const rm = el("button", "✕"); rm.title = "Remove";
    rm.onclick = async () => { await setJobs((await getJobs()).filter(x => x.job_url !== j.job_url)); renderList(); };
    li.appendChild(rm); ul.appendChild(li);
  });
}

$("save").onclick = async () => {
  if (!current) return;
  const jobs = await getJobs();
  const i = jobs.findIndex(x => x.job_url === current.job_url);
  if (i >= 0) jobs[i] = current; else jobs.push(current);
  await setJobs(jobs);
  msg(current.data_notes ? "warn" : "ok", (i >= 0 ? "Updated (already saved)." : "Saved.") + (current.data_notes ? " Some fields are blank — see Notes." : ""));
  renderList();
};

function download(blob, name) {
  const a = el("a"); a.href = URL.createObjectURL(blob); a.download = name;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 5000);
}
const stamp = () => new Date().toISOString().slice(0, 10);
$("xlsx").onclick = async () => { const j = await getJobs(); if (!j.length) return msg("warn", "Nothing to export."); download(toXLSX(j), `linkedin_jobs_${stamp()}.xlsx`); };
$("csv").onclick = async () => { const j = await getJobs(); if (!j.length) return msg("warn", "Nothing to export."); download(new Blob([toCSV(j)], { type: "text/csv" }), `linkedin_jobs_${stamp()}.csv`); };
$("clear").onclick = async () => { if (confirm("Delete all saved jobs from this browser?")) { await setJobs([]); renderList(); msg("ok", "Cleared."); } };

readTab(); renderList();
