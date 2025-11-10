# AlwaysBlock

A macOS website blocker that's always running. The friction is always there, so you don't have to remember to block yourself.

---

## Table of Contents

- [The Idea](#the-idea)
- [Installation](#installation)
  - [Upgrading](#upgrading)
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
- [How It Actually Works](#how-it-actually-works)
- [Troubleshooting](#troubleshooting)
- [Testing](#testing)
- [Limitations](#limitations)
- [Uninstall](#uninstall)
- [License](#license)

---

## The Idea

Most website blockers work like this: you're productive, so you block distracting sites. Then you hit a slump, disable the blocker, waste time, feel bad, re-enable it. Repeat forever.

The problem is relying on yourself to actively block things when you're already in a bad state.

AlwaysBlock tries something different: the blocking is **always on**. There's always friction between you and reddit/twitter/whatever. You never have to remember to turn it on, and you can't forget to turn it back on because it never turns off.

But if the friction was too high (completely blocked, no way to access), you'd just disable the whole thing. So the friction is calibrated to be annoying enough that you usually don't bother, but permissive enough that you leave it running.

When you want to access a blocked site, you can—but you have to wait a few minutes first. The wait gives you time to reconsider. If you really need it, you'll wait. If you were just mindlessly clicking, the friction stops you.

Key points:
- It's always running (set it up once, works across reboots)
- You can always access blocked sites (this isn't parental controls)
- But there's always a delay (usually 5 minutes, configurable per site)
- The delay resets when the site blocks again (time-limited access)

I built this because I kept going in circles with traditional blockers. This approach has worked better for me. Your mileage may vary.

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

**Note:** Commands that need root privileges (start, stop, restart, etc.) will automatically prompt for your password - no need to type `sudo`.

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

### Advanced: Component-Level Control

Most users should use `start`/`stop`/`restart`, but you can control components separately if needed:

```bash
# Just the proxy daemon
alwaysblock start-proxy
alwaysblock stop-proxy
alwaysblock restart-proxy

# Just the system proxy setting
alwaysblock enable-proxy
alwaysblock disable-proxy
```

All commands automatically prompt for your password when needed.

### Auto-Start on Boot

Enable auto-start to have AlwaysBlock running automatically when your Mac boots:

```bash
# Enable auto-start on boot (prompts for password)
alwaysblock enable-autostart

# Disable auto-start
alwaysblock disable-autostart

# Check status
alwaysblock status  # Shows auto-start status
```

**Important:** With auto-start enabled, the daemon keeps services running. If you manually stop services, they'll restart within 60 seconds. To stop permanently:

```bash
alwaysblock disable-autostart  # Disable the monitoring daemon
alwaysblock stop               # Stop services
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

### What Auto-Start Does

The daemon monitors your system and:
- Starts the proxy daemon on boot
- Enables the system proxy on boot
- Checks every 60 seconds that services are running
- Automatically restarts them if they stop

**Note:** If auto-start is enabled and you manually stop services, the daemon will restart them within 60 seconds. To stop services permanently, disable auto-start first:

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
alwaysblock restart-proxy
```

### System proxy not enabled

**Re-enable:**
```bash
alwaysblock disable-proxy
alwaysblock enable-proxy
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
alwaysblock start-proxy
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
alwaysblock disable-proxy
```

This removes the proxy from system settings and restores normal internet.

---

## How It Actually Works

I tried a few different approaches before landing on this one:

1. **DNS blocking** (`/etc/hosts`)—Chrome bypassed it with DNS-over-HTTPS
2. **Network Extension**—required a lot of code and Chrome would just retry failed requests
3. **System HTTP proxy**—this is what I ended up using

The proxy approach works like this:

```
Browser tries to visit reddit.com
    ↓
macOS routes the request through our proxy (127.0.0.1:8905)
    ↓
Proxy checks if reddit.com is blocked
    ↓
If blocked: refuse the connection
If allowed: forward to reddit.com
```

This works for Chrome even with DNS-over-HTTPS because system proxy settings get enforced before DNS resolution happens.

### Why the proxy approach?

I needed something that could:
- Block sites dynamically (unblock/reblock frequently without caching issues)
- Work with modern Chrome (DoH, QUIC, all the privacy features)
- Kill active sessions immediately (so `block-all` closes your open tabs)
- Stay simple enough that I could actually maintain it

The proxy does all of this. It sees the hostname from the HTTP CONNECT request before any encryption happens, blocks what needs blocking, and forwards everything else.

### What this approach doesn't do well

- You can disable the system proxy in Settings (but that's the point—this is a commitment device, not parental controls)
- Only intercepts HTTP/HTTPS on ports 80/443 (apps on custom ports bypass it)
- Adds about 5-10ms latency per HTTPS connection
- Future TLS Encrypted ClientHello (ECH) will encrypt the hostname, breaking this approach (probably 2-3 years away)

### Other approaches I considered

This isn't meant to be comprehensive, just what I learned while building this:

- **`/etc/hosts`**: Simple and works well for permanent blocking. [SelfControl](https://selfcontrolapp.com/) combines this with packet filtering and makes it hard to disable during a timer, which is clever. But it can't interrupt active connections (open tabs keep working) and Chrome bypasses it with DoH for new connections.

- **PF IP blocking**: Works at the network layer, can't be bypassed by browser settings. But you need to know all the IPs ahead of time, sites use multiple IPs/CDNs, and IPs change.

- **Network Extension**: Most powerful option for Safari—sees full URLs, can inspect page content. Enterprise content filters use this. But it's complicated to build and Chrome only exposes IP addresses, not hostnames.

Each approach has trade-offs. I picked the one that fit what I was trying to do.

### Components

The code is split into a few Python scripts:

- **`http_proxy.py`** - HTTP/HTTPS proxy with hostname inspection
- **`system_proxy.py`** - Manages macOS system proxy settings
- **`alwaysblock.py`** - CLI for configuration and daemon management
- **`config_manager.py`** - YAML config parser with domain groups
- **`db.py`** - SQLite for session tracking and queueing
- **`session_manager.py`** - Background daemon for session expiration
- **`alwaysblock-daemon.sh`** - LaunchDaemon script for auto-start

### Some implementation details

**Subdomain matching**: If you block `google.com`, it also blocks `mail.google.com` and `drive.google.com`, but not `googleusercontent.com` (different root domain).

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
- `pending` - waiting for the delay timer
- `active` - currently accessible
- `waiting_for_domain` - queued because that domain is already active
- `completed` - expired or cancelled

**Database**: Uses SQLite to track sessions and cooldowns. Nothing fancy.

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

1. Open Gmail in Chrome (while it's not blocked)
2. Run `alwaysblock block-all`
3. Refresh the Gmail tab
4. Should get a connection error even though the tab was already open

Automated tests:

```bash
alwaysblock test
```

---

## Limitations

Things this doesn't handle:

1. You can disable the system proxy in Settings (but that's the whole point—commitment device, not parental controls)
2. Requires sudo to run the proxy
3. Only intercepts HTTP/HTTPS on ports 80/443
4. Adds about 5-10ms latency per HTTPS connection (haven't noticed this in practice)
5. Future TLS Encrypted ClientHello (ECH) will encrypt hostnames, breaking this approach (probably 2-3 years out)

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
