# AlwaysBlock — Chrome backend

This is the **extension backend** for AlwaysBlock. It is one of two enforcement
backends (the other is the system proxy); see the [Backends section of the main
README](../README.md#backends-proxy-chrome-extension-or-both) for how they fit
together.

## What it does (and doesn't)

It is a **thin enforcer with no blocking logic of its own.** All policy —
which sites are blocked, wait times, durations, cooldowns, queueing, the
disable-until-midnight state — lives in the Python brain (`../alwaysblock.py`)
and is shared with the proxy backend. This extension only:

1. polls the local **bridge** (`alwaysblock bridge`, on `http://127.0.0.1:8906`)
   for the current blocklist, and
2. applies it as `declarativeNetRequest` rules, redirecting blocked navigations
   to a block page that POSTs unblock/disable commands back to the brain.

Because both backends read the same brain, they can never disagree.

## Files

| File | Role |
|---|---|
| `manifest.json` | MV3 manifest (declarativeNetRequest + alarms + storage; host permission for the loopback bridge) |
| `service-worker.js` | Polls the bridge on a `chrome.alarms` tick, caches state, rebuilds DNR rules. Replaces the proxy's `session_manager.py` for this backend. |
| `rules.js` | Translates the brain's state blob into DNR rules. The **only** place matching semantics live, kept in parity with the proxy by `tests/test_match_parity.py`. |
| `blocked.html` / `blocked.js` | The block page: profile picker, unblock button, countdown, returns you to the site when access opens. |
| `options.html` / `options.js` | Popup/options page mirroring `alwaysblock status`, with block-all / disable / resume. |

## Install (developer / unpacked)

1. In `~/.config/alwaysblock/config.yaml`, set `backends.extension: true`
   (and `proxy: true` if you also want system-wide coverage), then run
   `../install.sh` to set up the bridge LaunchAgent.
2. Open `chrome://extensions`, enable **Developer mode**, click **Load
   unpacked**, and select this folder. Repeat per Chrome profile.

## Gotchas

- **Loopback must be reachable.** If you run a proxy extension (e.g.
  SwitchyOmega), make sure it bypasses `127.0.0.1`/`localhost`, or the extension
  can't reach the bridge and will fall back to its last cached blocklist.
- **Incognito is off by default.** Chrome disables extensions in Incognito
  unless you opt in per extension; even then it's easy to toggle. Incognito is
  covered by the proxy backend, not this one.
- **Soft friction.** Disabling the extension is one click. For a hard lock, use
  a managed-policy force-install + `IncognitoModeAvailability=Disabled`.
