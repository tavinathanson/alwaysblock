# AlwaysBlock

A macOS website blocker that's always running. The friction is always there, so you don't have to remember to block yourself.

---

## Table of Contents

- [The Idea](#the-idea)
- [How It Works (ELI5)](#how-it-works-eli5)
- [Backends (proxy, Chrome extension, or both)](#backends-proxy-chrome-extension-or-both)
- [Installation](#installation)
  - [Upgrading](#upgrading)
- [Quick Start](#quick-start)
- [Configuration](#configuration)
- [Usage](#usage)
  - [Basic Commands](#basic-commands)
  - [Unblocking Sites](#unblocking-sites)
  - [Maintenance](#maintenance)
  - [Advanced: Component-Level Control](#advanced-component-level-control)
- [Advanced Features](#advanced-features)
  - [Profiles](#profiles)
  - [Tag System](#tag-system)
  - [Concurrent Penalty](#concurrent-penalty)
  - [Queueing Behavior](#queueing-behavior)
  - [Quitting native apps when blocked (opt-in)](#quitting-native-apps-when-blocked-opt-in)
- [Auto-Start Setup](#auto-start-setup)
- [Troubleshooting](#troubleshooting)
- [How It Actually Works](#how-it-actually-works)
  - [The Proxy Approach](#the-proxy-approach)
  - [What AlwaysBlock Can and Can't See](#what-alwaysblock-can-and-cant-see)
  - [Privacy and Security](#privacy-and-security)
  - [What's Bypassed](#whats-bypassed)
  - [Why the Proxy Approach?](#why-the-proxy-approach)
  - [Other Approaches I Considered](#other-approaches-i-considered)
  - [Components](#components)
  - [Implementation Details](#implementation-details)
- [Testing](#testing)
- [Limitations](#limitations)
- [Uninstall](#uninstall)
- [License](#license)

---

## The Idea

Most website blockers work like this: you're productive, so you block distracting sites. Then you hit a slump, disable the blocker, waste time, feel bad, re-enable it. Repeat forever.

AlwaysBlock is different: the blocking is **always on**. There's always friction between you and reddit/twitter/whatever. You never have to remember to turn it on, and you can't forget to turn it back on because it never turns off.

The friction is calibrated to be annoying enough that you usually don't bother, but permissive enough that you leave it running. When you want to access a blocked site, you can, but you have to wait a few minutes first.

Key points:
- It's always running (set it up once, works across reboots)
- You can always access blocked sites
- There's always a delay (usually 5 minutes, configurable per site)
- The delay resets when the site blocks again (time-limited access)

I built this because I kept going in circles with traditional blockers. This approach has worked better for me.

---

## How It Works (ELI5)

AlwaysBlock uses macOS's system proxy setting. When you try to visit a website, your browser asks AlwaysBlock first. AlwaysBlock checks its list: if the site is blocked, it refuses the connection. If it's allowed, it forwards your request.

It only sees hostnames (like "reddit.com"), not your browsing content or passwords. Everything runs locally on your Mac. You can disable it anytime in System Settings → Network → Proxies.

For technical details about privacy, security, and how the proxy actually works, see [How It Actually Works](#how-it-actually-works).

---

## Backends (proxy, Chrome extension, or both)

AlwaysBlock can enforce blocking through two independent backends. There is **one
brain** — your `config.yaml`, the timing/queue logic, and the SQLite session
state are shared — and each backend is just a different way of applying what the
brain computes. You pick which backend(s) to run **per machine**, in your own
`config.yaml`; there is no repo-wide default.

```yaml
# ~/.config/alwaysblock/config.yaml
backends:
  proxy: true        # system-wide proxy (Safari, Chrome, Incognito, every app)
  extension: true    # Chrome extension (Chrome tabs only)
```

If you omit the `backends:` block entirely, AlwaysBlock behaves exactly as it
always has: **proxy on, extension off.**

### What each backend covers

| | **Proxy backend** | **Extension backend** |
|---|---|---|
| Scope | Every app & browser, system-wide | Chrome tabs only |
| Safari / native apps | ✅ covered | ❌ not covered |
| Chrome Incognito | ✅ covered | ❌ off by default (see below) |
| Chrome + a proxy extension (e.g. SwitchyOmega) routing around the system proxy | ❌ **bypassed** | ✅ covered |
| Needs sudo / system changes | Yes (manages the macOS system proxy) | **No** (per-user LaunchAgent on `127.0.0.1:8906`) |
| When a site is blocked, you see | A refused connection | A block page showing the exact `alwaysblock unblock …` command + a live countdown, then auto-returns you when access opens |
| Disable on a whim | System Settings → Network → Proxies | Toggle off in `chrome://extensions` |

### Why you might want both

The two backends cover each other's blind spots:

- The **proxy** is system-wide but is bypassed inside a Chrome profile whose
  traffic a separate proxy extension (like SwitchyOmega) reroutes to its own
  server — that traffic never reaches the system proxy.
- The **extension** blocks *inside* Chrome via `declarativeNetRequest`, which
  acts before Chrome decides where to send the request. So it still blocks even
  when a proxy extension reroutes traffic — and it doesn't conflict with that
  proxy extension (different mechanism). It also gives you a real block page
  instead of a dead connection.

Running **both** means: the extension catches the Chrome-with-proxy-extension
case, and the proxy catches Safari, Incognito, native apps, and normal Chrome.
Because both read the same brain, an `alwaysblock unblock reddit` takes effect
everywhere consistently.

> **Note on friction.** Neither backend is an unbreakable lock — this tool is
> *soft* friction by design (you can always open another browser, toggle the
> extension off, or disable the system proxy). If you want it to be genuinely
> hard to bypass, that comes from a managed-policy / MDM force-install of the
> extension plus disabling Incognito (`IncognitoModeAvailability=Disabled`), not
> from the code here.

### Setting up the extension backend

1. Set `backends.extension: true` (and `proxy: true` if you want both) in
   `~/.config/alwaysblock/config.yaml`.
2. Run `./install.sh`. With the extension enabled it installs a per-user
   **LaunchAgent** that runs the bridge (`alwaysblock bridge`) on
   `127.0.0.1:8906` — no sudo, no system changes.
3. Load the extension in Chrome (once per Chrome profile you use):
   - Open `chrome://extensions`, enable **Developer mode**,
   - **Load unpacked** → select the `alwaysblock-chrome/` folder in this repo.
   - Allow the extension's site access when asked. It needs broad host access
     (`<all_urls>`) because it redirects *any* blocked site to its block page and
     your blocklist is dynamic — it can't know the hosts in advance.
4. If you also run a proxy extension that routes Chrome's traffic, make sure it
   **bypasses `127.0.0.1`/`localhost`** so the extension can reach the bridge.
   The extension blocks via `declarativeNetRequest` regardless of proxy routing,
   so you don't need to route Chrome through AlwaysBlock to get blocking.

Control the bridge by hand (it normally runs under the LaunchAgent):

```bash
alwaysblock bridge status   # is the bridge up?
alwaysblock bridge start    # start it in the background (no sudo)
alwaysblock bridge stop
```

**How it's wired.** The extension holds **no blocking logic** and never changes
state. It polls the bridge (read-only) for the current blocklist + session
status and applies it via `declarativeNetRequest`. You manage everything from the
`alwaysblock` CLI, exactly as with the proxy:

- `alwaysblock unblock <site>` requests access — the block page shows the exact
  command, then flips to a countdown and returns you to the site when it opens.
- `alwaysblock disable` / `resume` / `block-all` also take effect in Chrome.

The extension's toolbar popup is a read-only mirror of `alwaysblock status` (what
is blocked, plus any active / pending / queued unblocks). Timing, queueing,
cooldowns, and the disable state all live in the brain, so the backends can never
disagree.

---

## Installation

One command installs everything and handles upgrades:

```bash
./install.sh
```

This will:
- ✅ Stop and uninstall any previous versions
- ✅ Clean up port conflicts
- ✅ Create Python venv at `~/.alwaysblock-venv`
- ✅ Install CLI at `/usr/local/bin/alwaysblock`
- ✅ Create config at `~/.config/alwaysblock/config.yaml`
- ✅ Optionally set up passwordless sudo
- ✅ Optionally set up auto-start on boot

**Safe to run multiple times** - preserves your configuration.

### Upgrading

To upgrade to the latest version:

```bash
alwaysblock upgrade
```

This will:
- Pull latest changes from git
- Run the install script to apply updates
- Restart services if they were running

**Note:** If upgrading from an older version, you may need to clean up old log files once: `sudo rm -f /tmp/proxy.log /tmp/session_manager.log /tmp/alwaysblock*.pid`

---

## Quick Start

### 1. Start AlwaysBlock

```bash
alwaysblock start
```

This starts the proxy daemon and enables the system proxy. You'll be prompted for your password.

### 2. Verify

```bash
alwaysblock status
```

Should show:
```
Proxy daemon: 🟢 Running
System proxy: 🟢 Enabled (2/2 services)
Auto-start:   🔴 Disabled
```

### 3. Try blocking a site

Open Chrome and try to visit a configured blocked site (e.g., `reddit.com`). You should see a connection error.

---

## Configuration

Edit `~/.config/alwaysblock/config.yaml`:

```yaml
default_profile: unblock

# Globally excluded domains (always allowed, even if parent domain is blocked)
excluded_domains:
  - accounts.google.com   # Allow Google accounts (for GSuite login)
  - myaccount.google.com  # Allow Google account management
  - accounts.youtube.com  # Allow YouTube accounts (for GSuite login)

domains:
  # Individual domains
  reddit.com:
    tags: [social, distracting]

  youtube.com:
    tags: [entertainment, distracting]

  facebook.com:
    tags: [social, distracting]

  instagram.com:
    tags: [social, distracting]

  twitter.com:
    tags: [social, distracting]

  x.com:
    tags: [social, distracting]

  netflix.com:
    tags: [ultra_distracting, entertainment]

profiles:
  # Default unblock profile
  unblock:
    description: "Standard unblock with wait time"
    wait:
      base: 5              # 5 minute wait before access
      concurrent_penalty: 5 # +5 min per concurrent unblock
    duration: 30           # Stay unblocked for 30 minutes

    # Tag-based overrides
    tag_rules:
      - tags: [ultra_distracting]
        wait_override: 30  # 30 min wait for Netflix

  # Quick access (all domains)
  quick:
    description: "Quick 1-minute check"
    wait: 0.5
    duration: 1
    target_type: all       # No targets; runs independently by default

  # Emergency bypass (all domains)
  bypass:
    description: "Emergency 5-minute unblock (once per hour)"
    wait: 0
    duration: 5
    cooldown: 60
    target_type: all       # No targets; runs independently by default

  # Peek at a single site
  peek:
    description: "Quick peek at one site"
    wait: 0
    duration: 1
    target_type: single    # Exactly one target required
```

---

## Usage

### Basic Commands

```bash
# Check status
alwaysblock status

# Start all services (prompts for password)
alwaysblock start

# Stop all services
alwaysblock stop

# Restart all services
alwaysblock restart

# Block all domains immediately
alwaysblock block-all

# Cancel a specific session
alwaysblock cancel <session_id>
```

Commands that need root privileges (start, stop, restart, etc.) will automatically prompt for your password.

### Unblocking Sites

```bash
# Unblock a domain (uses default profile)
alwaysblock unblock reddit

# Unblock multiple domains
alwaysblock unblock reddit youtube

# Use a specific profile
alwaysblock unblock -p quick reddit

# Use bypass profile
alwaysblock unblock -p bypass facebook
```

When you unblock multiple domains at once, each creates a separate session with its own timing. Sessions are **order-dependent**: later domains get higher concurrent penalties.

### Maintenance

```bash
# Upgrade to latest version
alwaysblock upgrade

# Run tests
alwaysblock test

# Uninstall completely (prompts for password)
alwaysblock uninstall

# Uninstall and remove all data
alwaysblock uninstall --remove-data
```

All commands automatically prompt for your password when needed. For auto-start on boot configuration, see [Auto-Start Setup](#auto-start-setup).

---

## Advanced Features

### Profiles

Profiles define unblocking behavior:

- **wait**: How long to wait before accessing (minutes)
- **duration**: How long to stay unblocked (minutes)
- **cooldown**: Minimum time between uses (minutes)
- **tag_rules**: Override wait times for specific tags
- **target_type**: Controls which targets the profile accepts:
  - `all`: Must be called without targets (applies to all domains). Runs independently by default.
  - `single`: Must be called with exactly one target
  - Omitted: Legacy behavior (can be either)
- **independent**: Override the default independent behavior. Profiles with `target_type: all` default to `true`; others default to `false`.

Example:

```yaml
work:
  description: "Work mode - productivity tools"
  wait: 0
  duration: 120  # 2 hours
  tag_rules:
    - tags: [work, productivity]
      wait_override: 0

# Bypass runs independently (default for target_type: all)
bypass:
  wait: 0
  duration: 5
  cooldown: 60
  target_type: all      # No targets; runs independently by default

# Peek at a single site
peek:
  wait: 0
  duration: 1
  target_type: single   # Exactly one target required
```

### Tag System

Tags allow categorizing domains and applying rules:

```yaml
domains:
  reddit.com:
    tags: [social, distracting]

  netflix.com:
    tags: [ultra_distracting, entertainment]

profiles:
  unblock:
    tag_rules:
      - tags: [ultra_distracting]
        wait_override: 30  # Long delay for Netflix
```

### Concurrent Penalty

When you unblock multiple domains at once, each subsequent domain gets an additional wait penalty:

```bash
# With concurrent_penalty: 5
alwaysblock unblock reddit youtube twitter

# Results:
# reddit:  5 min (base)
# youtube: 10 min (base + 1×5 penalty)
# twitter: 15 min (base + 2×5 penalty)
```

This makes you think twice before opening multiple distracting sites at once.

### Queueing Behavior

When you try to unblock a domain that's already in an active or pending session:

1. **Same domain queued**: New session enters `waiting_for_domain` status
2. **Wait time calculated later**: When the domain becomes free, the wait time is calculated based on the state at that moment
3. **Automatic activation**: Session manager daemon checks every 30 seconds and activates waiting sessions

Example:

```bash
# Start first session
alwaysblock unblock reddit  # Active for 30 minutes

# Try to unblock again while still active
alwaysblock unblock reddit  # Status: waiting_for_domain

# After first session expires, second session automatically becomes active
```

### Independent Sessions

Some profiles (like `bypass` and `quick`) are marked as `independent: true`. These sessions:

- **Never queue**: They start immediately regardless of other active sessions
- **Don't cancel others**: Existing sessions continue running
- **Run concurrently**: When an independent session ends, other sessions remain active

Example:

```bash
# Start a session for instagram
alwaysblock unblock instagram  # Active for 30 minutes

# Start bypass (independent) - doesn't affect instagram session
alwaysblock bypass             # All domains unblocked for 5 minutes

# When bypass ends, instagram is still unblocked (its session continues)
```

This is useful for temporary "everything unblocked" scenarios that shouldn't disrupt existing sessions.

### Quitting native apps when blocked (opt-in)

Some native apps hide a blocked connection instead of surfacing it. Slack is the
classic case: while `slack.com` is blocked by the proxy, you can type a message,
hit send, and it *looks* sent — but it silently never goes through. There's no
clear "you're blocked" signal.

The **app watchdog** fixes this. It's an opt-in helper that **quits an app
whenever its sites are blocked**, so "blocked" is unmistakable — the app just
won't stay open. When you `alwaysblock unblock slack`, it stops quitting and you
can reopen the app normally. (The proxy still does the actual blocking; the
watchdog only closes the app.)

It's **off by default**. Turn it on by adding a `kill_apps:` block to your
config:

```yaml
# ~/.config/alwaysblock/config.yaml
kill_apps:
  - app: Slack             # exact process name — check with: pgrep -x Slack
    when_blocked: [slack]   # config domain or group name(s)
```

Then install the watchdog LaunchAgent (or just re-run `install.sh`, which picks
this up automatically):

```bash
cp com.alwaysblock.watchdog.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.alwaysblock.watchdog.plist
```

- Runs as **you** — no sudo, no system changes (like the Chrome bridge).
- Polls ~1s and sends `SIGTERM`, so an app you open while blocked is closed
  almost as fast as it opens — far quicker than the old "AppleScript that kills
  Slack," which noticed late and let the app run for several seconds first.
- Honors pauses and `disable` (during a travel-disable, nothing is quit).
- Check it anytime: `alwaysblock watchdog status` shows whether each configured
  app is currently blocked, and `alwaysblock status` lists it alongside the
  backends. Drive it by hand with `alwaysblock watchdog {start,stop}`.

> **Note:** `app` is the exact process name macOS uses (what `pgrep -x` matches),
> which is usually the name in Activity Monitor. The watchdog complements the
> **proxy** backend; it doesn't depend on the Chrome extension.

---

## Auto-Start Setup

AlwaysBlock can automatically start on boot without requiring password entry.

### Installation

During `./install.sh`, you'll be prompted:

```
Do you want to enable passwordless sudo for AlwaysBlock commands? (y/n)
```

Answer **y** to allow commands like `alwaysblock start` without password prompts.

```
Do you want AlwaysBlock to start automatically on boot? (y/n)
```

Answer **y** to enable auto-start on boot.

### What Gets Started

When auto-start is enabled, the LaunchDaemon will:

1. Wait 5 seconds for network to be ready
2. Start the proxy daemon
3. Enable system proxy
4. Monitor every 60 seconds to ensure both services are running
5. Automatically restart services if they stop

### What Auto-Start Does

The daemon monitors your system and:
- Starts the proxy daemon on boot
- Enables the system proxy on boot
- Checks every 60 seconds that services are running
- Automatically restarts them if they stop

To stop services permanently, disable auto-start first:

```bash
alwaysblock disable-autostart
alwaysblock stop
```

### Files Created

- `/Library/LaunchDaemons/com.alwaysblock.daemon.plist` - LaunchDaemon config
- `/usr/local/bin/alwaysblock-daemon` - Daemon wrapper script
- `/etc/sudoers.d/alwaysblock` - Passwordless sudo rules (optional)

### Logs

```bash
# Daemon logs
tail -f /tmp/alwaysblock_daemon.log
tail -f /tmp/alwaysblock_daemon_error.log

# Proxy logs
tail -f /tmp/proxy.log

# Session manager logs
tail -f /tmp/session_manager.log
```

### Security

The passwordless sudo configuration is limited to specific alwaysblock commands only:
- `start`, `stop`, `restart`
- `enable-autostart`, `disable-autostart`

Other sudo commands will still require a password.

---

## Troubleshooting

### Can't login to WiFi networks (captive portals)

If you're joining a WiFi network at a coffee shop, airport, or hotel and the login page doesn't appear, that used to be an AlwaysBlock issue. It's fixed now.

Those networks use "captive portals" (login pages hosted on local IP addresses like 192.168.1.1). AlwaysBlock now automatically bypasses the proxy for local networks (192.168.x.x, 10.x.x.x, etc.), Apple's captive portal detection (captive.apple.com), and localhost.

**To verify bypass rules are set:**
```bash
networksetup -getproxybypassdomains Wi-Fi
```

You should see the list of bypass domains. If you installed AlwaysBlock before this fix, restart the proxy to apply:
```bash
alwaysblock restart
```

### Proxy not blocking

**Check status:**
```bash
alwaysblock status
```

**View logs:**
```bash
tail -f /tmp/proxy.log
```

**Restart services:**
```bash
alwaysblock restart
```

### System proxy not enabled

**Re-enable:**
```bash
alwaysblock stop
alwaysblock start
```

**Manual check in System Settings:**
- Open System Settings → Network → [Your Network] → Details → Proxies
- Web Proxy (HTTP) should be `127.0.0.1:8905`
- Secure Web Proxy (HTTPS) should be `127.0.0.1:8905`

### Sites not loading at all

**Check if proxy is running:**
```bash
lsof -i :8905
```

**If not running:**
```bash
alwaysblock start
```

### Sites intermittently fail to load (DNS)

If pages intermittently fail to load (especially ad/analytics/CDN domains), the cause is usually a flaky DNS resolver rather than AlwaysBlock's blocking. See [docs/dns-troubleshooting.md](docs/dns-troubleshooting.md).

### Auto-start not working after reboot

**Check LaunchDaemon:**
```bash
sudo launchctl list | grep alwaysblock
```

**Check logs:**
```bash
cat /tmp/alwaysblock_daemon.log
cat /tmp/alwaysblock_daemon_error.log
```

**Manually reload:**
```bash
sudo launchctl unload /Library/LaunchDaemons/com.alwaysblock.daemon.plist
sudo launchctl load /Library/LaunchDaemons/com.alwaysblock.daemon.plist
```

### Still prompting for password

**Verify sudoers file:**
```bash
sudo cat /etc/sudoers.d/alwaysblock
```

Should show your username instead of `USERNAME`.

**Test:**
```bash
alwaysblock start  # Should not prompt for password
```

### Using a VPN or proxy extension (e.g., Tailscale + Zero Omega)

Chrome proxy extensions like Zero Omega (SwitchyOmega) override the macOS system proxy, which means AlwaysBlock's blocking won't apply to Chrome traffic routed through the extension.

**Fix:** Configure your proxy extension to route traffic through AlwaysBlock's proxy instead of going direct.

For **Zero Omega** (or SwitchyOmega):

1. Create a new proxy profile (e.g., "AlwaysBlock"):
   - **Scheme: HTTP** (not HTTPS — AlwaysBlock's proxy speaks plain HTTP and handles HTTPS via CONNECT)
   - **Server:** `127.0.0.1`
   - **Port:** `8905`
   - No bypass list needed (AlwaysBlock handles its own bypass rules internally)

2. In your **auto switch** profile, change the **Default** from `[Direct]` to your new `AlwaysBlock` profile.

Now your VPN/proxy rules still work for matched conditions (e.g., routing `simba` traffic through a Tailscale proxy), while everything else goes through AlwaysBlock for blocking.

**Common mistake:** Setting the proxy scheme to HTTPS instead of HTTP. AlwaysBlock's proxy doesn't speak TLS — Chrome will fail to connect if you set HTTPS as the scheme. Use **HTTP** even though it handles HTTPS traffic (via the standard CONNECT method).

### Internet broken after disabling

```bash
alwaysblock stop
```

This stops all services and restores normal internet.

---

## How It Actually Works

### The Proxy Approach

AlwaysBlock uses macOS's system HTTP proxy setting. Here's the flow:

```
Browser tries to visit reddit.com
    ↓
macOS checks bypass rules (192.168.x.x, captive.apple.com, etc.)
    ↓
If bypassed: connect directly
Otherwise: route through our proxy (127.0.0.1:8905)
    ↓
Proxy checks if reddit.com is blocked
    ↓
If blocked: refuse the connection
If allowed: forward to reddit.com
```

This works for Chrome even with DNS-over-HTTPS because system proxy settings get enforced before DNS resolution happens.

### What AlwaysBlock Can and Can't See

**AlwaysBlock is not a firewall or deep packet inspector.** It only sees the hostname (like "reddit.com") from the initial HTTPS CONNECT request. It cannot see:
- What pages you visit
- What you type
- Any encrypted content
- Anything after the connection is established

It just sees "this app wants to connect to reddit.com" and decides yes/no.

### Privacy and Security

**No MITM (man-in-the-middle).** AlwaysBlock doesn't decrypt HTTPS traffic. It only reads the unencrypted hostname from the connection request (this is how all HTTP proxies work).

**Runs locally.** Everything runs on your Mac (127.0.0.1). No data leaves your computer. No cloud service, no telemetry.

**Requires sudo.** Starting the proxy requires admin password because it needs to bind to a port and modify system settings. The code is open source if you want to audit it.

### What's Bypassed

**Local networks:** Traffic to your router (192.168.x.x), printer, local servers, etc. doesn't go through the proxy. Neither do captive portals (WiFi login pages).

**Non-HTTP traffic:** Apps that use custom protocols or ports (like SSH, games, VPNs) bypass it entirely. Only HTTP/HTTPS on ports 80/443 are intercepted.

**You can disable it anytime.** Go to System Settings → Network → [Your Network] → Proxies and uncheck the boxes. Your internet works normally.

**Browser extensions can bypass it.** VPN extensions, proxy extensions, or changing browser proxy settings can bypass AlwaysBlock.

**It's easy to circumvent.** If you want to bypass it, you can.

### Why the proxy approach?

I needed something that could:
- Block sites dynamically (unblock/reblock frequently without caching issues)
- Work with modern Chrome (DoH, QUIC, all the privacy features)
- Kill active sessions immediately (so `block-all` closes your open tabs)
- Stay simple enough that I could actually maintain it

The proxy does all of this. It sees the hostname from the HTTP CONNECT request before any encryption happens, blocks what needs blocking, and forwards everything else.

### Limitations of this approach

- You can disable the system proxy in Settings
- Only intercepts HTTP/HTTPS on ports 80/443 (apps on custom ports bypass it)
- Adds about 5-10ms latency per HTTPS connection
- Future TLS Encrypted ClientHello (ECH) will encrypt the hostname, breaking this approach (probably 2-3 years away)

### Other approaches I considered

- **`/etc/hosts`**: Simple and works well for permanent blocking. [SelfControl](https://selfcontrolapp.com/) combines this with packet filtering and makes it hard to disable during a timer, which is clever. But it can't interrupt active connections (open tabs keep working) and Chrome bypasses it with DoH for new connections.

- **PF IP blocking**: Works at the network layer, can't be bypassed by browser settings. But you need to know all the IPs ahead of time, sites use multiple IPs/CDNs, and IPs change.

- **Network Extension**: Most powerful option for Safari. Sees full URLs, can inspect page content. Enterprise content filters use this. But it's complicated to build and Chrome only exposes IP addresses, not hostnames.

Each approach has trade-offs. I picked the one that fit what I was trying to do.

### Components

The code is split into a few Python scripts:

- **`http_proxy.py`**: HTTP/HTTPS proxy with hostname inspection
- **`system_proxy.py`**: Manages macOS system proxy settings
- **`alwaysblock.py`**: CLI for configuration and daemon management
- **`config_manager.py`**: YAML config parser with domain groups
- **`db.py`**: SQLite for session tracking and queueing
- **`session_manager.py`**: Background daemon for session expiration
- **`alwaysblock-daemon.sh`**: LaunchDaemon script for auto-start

### Implementation Details

**Subdomain matching**: If you block `reddit.com`, it also blocks `old.reddit.com` and `www.reddit.com`, but not `redd.it` (different root domain).

**Domain groups**: Sites often use multiple CDNs, so you can group related domains:

```yaml
reddit:
  domains:
    - reddit.com
    - redditstatic.com  # CSS/JS
    - redd.it           # images
    - v.redd.it         # video
```

**Session states**: When you unblock a site, it goes through states:
- `pending`: waiting for the delay timer
- `active`: currently accessible
- `waiting_for_domain`: queued because that domain is already active
- `completed`: expired or cancelled

**Database**: Uses SQLite to track sessions and cooldowns.

---

## Testing

Quick test that it works:

1. Start AlwaysBlock: `alwaysblock start`
2. Try to visit a blocked site like `reddit.com` in Chrome
3. Should get a connection error
4. Unblock it: `alwaysblock unblock reddit`
5. Wait out the timer (or use `-p quick` for a shorter wait)
6. Reddit should load

Test that `block-all` kills active sessions:

1. Unblock and open Reddit in Chrome
2. Run `alwaysblock block-all`
3. Refresh the Reddit tab
4. Should get a connection error even though the tab was already open

Automated tests:

```bash
alwaysblock test
```

---

## Limitations

- You can disable the system proxy in Settings
- Requires sudo to run the proxy
- Only intercepts HTTP/HTTPS on ports 80/443
- Adds about 5-10ms latency per HTTPS connection
- Future TLS Encrypted ClientHello (ECH) will encrypt hostnames, breaking this approach (probably 2-3 years out)

---

## Uninstall

One command removes everything:

```bash
alwaysblock uninstall
```

This will:
- Stop all running services
- Disable auto-start (if enabled)
- Disable system proxy
- Remove CLI from `/usr/local/bin`
- Remove passwordless sudo rules (if configured)
- Ask if you want to remove configuration and data

To skip the prompt and remove everything including data:

```bash
alwaysblock uninstall --remove-data
```

---

## License

MIT License - See LICENSE file

## Credits

Evolved from [taviblock](https://github.com/tavinathanson/taviblock) through multiple iterations:
- Started with DNS-based blocking (Chrome bypassed with DoH)
- Tried Network Extension (packet-level blocking failed - Chrome retried)
- Landed on system HTTP proxy (simple and actually works!)
