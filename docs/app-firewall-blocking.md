# App-level firewall blocking on macOS

## Goal

Block native macOS apps (like Slack) at the OS level so they can't communicate even when the proxy-based domain blocking isn't enough (e.g., apps that use certificate pinning, custom DNS, or persistent connections).

## What we tried: `socketfilterfw`

macOS ships with an application firewall at `/usr/libexec/ApplicationFirewall/socketfilterfw`. It lets you block or allow specific app binaries:

```bash
# Block an app
/usr/libexec/ApplicationFirewall/socketfilterfw --blockapp /Applications/Slack.app/Contents/MacOS/Slack

# Unblock an app
/usr/libexec/ApplicationFirewall/socketfilterfw --unblockapp /Applications/Slack.app/Contents/MacOS/Slack

# List all app rules
/usr/libexec/ApplicationFirewall/socketfilterfw --listapps
```

We integrated this into alwaysblock so that `_write_domains_for_proxy()` would also call `--blockapp` / `--unblockapp` in sync with domain blocking state. The implementation works (commands succeed, state is tracked), but **it doesn't actually block outgoing traffic**.

### Why it doesn't work

The macOS application firewall (`socketfilterfw`) only controls **incoming** connections to an app. It's designed to prevent other machines from connecting to services your apps are running. It does **not** block outgoing connections — which is what apps like Slack use to send messages, fetch channels, etc.

So `--blockapp Slack` prevents other computers from connecting to Slack on your machine, but Slack can still freely connect out to `api.slack.com`, `slack-edge.com`, etc.

### Gotcha: `socketfilterfw` is not on PATH

The binary lives at `/usr/libexec/ApplicationFirewall/socketfilterfw`, not on the default PATH. Running `sudo socketfilterfw` will fail with "command not found" — you need the full path.

## What actually works for blocking apps

### Domain-based proxy blocking (what alwaysblock already does)

For most apps, blocking their domains via the HTTP/HTTPS proxy is sufficient. Slack can't reach `api.slack.com` if the proxy returns a block page. This is the primary mechanism and works well for browser-based and most native apps.

### Alternatives for true app-level outbound blocking

If you need to block an app's outgoing connections at the OS level (beyond domain blocking), here are options that actually work:

1. **`pf` (packet filter)** — macOS's built-in packet filter can block outbound traffic by process or by destination. More complex to configure but very powerful. Requires anchors in `/etc/pf.conf`.

2. **Third-party app firewalls** — Tools like [LuLu](https://objective-see.org/products/lulu.html) (free, open source) or [Little Snitch](https://www.obdev.at/products/littlesnitch/) (paid) provide per-app outbound firewall rules with a GUI.

3. **Kill the process** — The simplest brute-force approach: `pkill -f Slack` when domains are blocked. The app can't communicate if it's not running. Downside: user has to relaunch the app manually after unblocking.

## Current state

The `socketfilterfw` integration was reverted — the code and config (`app:` field, `app_firewall.py`, `get_app_mappings()`) have been removed since it doesn't accomplish anything useful.

If a future approach is chosen (pf rules, process killing, etc.), the hook point would be `_write_domains_for_proxy()` in `alwaysblock.py`, which is called on every state transition and already computes `blocked_domains` and `unblocked_domains` sets.
