// options.js — popup as a read-only status mirror of `alwaysblock status` for
// the Chrome backend. Access is requested from the CLI; this only reflects state.

const BRIDGE = "http://127.0.0.1:8906";
const $ = (id) => document.getElementById(id);

async function getState() {
  const res = await fetch(`${BRIDGE}/state`, { cache: "no-store" });
  if (!res.ok) throw new Error(`bridge ${res.status}`);
  return res.json();
}

function fmtClock(epoch) {
  return new Date(epoch * 1000).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}
function fmtDelta(epoch) {
  const secs = Math.max(0, Math.round(epoch - Date.now() / 1000));
  return secs < 180 ? `${secs}s` : `${Math.round(secs / 60)} min`;
}

function item(name, right, cls) {
  const row = document.createElement("div");
  row.className = `item ${cls || ""}`;
  const n = document.createElement("span"); n.className = "name"; n.textContent = name;
  const r = document.createElement("span"); r.className = "muted"; r.textContent = right;
  row.append(n, r);
  return row;
}

function renderSessions(state) {
  const box = $("sessions");
  box.innerHTML = "";
  const active = state.active_sessions || [];
  const pending = state.pending_sessions || [];
  const waiting = state.waiting_sessions || [];

  for (const s of active) box.appendChild(item(s.name, `${fmtDelta(s.end_at)} left`));
  for (const s of pending) box.appendChild(item(s.name, `open in ${fmtDelta(s.start_at)}`, "pending"));
  for (const s of waiting) box.appendChild(item(s.name, "queued", "pending"));

  if (!active.length && !pending.length && !waiting.length) {
    box.innerHTML = `<div class="empty">Nothing unblocked — fully blocking.</div>`;
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
    renderSessions(state);
  } catch (e) {
    $("bridge").textContent = "🔴 unreachable";
    $("blocking").textContent = "unknown";
    $("sessions").innerHTML = `<div class="empty">Can't reach the bridge. Is it running?</div>`;
  }
}

render();
setInterval(render, 2000); // keep countdowns fresh while open
