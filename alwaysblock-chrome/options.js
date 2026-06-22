// options.js — popup/options page. Mirrors `alwaysblock status` for the Chrome
// backend and exposes the same commands the CLI has. No logic of its own.

const BRIDGE = "http://127.0.0.1:8906";
const $ = (id) => document.getElementById(id);

async function getState() {
  const res = await fetch(`${BRIDGE}/state`, { cache: "no-store" });
  if (!res.ok) throw new Error(`bridge ${res.status}`);
  return res.json();
}
async function command(path) {
  const res = await fetch(`${BRIDGE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: "{}"
  });
  try { chrome.runtime.sendMessage({ type: "refresh" }); } catch (_) {}
  return res.json().catch(() => ({}));
}

function fmtClock(epoch) {
  return new Date(epoch * 1000).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}
function fmtRemaining(epoch) {
  const secs = Math.max(0, Math.round(epoch - Date.now() / 1000));
  if (secs < 180) return `${secs}s left`;
  return `${Math.round(secs / 60)} min left`;
}

function renderUnblocks(state) {
  const box = $("unblocks");
  const sessions = (state.active_sessions || []).slice().sort((a, b) => a.end_at - b.end_at);
  if (!sessions.length) {
    box.innerHTML = `<div class="empty">Nothing unblocked — fully blocking.</div>`;
    return;
  }
  box.innerHTML = "";
  for (const s of sessions) {
    const row = document.createElement("div");
    row.className = "item";
    const name = document.createElement("span");
    name.className = "name";
    name.textContent = s.name;
    const time = document.createElement("span");
    time.className = "muted";
    time.textContent = fmtRemaining(s.end_at);
    row.append(name, time);
    box.appendChild(row);
  }
}

async function render() {
  try {
    const state = await getState();
    $("bridge").textContent = "🟢 running";
    const now = Date.now() / 1000;
    const paused = typeof state.pause_until === "number" && state.pause_until > now;
    const blockedCount = (state.domains || []).length;
    $("blocking").textContent = paused
      ? `⏸ off until ${fmtClock(state.pause_until)}`
      : `🟢 on · ${blockedCount} sites`;
    renderUnblocks(state);
    // Resume only makes sense while paused; cancel only while something's unblocked.
    $("resume").disabled = !paused;
    $("cancel").disabled = !(state.active_sessions || []).length;
  } catch (e) {
    $("bridge").textContent = "🔴 unreachable";
    $("blocking").textContent = "unknown";
    $("unblocks").innerHTML = `<div class="empty">Can't reach the bridge. Is it running?</div>`;
  }
}

function flash(msg) {
  $("status").textContent = msg;
  setTimeout(() => { if ($("status").textContent === msg) $("status").textContent = ""; }, 2500);
}

async function run(path, label) {
  $("status").style.color = "#7ee0a2";
  flash(`${label}…`);
  try {
    await command(path);
    flash("Done ✓");
  } catch (_) {
    $("status").style.color = "#ff8f6b";
    flash("Failed — bridge unreachable");
  }
  render();
}

$("cancel").addEventListener("click", () => run("/block-all", "Re-blocking everything"));
$("disable").addEventListener("click", () => run("/disable", "Disabling until midnight"));
$("resume").addEventListener("click", () => run("/resume", "Resuming blocking"));

render();
// Keep countdowns fresh while the popup is open.
setInterval(render, 2000);
