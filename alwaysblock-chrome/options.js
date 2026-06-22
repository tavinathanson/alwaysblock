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
  await fetch(`${BRIDGE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: "{}"
  });
  try { chrome.runtime.sendMessage({ type: "refresh" }); } catch (_) {}
}

function fmtUntil(epoch) {
  const d = new Date(epoch * 1000);
  return d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

async function render() {
  try {
    const state = await getState();
    $("bridge").textContent = "🟢 running";
    const now = Date.now() / 1000;
    const paused = typeof state.pause_until === "number" && state.pause_until > now;
    $("blocking").textContent = paused ? `⏸ off until ${fmtUntil(state.pause_until)}` : "🟢 on";
    $("count").textContent = (state.domains || []).length;
  } catch (e) {
    $("bridge").textContent = "🔴 unreachable";
    $("blocking").textContent = "unknown";
    $("count").textContent = "—";
  }
}

$("blockAll").addEventListener("click", async () => { await command("/block-all"); render(); });
$("disable").addEventListener("click", async () => { await command("/disable"); render(); });
$("resume").addEventListener("click", async () => { await command("/resume"); render(); });

render();
