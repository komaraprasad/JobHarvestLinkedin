// Runs only on the local dashboard (http://127.0.0.1:5000). Lets the page talk to the extension.
// If the extension is reloaded/updated while this page is open, this old copy loses its connection
// (chrome.runtime becomes undefined). Then it tells the page to reload instead of failing silently.
const post = msg => window.postMessage({ source: "ljt-ext", ...msg }, location.origin);
const alive = () => { try { return !!(chrome.runtime && chrome.runtime.id); } catch { return false; } };
const STALE = "The extension was reloaded. Reload this page (F5), then press Start again.";

async function send(msg) {
  if (!alive()) return { ok: false, stale: true, error: STALE };
  try { return await chrome.runtime.sendMessage(msg); }
  catch (e) { return { ok: false, stale: !alive(), error: alive() ? String(e && e.message || e) : STALE }; }
}

window.addEventListener("message", async e => {
  if (e.source !== window || e.origin !== location.origin || !e.data || e.data.source !== "ljt-dash") return;
  if (e.data.type === "ping") {
    const r = await send({ type: "ping" });
    if (r && r.stale) post({ type: "stale", error: STALE });
    else post({ type: "ready", version: alive() ? chrome.runtime.getManifest().version : "?", busy: r && r.busy });
  } else if (e.data.type === "start") {
    const r = await send({ type: "start", runId: e.data.runId });
    post({ type: "started", ...(r || { ok: false, error: "no answer from extension" }) });
  }
});

if (alive()) post({ type: "ready", version: chrome.runtime.getManifest().version });
