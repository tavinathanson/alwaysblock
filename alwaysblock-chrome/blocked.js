// blocked.js — the unblock UI shown when DNR redirects a blocked navigation here.
//
// It holds NO blocking policy. It asks the bridge what the rules are, sends an
// unblock command, then polls the bridge until the site is actually allowed and
// returns you there. All timing decisions are made by the brain.

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

async function getState() {
  const res = await fetch(`${BRIDGE}/state`, { cache: "no-store" });
  if (!res.ok) throw new Error(`bridge ${res.status}`);
  return res.json();
}
async function command(path, body) {
  const res = await fetch(`${BRIDGE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {})
  });
  return res.json();
}
function nudgeServiceWorker() {
  // Ask the SW to refresh rules immediately so we don't wait for its poll tick.
  try { chrome.runtime.sendMessage({ type: "refresh" }); } catch (_) {}
}

// --- profile picker -------------------------------------------------------
let profiles = {};
async function init() {
  try {
    const state = await getState();
    profiles = state.profiles || {};
    const sel = $("profile");
    sel.innerHTML = "";
    for (const [name, meta] of Object.entries(profiles)) {
      const opt = document.createElement("option");
      const wait = meta.wait, dur = meta.duration;
      opt.value = name;
      opt.textContent = `${name} — ~${wait} min wait, ${dur} min access`;
      if (name === state.default_profile) opt.selected = true;
      sel.appendChild(opt);
    }
    if (!Object.keys(profiles).length) {
      const opt = document.createElement("option");
      opt.value = "";
      opt.textContent = "default";
      sel.appendChild(opt);
    }
  } catch (e) {
    setStatus(`Can't reach AlwaysBlock (${e.message}). Is the bridge running?`);
    $("unblock").disabled = true;
  }
}

function setStatus(msg) { $("status").textContent = msg || ""; }

// --- estimated countdown + authoritative poll-to-redirect -----------------
let pollTimer = null;
let countdownTimer = null;

function startCountdown(minutes) {
  let remaining = Math.max(0, Math.round(minutes * 60));
  const tick = () => {
    const m = String(Math.floor(remaining / 60)).padStart(2, "0");
    const s = String(remaining % 60).padStart(2, "0");
    $("countdown").textContent = remaining > 0 ? `${m}:${s}` : "almost…";
    if (remaining > 0) remaining -= 1;
  };
  tick();
  countdownTimer = setInterval(tick, 1000);
}

function startPolling() {
  pollTimer = setInterval(async () => {
    try {
      const state = await getState();
      if (!isBlocked(host, state)) {
        clearInterval(pollTimer); clearInterval(countdownTimer);
        $("countdown").textContent = "open!";
        if (originalUrl) location.replace(originalUrl);
      }
    } catch (_) { /* transient; keep polling */ }
  }, 3000);
}

async function requestAccess() {
  const profile = $("profile").value;
  $("unblock").disabled = true;
  setStatus("Requesting…");
  const result = await command("/unblock", { domain: host, profile });
  nudgeServiceWorker();
  if (!result.ok) {
    $("unblock").disabled = false;
    setStatus(result.output || "Couldn't start an unblock for this site.");
    return;
  }
  // Switch to the waiting view. The countdown is an estimate from the profile's
  // base wait; the redirect itself is driven by the authoritative poll below.
  $("request").classList.add("hidden");
  $("waiting").classList.remove("hidden");
  setStatus("");
  const est = (profiles[profile] && profiles[profile].wait) || 5;
  startCountdown(est);
  startPolling();
}

async function disableToday() {
  setStatus("Disabling until midnight…");
  await command("/disable", {});
  nudgeServiceWorker();
  // Give the SW a beat to clear rules, then return to the site.
  setTimeout(() => { if (originalUrl) location.replace(originalUrl); }, 1200);
}

$("unblock").addEventListener("click", requestAccess);
$("disable").addEventListener("click", disableToday);
init();
