# AlwaysBlock — Chrome backend

This is the **extension backend** for AlwaysBlock. It is one of two enforcement
backends (the other is the system proxy); see the [Backends section of the main
README](../README.md#backends-proxy-chrome-extension-or-both) for how they fit
together.

## What it does (and doesn't)

It is a **thin enforcer + status view with no blocking logic and no control of
its own.** All policy — which sites are blocked, wait times, durations,
cooldowns, queueing, the disable-until-midnight state — lives in the Python brain
(`../alwaysblock.py`) and is shared with the proxy backend. This extension only:

1. polls the local **bridge** (`alwaysblock bridge`, read-only, on
   `http://127.0.0.1:8906`) for the current blocklist + session status, and
2. applies it as `declarativeNetRequest` rules, redirecting blocked navigations
   to a block page.

**You request access from the CLI**, exactly as with the proxy backend:
`alwaysblock unblock <site>`, `alwaysblock disable`, etc. The bridge is read-only
— the extension never changes state, so it can't disagree with the brain.

## Files

| File | Role |
|---|---|
| `manifest.json` | MV3 manifest. Needs `<all_urls>` host access because DNR *redirect* actions require host permission for the redirected site, and the blocklist is dynamic. |
| `service-worker.js` | Polls the bridge on a `chrome.alarms` tick, caches state, rebuilds DNR rules. Replaces the proxy's `session_manager.py` for this backend. |
| `rules.js` | Translates the brain's state blob into DNR rules. The **only** place matching semantics live, kept in parity with the proxy by `tests/test_match_parity.py`. |
| `blocked.html` / `blocked.js` | Block page: shows the exact `alwaysblock unblock <target>` command (resolving subdomains/groups via the bridge's `/resolve`), flips to a countdown once a pending unblock exists, and auto-returns you to the site when access opens. |
| `options.html` / `options.js` | Toolbar popup: a read-only mirror of `alwaysblock status` (blocking on/paused, blocked count, active/pending/queued unblocks). No action buttons. |

## Install (developer / unpacked)

1. In `~/.config/alwaysblock/config.yaml`, set `backends.extension: true`
   (and `proxy: true` if you also want system-wide coverage), then run
   `../install.sh` to set up the bridge LaunchAgent.
2. Open `chrome://extensions`, enable **Developer mode**, click **Load
   unpacked**, and select this folder. Allow site access when prompted. Repeat
   per Chrome profile.

## Gotchas

- **Blocking not working / sites load through.** DNR `redirect` requires
  `<all_urls>` host access. If the extension's site access is restricted, the
  block-page redirect silently won't fire. Check `chrome://extensions` → the
  card's site-access setting.
- **Loopback must be reachable.** If you run a proxy extension (e.g.
  SwitchyOmega), make sure it bypasses `127.0.0.1`/`localhost`, or the extension
  can't reach the bridge and falls back to its last cached blocklist.
- **Incognito is off by default.** Chrome disables extensions in Incognito
  unless you opt in per extension; even then it's easy to toggle. Incognito is
  covered by the proxy backend, not this one.
- **Soft friction.** Disabling the extension is one click. For a hard lock, use
  a managed-policy force-install + `IncognitoModeAvailability=Disabled`.
