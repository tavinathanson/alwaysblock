// blocked.js — shown when a blocked navigation is redirected here. It does NOT
// request access (that's the CLI's job). It tells you the exact command to run,
// reflects status, and sends you back to the site the moment access opens.

const BRIDGE = "http://127.0.0.1:8906";

const params = new URLSearchParams(location.search);
const originalUrl = params.get("u") || "";
let host = "this site";
try { host = new URL(originalUrl).hostname.toLowerCase(); } catch (_) {}

const $ = (id) => document.getElementById(id);
$("host").textContent = host;

// --- match semantics (mirror of rules.js / the proxy) ---------------------
function matches(h, list) {
  return (list || []).some((d) => h === d || h.endsWith("." + d));
}
function isBlocked(h, state) {
  const now = Date.now() / 1000;
  if (state && typeof state.pause_until === "number" && state.pause_until > now) return false;
  if (matches(h, state && state.excluded)) return false;
  return matches(h, state && state.domains);
}
function pendingFor(h, state) {
  return (state.pending_sessions || []).find((s) => matches(h, s.domains)) || null;
}

async function getState() {
  const res = await fetch(`${BRIDGE}/state`, { cache: "no-store" });
  if (!res.ok) throw new Error(`bridge ${res.status}`);
  return res.json();
}
async function resolveTarget() {
  try {
    const res = await fetch(`${BRIDGE}/resolve?host=${encodeURIComponent(host)}`, { cache: "no-store" });
    const data = await res.json();
    return data.target || null;
  } catch (_) { return null; }
}

// --- the unblock command --------------------------------------------------
let command = `alwaysblock unblock ${host}`;
async function initCommand() {
  const target = await resolveTarget();
  if (target) command = `alwaysblock unblock ${target}`;
  $("cmd").textContent = command;
}
$("copy").addEventListener("click", async () => {
  try { await navigator.clipboard.writeText(command); $("copy").textContent = "Copied"; }
  catch (_) { $("copy").textContent = "Copy failed"; }
  setTimeout(() => { $("copy").textContent = "Copy"; }, 1500);
});

// --- view switching + auto-redirect ---------------------------------------
function showCmd() { $("cmd-view").classList.remove("hidden"); $("wait-view").classList.add("hidden"); }
function showWait(startEpoch) {
  $("cmd-view").classList.add("hidden");
  $("wait-view").classList.remove("hidden");
  const secs = Math.max(0, Math.round(startEpoch - Date.now() / 1000));
  const m = String(Math.floor(secs / 60)).padStart(2, "0");
  const s = String(secs % 60).padStart(2, "0");
  $("countdown").textContent = secs > 0 ? `${m}:${s}` : "almost…";
}

async function tick() {
  let state;
  try { state = await getState(); }
  catch (_) { $("foot").textContent = "Can't reach AlwaysBlock — is the bridge running?"; return; }

  if (!isBlocked(host, state)) {
    $("foot").textContent = "Access open — continuing…";
    // Make the service worker drop the DNR block rule before we navigate, or
    // the redirect would bounce us right back here until its next poll tick.
    try { await chrome.runtime.sendMessage({ type: "refresh" }); } catch (_) {}
    if (originalUrl) location.replace(originalUrl);
    return;
  }

  const pending = pendingFor(host, state);
  if (pending) {
    showWait(pending.start_at);
  } else {
    showCmd();
  }

  const blockedCount = (state.domains || []).length;
  const activeCount = (state.active_sessions || []).length;
  $("foot").textContent = `Blocking on · ${blockedCount} sites blocked`
    + (activeCount ? ` · ${activeCount} unblocked` : "");
}

initCommand();
tick();
setInterval(tick, 2000);
