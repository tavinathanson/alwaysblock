# AlwaysBlock

A macOS website blocker that actually works with Chrome's DNS-over-HTTPS. Built as a commitment device to help you stay focused.

---

## Table of Contents

- [How It Works](#how-it-works)
- [Features](#features)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [Configuration](#configuration)
- [Usage](#usage)
  - [Basic Commands](#basic-commands)
  - [Unblocking Sites](#unblocking-sites)
  - [Managing the Proxy](#managing-the-proxy)
  - [Auto-Start on Boot](#auto-start-on-boot)
- [Advanced Features](#advanced-features)
  - [Profiles](#profiles)
  - [Tag System](#tag-system)
  - [Concurrent Penalty](#concurrent-penalty)
  - [Queueing Behavior](#queueing-behavior)
- [Auto-Start Setup](#auto-start-setup)
- [Troubleshooting](#troubleshooting)
- [Architecture](#architecture)
- [Technical Details](#technical-details)
- [Testing](#testing)
- [Performance](#performance)
- [Limitations](#limitations)
- [Uninstall](#uninstall)
- [License](#license)

---

## How It Works

AlwaysBlock uses a **system-wide HTTP/HTTPS proxy** with hostname inspection to block websites. When you try to visit a blocked site:

1. macOS redirects the request through our proxy (via System Proxy settings)
2. The proxy reads the hostname from the HTTP CONNECT request
3. If the hostname is blocked, the connection is refused
4. If allowed, the proxy forwards the traffic normally

This works for **all browsers** including Chrome with DNS-over-HTTPS enabled, because system proxy settings are enforced before DNS resolution.

### Why This Approach?

We evaluated several blocking methods. Each has trade-offs - **no solution is perfect**:

| Approach | Chrome w/ DoH | Safari | Kills Active Sessions | Complexity | User Can Bypass? |
|----------|---------------|--------|----------------------|------------|------------------|
| `/etc/hosts` only | ⚠️ New connections only | ✅ Works | ❌ No | ✅ Simple | Edit file |
| `/etc/hosts` + PF IPs | ⚠️ New connections only | ✅ Works | ⚠️ Partial | ⚠️ Medium | Edit file + disable PF |
| PF IP blocking only | ⚠️ If you know all IPs | ⚠️ If you know all IPs | ✅ Yes | ❌ High maintenance | Disable PF |
| Network Extension | ❌ IP-only for Chrome | ✅ Full URL access | ✅ Yes | ❌ Very complex | Uninstall extension |
| **System HTTP Proxy** | ✅ Works | ✅ Works | ✅ Yes | ✅ Simple | **Disable system proxy** |

**What each approach does well:**

- **`/etc/hosts`** ([SelfControl](https://selfcontrolapp.com/) uses this + PF): Excellent for "set and forget" blocking. Works across all apps. SelfControl's genius is making it hard to undo during the timer - you can't just disable it on impulse. Simple and battle-tested.

- **PF IP blocking**: Works at the network layer, blocking packets before they leave your machine. Great for known, static IPs. Can't be bypassed by changing browser settings.

- **Network Extension**: Most powerful option for Safari - can see full URLs, inspect page content, make sophisticated filtering decisions. Used by enterprise content filters.

- **System HTTP Proxy** (our choice): Best for *dynamic* blocking where you want to unblock/reblock sites frequently. Sees hostnames for all browsers, kills active sessions immediately, simple implementation.

**Why we chose the proxy approach:**

Our use case is different from SelfControl - we wanted **flexible, reversible blocking** with time-based delays. Key advantages:
- **Chrome respects system proxy settings** even with DoH enabled - proxy intercepts traffic before DNS resolution
- **Active session blocking:** `/etc/hosts` can't interrupt already-established connections (e.g., an open Gmail tab keeps working). Our proxy blocks every HTTP request, so `block-all` immediately kills active sessions.
- **Long-running connections:** Handles WebSockets and long-polling via bidirectional forwarding
- **Dynamic updates:** Reload blocklist every 5 seconds without DNS caching issues

**Our honest limitations:**
- User can disable system proxy in Settings (but that's the point - it's a *commitment device*, not parental controls)
- Only intercepts HTTP/HTTPS on ports 80/443 (apps using custom ports bypass it)
- Adds ~5-10ms latency per HTTPS connection (CONNECT handshake overhead)
- Future TLS Encrypted ClientHello (ECH) will encrypt SNI, breaking hostname inspection (2-3 years away)

---

## Features

- 🚫 **Actually blocks Chrome** - Works with DNS-over-HTTPS, QUIC, and all modern browser features
- ⏱️ **Time-based unblocking** - Configure wait times and durations before accessing sites
- 🏷️ **Tag system** - Group domains by category with tag-specific rules
- 🔄 **Session management** - Track active unblock sessions with automatic expiration
- 🌐 **Smart subdomain matching** - Blocking `google.com` also blocks `mail.google.com`
- 🎯 **Profile-based rules** - Different unblocking strategies for different contexts
- 🚀 **Auto-start on boot** - Optional LaunchDaemon for automatic startup
- 🔑 **Passwordless sudo** - Optional configuration for commands without password prompts
- 📊 **Lightweight** - Simple HTTP proxy, minimal overhead
- 🔧 **YAML configuration** - Human-readable config

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

---

## Quick Start

### 1. Start the Proxy

```bash
sudo alwaysblock start-proxy
```

The proxy daemon runs in the background and must be started as root.

### 2. Enable System Proxy

```bash
sudo alwaysblock enable-proxy
```

This configures macOS to route all HTTP/HTTPS traffic through the AlwaysBlock proxy.

### 3. Verify

```bash
alwaysblock status
```

Should show:
```
Proxy daemon: 🟢 Running
System proxy: 🟢 Enabled (2/2 services)
Auto-start:   🔴 Disabled
```

### 4. Try blocking a site

Open Chrome and try to visit a configured blocked site (e.g., `reddit.com`). You should see a connection error.

---

## Configuration

Edit `~/.config/alwaysblock/config.yaml`:

```yaml
default_profile: unblock

domains:
  # Individual domains
  reddit.com:
    tags: [social, distracting]

  netflix.com:
    tags: [ultra_distracting, entertainment]

  # Domain groups (with related domains/CDNs)
  google:
    domains:
      - google.com
      - gmail.com
      - mail.google.com
      - calendar.google.com
      - drive.google.com
      - googleusercontent.com
      - gstatic.com
    tags: [work, productivity]

  slack:
    domains:
      - slack.com
      - app.slack.com
      - slack-edge.com
      - slack-imgs.com
    tags: [work, communication]

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
      - tags: [work, communication]
        wait_override: 1   # 1 min wait for Slack/Gmail

  # Quick access
  quick:
    description: "Quick 1-minute check"
    wait: 0.5
    duration: 1

  # Emergency bypass
  bypass:
    description: "Emergency 5-minute unblock (once per hour)"
    wait: 0
    duration: 5
    cooldown: 60
```

---

## Usage

### Basic Commands

```bash
# Check status
alwaysblock status

# Block all domains immediately
alwaysblock block-all

# Cancel a specific session
alwaysblock cancel <session_id>
```

### Unblocking Sites

```bash
# Unblock a domain (uses default profile)
alwaysblock unblock reddit

# Unblock multiple domains
alwaysblock unblock reddit youtube

# Use a specific profile
alwaysblock unblock -p quick gmail

# Use bypass profile
alwaysblock unblock -p bypass facebook
```

**Important:** When you unblock multiple domains at once, each creates a separate session with its own timing. Sessions are **order-dependent** - later domains get higher concurrent penalties. However, sessions with tag overrides (like `gmail` and `slack` with 1-min wait) don't count toward the penalty for other sessions.

### Managing the Proxy

```bash
# Start proxy daemon
sudo alwaysblock start-proxy

# Stop proxy daemon
sudo alwaysblock stop-proxy

# Restart proxy daemon
sudo alwaysblock restart-proxy

# Enable system proxy
sudo alwaysblock enable-proxy

# Disable system proxy
sudo alwaysblock disable-proxy
```

### Auto-Start on Boot

```bash
# Enable auto-start on boot
sudo alwaysblock enable-autostart

# Disable auto-start
sudo alwaysblock disable-autostart

# Check status
alwaysblock status  # Shows auto-start status
```

---

## Advanced Features

### Profiles

Profiles define unblocking behavior:

- **wait**: How long to wait before accessing (minutes)
- **duration**: How long to stay unblocked (minutes)
- **cooldown**: Minimum time between uses (minutes)
- **tag_rules**: Override wait times for specific tags

Example:

```yaml
work:
  description: "Work mode - productivity tools"
  wait: 0
  duration: 120  # 2 hours
  tag_rules:
    - tags: [work, productivity]
      wait_override: 0
```

### Tag System

Tags allow categorizing domains and applying rules:

```yaml
domains:
  reddit.com:
    tags: [social, distracting]

  slack:
    domains: [slack.com]
    tags: [work, communication]

profiles:
  unblock:
    tag_rules:
      - tags: [work, communication]
        wait_override: 1  # Quick access for work tools
      - tags: [ultra_distracting]
        wait_override: 30  # Long delay for distracting sites
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

**Tag override sessions don't count toward the penalty:**

```bash
alwaysblock unblock gmail slack facebook instagram

# Results:
# gmail:     1 min (override, doesn't count)
# slack:     1 min (override, doesn't count)
# facebook:  5 min (base + 0 penalty)
# instagram: 10 min (base + 1×5 penalty from facebook only)
```

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

---

## Auto-Start Setup

AlwaysBlock can automatically start on boot without requiring password entry.

### Installation

During `./install.sh`, you'll be prompted:

```
Do you want to enable passwordless sudo for AlwaysBlock commands? (y/n)
```

Answer **y** to allow commands like `sudo alwaysblock start-proxy` without password prompts.

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
- `start-proxy`, `stop-proxy`, `restart-proxy`
- `enable-proxy`, `disable-proxy`
- `enable-autostart`, `disable-autostart`

Other sudo commands will still require a password.

---

## Troubleshooting

### Proxy not blocking

**Check status:**
```bash
alwaysblock status
```

**View logs:**
```bash
tail -f /tmp/proxy.log
```

**Restart proxy:**
```bash
sudo alwaysblock restart-proxy
```

### System proxy not enabled

**Re-enable:**
```bash
sudo alwaysblock disable-proxy
sudo alwaysblock enable-proxy
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
sudo alwaysblock start-proxy
```

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
sudo -n alwaysblock start-proxy  # Should not prompt
```

### Internet broken after disabling

```bash
sudo alwaysblock disable-proxy
```

This removes the proxy from system settings and restores normal internet.

---

## Architecture

```
┌─────────────────────────────────────┐
│ Browser (Chrome/Safari/Firefox)     │
│ Tries to visit reddit.com           │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│ macOS System Proxy Settings         │
│ HTTP/HTTPS → 127.0.0.1:8905         │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│ AlwaysBlock HTTP Proxy (Python)     │
│                                      │
│ 1. Receives CONNECT reddit.com:443  │
│ 2. Checks if reddit.com is blocked  │
│ 3. IF BLOCKED: Return 403 Forbidden │
│ 4. IF ALLOWED: Forward to reddit.com│
└─────────────────────────────────────┘
```

### Components

- **`http_proxy.py`** - HTTP/HTTPS proxy with hostname inspection
- **`system_proxy.py`** - Manages macOS system proxy settings
- **`alwaysblock.py`** - CLI for configuration and daemon management
- **`config_manager.py`** - YAML config parser with domain groups
- **`db.py`** - SQLite for session tracking and queueing
- **`session_manager.py`** - Background daemon for session expiration
- **`alwaysblock-daemon.sh`** - LaunchDaemon script for auto-start

---

## Technical Details

### Subdomain Matching

If you block `google.com`, it automatically blocks:
- `mail.google.com` ✓
- `drive.google.com` ✓
- `docs.google.com` ✓

But does NOT block:
- `googleusercontent.com` ✗ (different root domain - must list explicitly)

### Domain Groups

Use domain groups to block sites with multiple CDNs:

```yaml
reddit:
  domains:
    - reddit.com
    - www.reddit.com
    - redditstatic.com  # CSS/JS CDN
    - redd.it            # Image CDN
    - v.redd.it          # Video CDN
```

### Why Chrome Works

Chrome's DoH and modern privacy features don't bypass system proxy settings. When system proxy is configured, Chrome:

1. Sends CONNECT request to proxy for HTTPS
2. Sends full URL to proxy for HTTP
3. Proxy sees the hostname before any DNS resolution
4. Proxy can block based on hostname

### Session States

Sessions can be in one of four states:

- **`pending`** - Waiting for the wait time to elapse before becoming active
- **`active`** - Currently unblocked, domain is accessible
- **`waiting_for_domain`** - Queued because domain is in another session
- **`completed`** - Expired or cancelled

### Database Schema

```sql
CREATE TABLE sessions (
    id INTEGER PRIMARY KEY,
    profile TEXT,
    domains TEXT,  -- JSON array
    status TEXT,
    wait_minutes INTEGER,
    duration_minutes INTEGER,
    created_at TIMESTAMP,
    start_at TIMESTAMP,
    end_at TIMESTAMP,
    has_override INTEGER  -- 1 if tag override applied
);

CREATE TABLE cooldowns (
    profile TEXT PRIMARY KEY,
    last_used TIMESTAMP
);
```

---

## Testing

### Test with Chrome

1. Configure `reddit.com` as blocked (already in example config)
2. Start proxy: `sudo alwaysblock start-proxy`
3. Enable system proxy: `sudo alwaysblock enable-proxy`
4. Open Chrome and try to visit `reddit.com`
5. **Expected:** Connection refused, site doesn't load
6. Unblock: `alwaysblock unblock reddit`
7. Wait for timer or use quick profile
8. **Expected:** Reddit loads normally

### Test with open tab

1. Open Gmail in Chrome (working, not blocked)
2. Block all: `alwaysblock block-all`
3. Refresh Gmail tab
4. **Expected:** Connection error, Gmail stops working

### Run automated tests

```bash
make test
```

Tests cover:
- Domain validation and resolution
- Session queueing behavior
- Concurrent penalty calculation
- Tag override behavior
- Order independence for override sessions

---

## Performance

- **Latency overhead:** ~5-10ms per HTTPS connection (CONNECT handshake)
- **Memory:** ~15MB for proxy process
- **CPU:** <1% on modern Mac
- **No noticeable impact** on browsing speed

---

## Limitations

1. **Proxy bypass:** User could disable system proxy in Settings (but they won't - commitment device!)
2. **Requires sudo:** Proxy must run as root to bind to configured port
3. **VPN bypass:** If user installs a VPN, traffic goes through encrypted tunnel (but again, commitment device)
4. **Non-standard ports:** Only intercepts ports 80/443 (standard HTTP/HTTPS)
5. **Encrypted ClientHello (ECH):** Future TLS versions will encrypt SNI, breaking hostname inspection (2-3 years away)

---

## Uninstall

One command removes everything:

```bash
./uninstall.sh
```

This will:
- Stop the proxy daemon
- Disable system proxy
- Unload LaunchDaemon (if enabled)
- Remove CLI from `/usr/local/bin`
- Remove passwordless sudo rules (if configured)
- Optionally remove configuration and data

---

## License

MIT License - See LICENSE file

## Credits

Evolved from [taviblock](https://github.com/tavinathanson/taviblock) through multiple iterations:
- Started with DNS-based blocking (Chrome bypassed with DoH)
- Tried Network Extension (packet-level blocking failed - Chrome retried)
- Landed on system HTTP proxy (simple and actually works!)
