// service-worker.js — the extension's heartbeat.
//
// Responsibilities (and ONLY these — no blocking logic of its own):
//   1. Poll the local AlwaysBlock bridge for the current state blob.
//   2. Cache the last good state so blocking survives the bridge being down.
//   3. Rebuild declarativeNetRequest rules from that state (see rules.js).
//   4. Schedule a prompt rule refresh when the soonest unblock window closes.
//
// MV3 service workers are ephemeral: Chrome kills this after ~30s idle. So we
// keep NO state in memory — everything durable goes to chrome.storage, and all
// timing is driven by chrome.alarms. This alarm loop is what replaces the
// proxy's session_manager.py for the extension backend.

import { buildDynamicRules } from "./rules.js";

const BRIDGE_URL = "http://127.0.0.1:8906/state";
const REFRESH_ALARM = "alwaysblock-refresh";
const REBLOCK_ALARM = "alwaysblock-reblock";
const STORAGE_KEY = "lastState";
const POLL_MINUTES = 0.5; // Chrome's minimum periodic interval.

async function fetchState() {
  // Note: if a third-party proxy extension reroutes all Chrome traffic, make
  // sure it bypasses 127.0.0.1, or this fetch (and thus rule updates) will fail.
  const res = await fetch(BRIDGE_URL, { cache: "no-store" });
  if (!res.ok) throw new Error(`bridge ${res.status}`);
  return res.json();
}

async function applyState(state) {
  const desired = buildDynamicRules(state);
  const existing = await chrome.declarativeNetRequest.getDynamicRules();
  await chrome.declarativeNetRequest.updateDynamicRules({
    removeRuleIds: existing.map((r) => r.id),
    addRules: desired
  });

  // Schedule a one-off refresh for the moment the next unblock window closes,
  // so a site re-blocks promptly instead of waiting for the next poll tick.
  const now = Date.now() / 1000;
  const ends = Object.values(state.unblocked || {}).filter((t) => t > now);
  if (ends.length) {
    const soonest = Math.min(...ends);
    chrome.alarms.create(REBLOCK_ALARM, { when: (soonest + 1) * 1000 });
  }
}

async function refresh() {
  try {
    const state = await fetchState();
    await chrome.storage.local.set({ [STORAGE_KEY]: state });
    await applyState(state);
  } catch (e) {
    // Bridge unreachable (not running, or loopback got proxied away). Keep
    // enforcing the last known state rather than failing open.
    const cached = (await chrome.storage.local.get(STORAGE_KEY))[STORAGE_KEY];
    if (cached) await applyState(cached);
    console.warn("AlwaysBlock: bridge unreachable, using cached state:", e.message);
  }
}

function ensureAlarms() {
  chrome.alarms.create(REFRESH_ALARM, { periodInMinutes: POLL_MINUTES });
}

chrome.runtime.onInstalled.addListener(() => { ensureAlarms(); refresh(); });
chrome.runtime.onStartup.addListener(() => { ensureAlarms(); refresh(); });
chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === REFRESH_ALARM || alarm.name === REBLOCK_ALARM) refresh();
});

// Let the block page and options page trigger an immediate refresh after an
// action (unblock / disable / resume) so rules update without waiting a tick.
chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg && msg.type === "refresh") {
    refresh().then(() => sendResponse({ ok: true }));
    return true; // async response
  }
});

// Kick once on load too (covers extension reloads during development).
refresh();
