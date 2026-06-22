// rules.js — translate the brain's state blob into declarativeNetRequest rules.
//
// This is the ONLY place the extension touches blocking semantics, and it is a
// faithful, mechanical translation of the brain's contract — not independent
// logic. The brain (alwaysblock.py `_write_state`) already decided which hosts
// are blocked vs excluded; we only express that as DNR rules.
//
// Match semantics parity (must mirror http_proxy.py `should_block_domain` and
// config_manager.py `is_domain_blocked`):
//   * A blocked host h matches h and ALL its subdomains. declarativeNetRequest's
//     `requestDomains` does exactly this, so we never hand-roll subdomain/www
//     matching — `requestDomains: [h]` == "h or any *.h".
//   * Excluded hosts always win. We give `allow` rules a higher priority than
//     `block`/`redirect` rules, so an excluded subtree is allowed even when its
//     parent is blocked.
//   * While paused (pause_until in the future) we emit NO blocking rules at all.
//
// The Python parity test (tests/test_match_parity.py) pins the proxy to these
// same `requestDomains` semantics so the two backends can't silently drift.

// Priorities: higher number wins in DNR.
const PRIORITY_BLOCK = 1;
const PRIORITY_ALLOW = 2;

// Resource types we redirect to the friendly block page vs. hard-block. Only a
// top-level navigation should land on blocked.html; embedded sub-resources from
// a blocked host are simply blocked so they can't load on an allowed page.
const MAIN_FRAME = ["main_frame"];
const SUBRESOURCE = [
  "sub_frame", "stylesheet", "script", "image", "font",
  "object", "xmlhttprequest", "ping", "media", "websocket", "other"
];

// Whole-URL capture so the block page can offer to return you to where you were.
const CAPTURE_FULL_URL = "^(https?://.*)$";

export function buildDynamicRules(state) {
  const now = Date.now() / 1000;
  const rules = [];

  // Fully paused (manual 2-min pause or all-day disable) → block nothing.
  if (state && typeof state.pause_until === "number" && state.pause_until > now) {
    return rules;
  }

  const blocked = (state && state.domains) || [];
  const excluded = (state && state.excluded) || [];

  let id = 1;
  const blockedPageBase = chrome.runtime.getURL("blocked.html");

  for (const host of blocked) {
    // Top-level navigation → redirect to the block page, carrying the original
    // URL in ?u= so the page can send you back once access opens.
    rules.push({
      id: id++,
      priority: PRIORITY_BLOCK,
      action: {
        type: "redirect",
        redirect: { regexSubstitution: `${blockedPageBase}?u=\\1` }
      },
      condition: {
        regexFilter: CAPTURE_FULL_URL,
        requestDomains: [host],
        resourceTypes: MAIN_FRAME
      }
    });
    // Everything else from a blocked host → hard block (no half-loaded embeds).
    rules.push({
      id: id++,
      priority: PRIORITY_BLOCK,
      action: { type: "block" },
      condition: {
        requestDomains: [host],
        resourceTypes: SUBRESOURCE
      }
    });
  }

  // Excluded hosts win over any block via higher priority.
  for (const host of excluded) {
    rules.push({
      id: id++,
      priority: PRIORITY_ALLOW,
      action: { type: "allow" },
      condition: { requestDomains: [host] }
    });
  }

  return rules;
}
