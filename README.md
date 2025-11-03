# AlwaysBlock

A macOS website blocker that uses Network Extensions for robust, unbypassable blocking. Unlike traditional DNS-based blockers, AlwaysBlock intercepts network connections at the system level.

## Features

- 🚫 **Unbypassable blocking** - Works at the network packet level, not just DNS
- ⏱️ **Smart unblocking** - Configurable wait times and durations to encourage mindful browsing
- 🏷️ **Tag system** - Group domains by category with tag-specific rules
- 🔄 **Session management** - Track active unblock sessions with automatic expiration
- 🌐 **Domain groups** - Automatically blocks CDNs and related domains
- 🎯 **Profile-based rules** - Different unblocking strategies for different contexts
- 📊 **No daemon required** - Network Extension handles all blocking
- 🔧 **YAML configuration** - Human-readable config compatible with taviblock

## Architecture

AlwaysBlock consists of three components:

1. **Network Extension** (`AlwaysBlockApp.app`) - System-level content filter that blocks network connections
2. **CLI** (`alwaysblock`) - Command-line tool for managing blocked domains
3. **Configuration** - YAML-based config with domain groups and unblocking profiles

No background daemon is needed - the Network Extension runs continuously and the CLI directly updates the blocking rules.

### How Network Extension Blocking Works

The Network Extension uses macOS's `NEFilterDataProvider` to intercept network traffic:

1. **Safari & System-Respecting Apps**: Connections include hostname via `remoteHostname`, blocking is straightforward
2. **Chrome & Chromium Browsers**: Often make direct IP connections without hostnames, requiring SNI (Server Name Indication) inspection
3. **SNI Extraction**: For connections without hostnames, the filter peeks at TLS ClientHello packets to extract the actual domain being accessed

### Why Chrome Is Challenging

Chrome intentionally bypasses many system-level filtering mechanisms as a "privacy and security feature." This creates several challenges:

**DNS Bypassing**: Chrome uses DNS-over-HTTPS (DoH) by default, sending DNS queries through encrypted HTTPS connections to Google's servers (8.8.8.8) instead of using the system's DNS resolver. This completely bypasses traditional DNS-based blocking methods like `/etc/hosts` or custom DNS servers.

**Direct IP Connections**: Chrome often resolves domains internally and makes direct TCP connections to IP addresses without providing the hostname to the operating system's network stack. When our Network Extension sees these connections, `remoteHostname` is `nil`, so we can't block by domain name alone.

**QUIC Protocol**: Chrome defaults to using QUIC (HTTP/3 over UDP) instead of traditional TCP connections when available. QUIC encrypts connection metadata differently than TLS, making hostname extraction more difficult. Our SNI extraction works on standard TLS (TCP) connections but not QUIC, which is why we recommend disabling it via `chrome://flags/#enable-quic`.

**Our Workaround & Its Limitation**: We implemented SNI (Server Name Indication) extraction by peeking at the first 512 bytes of outbound TLS handshake data. When Chrome makes a TLS connection, it includes the target hostname in the ClientHello packet's SNI extension. We parse this binary data to extract the hostname and block accordingly.

However, there are two major limitations:

1. **Multiple Root Domains**: Modern websites use separate domains for CDNs and services. For example, `reddit.com` also loads from `redditstatic.com` (CSS/JS), `redd.it` (images), and `v.redd.it` (videos). These are NOT subdomains of `reddit.com` - they're completely different root domains that must be listed explicitly. Our subdomain matcher works perfectly (e.g., `mail.google.com` matches `google.com`), but it can't know that `redditstatic.com` belongs to Reddit.

2. **Packet-Level Blocking Limitation**: The fundamental issue with `NEFilterDataProvider` is that `handleOutboundData()` returning `.drop()` only drops individual data packets, not the entire TCP connection. Chrome is resilient - when it detects dropped packets, it retries the connection. This creates a race condition where the site blocks for ~1 second (while packets are dropped), then Chrome successfully retries and the connection succeeds. This is why you might see "reddit blocks briefly then loads" in Chrome.

**Technical Deep Dive**: When Chrome connects to a blocked site:
1. Chrome resolves `reddit.com` via DoH → gets IP `151.101.193.140`
2. Chrome connects to `151.101.193.140` (no hostname provided to OS)
3. Network Extension's `handleNewFlow()` sees `remoteHostname = nil`
4. Extension returns `.filterDataVerdict()` to peek at TLS handshake
5. Extension's `handleOutboundData()` receives TLS ClientHello packet
6. `extractSNIHostname()` parses packet → extracts `reddit.com`
7. `shouldBlockDomain("reddit.com")` returns `true`
8. Extension returns `.drop()` for that packet
9. **Chrome retries the TLS handshake** → eventually succeeds

The issue is architectural: `NEFilterDataProvider` can inspect and drop packets, but by the time we've extracted the SNI hostname, the TCP connection is already established. Dropping individual packets doesn't kill the connection, and Chrome simply retries until it succeeds.

**Current State:**
- ✅ **Safari**: Fully blocked - Safari provides `remoteHostname` directly, allowing immediate blocking at connection time
- ⚠️ **Chrome**: Unreliable - SNI extraction works, but Chrome bypasses packet-level drops via retry logic
  - Sites may block for 1-2 seconds before loading
  - Disable QUIC (`chrome://flags/#enable-quic` → Disabled) required for SNI extraction to work at all
- 🔧 **Future**: Need kernel-level approach (PF packet filter, transparent proxy, or hosts file) that can kill entire connections, not just packets

## Prerequisites

- macOS 13+ (Ventura or later)
- Xcode (for building the Network Extension)
- Python 3.8+
- Temporarily disabled System Integrity Protection (SIP) for development

## Installation

### Step 1: Disable SIP (Temporary, for Development)

1. Restart your Mac and hold the power button (Apple Silicon) or Command+R (Intel)
2. Open Terminal from the Utilities menu
3. Run: `csrutil disable`
4. Restart your Mac

**Important**: Re-enable SIP after development by running `csrutil enable` in Recovery Mode.

### Step 2: Enable Developer Mode

```bash
sudo systemextensionsctl developer on
```

### Step 3: Build the Network Extension

1. Open `AlwaysBlockApp/AlwaysBlock.xcodeproj` in Xcode
2. Select the **AlwaysBlock** target
3. Under "Signing & Capabilities":
   - Choose "Sign to Run Locally" or select your team
   - Ensure "Automatically manage signing" is checked
4. Select the **AlwaysBlockExtension** target and repeat step 3
5. Build and run (Cmd+R)

### Step 4: Approve the System Extension

When you first run the app:
1. You'll see a prompt to allow the system extension
2. Click "Open System Settings" or go to System Settings → Privacy & Security
3. Look for "System software from developer..." message
4. Click "Allow" and enter your password

### Step 5: Install the CLI

```bash
sudo ./install-direct.sh
```

This will:
- Create a Python virtual environment at `~/.alwaysblock-venv`
- Install dependencies (PyYAML)
- Install the `alwaysblock` command to `/usr/local/bin/`
- Set up configuration directories

## Configuration

Edit `~/.config/alwaysblock/config.yaml` to configure domains and profiles:

```yaml
domains:
  # Individual domains
  reddit.com:
    tags: [social]
  
  # Domain groups (with CDNs)
  youtube:
    domains:
      - youtube.com
      - googlevideo.com
      - ytimg.com
    tags: [entertainment, streaming]

profiles:
  # Default profile with wait times
  unblock:
    wait:
      base: 5              # 5 minute wait
    duration: 30           # Stay unblocked for 30 minutes
    
  # Quick access for work sites
  work:
    tags: [work, productivity]
    wait: 0
    duration: 120          # 2 hours
```

## Usage

### Basic Commands

```bash
# Show status
alwaysblock status

# Temporarily unblock a domain (uses default profile)
alwaysblock unblock reddit

# Unblock with a specific profile
alwaysblock unblock youtube -p quick

# Block all domains immediately
alwaysblock block-all

# Cancel an unblock session
alwaysblock cancel <session_id>
```

### Unblocking Behavior

When you unblock a domain:
1. A timer starts based on the profile's wait time
2. After the wait, the domain becomes accessible
3. It stays unblocked for the profile's duration
4. The domain is automatically re-blocked when time expires

### Domain Groups

When you block/unblock a main domain, related CDNs are included:

- `reddit.com` → also affects `redd.it`, `redditstatic.com`
- `youtube.com` → also affects `googlevideo.com`, `ytimg.com`
- `twitter.com` → also affects `t.co`, `twimg.com`, `x.com`

## How It Works

1. **Configuration** is stored in YAML and SQLite database
2. **CLI** manages the configuration and writes blocked domains to a JSON file
3. **Network Extension** monitors the JSON file and blocks matching connections
4. **No DNS changes** - works at the network level, can't be bypassed

The Network Extension reads from:
```
/tmp/alwaysblock_domains.json
```

**Why `/tmp`?** App Group containers require a paid Apple Developer account for proper signing. Using `/tmp` allows local development without a certificate while still sharing data between the CLI and Network Extension.

## Troubleshooting

### Extension not blocking?

1. Check if it's running:
   ```bash
   systemextensionsctl list
   ```
   Should show "com.tavinathanson.AlwaysBlockApp.AlwaysBlockExtension" as "activated enabled"

2. Check the JSON file exists and has domains:
   ```bash
   cat /tmp/alwaysblock_domains.json
   ```

3. Force refresh by running any CLI command:
   ```bash
   alwaysblock status
   ```

4. Check Console.app logs:
   - Open Console.app
   - Filter by "AlwaysBlock"
   - Look for "🚀 Filter started with X blocked domains" (should be > 0)
   - Try visiting a blocked site and look for "🚫 BLOCKING flow to: domain.com"

5. Test in Safari first (works more reliably than Chrome)

### Chrome-specific issues?

Chrome uses modern networking protocols that can bypass content filters:

1. **Disable QUIC** (HTTP/3 over UDP):
   - Visit `chrome://flags/#enable-quic`
   - Set to "Disabled"
   - Restart Chrome

2. **Ensure all subdomains are listed** in your config:
   ```yaml
   reddit:
     domains:
       - reddit.com
       - www.reddit.com
       - redditstatic.com  # Required for CSS/JS
       - redd.it           # Required for images
   ```

3. **Check SNI extraction is working** in Console.app:
   - Look for "Blocking flow to SNI: domain.com" messages
   - If missing, Chrome might be using direct IP connections

### Build errors in Xcode?

- Ensure both targets have the same signing settings
- Check that entitlements files exist in both target folders
- Clean build folder (Shift+Cmd+K) and rebuild

### Can't disable SIP?

- Make sure you're in Recovery Mode
- On newer Macs, you may need to authenticate multiple times
- Alternative: Use a Developer ID certificate (requires paid Apple Developer account)

## What We Learned

### Network Extension Journey

This project went through several iterations to achieve reliable blocking:

1. **Initial Attempt: DNS Manipulation** ❌
   - Used `/etc/hosts` and DNS servers
   - Failed: Chrome uses DNS-over-HTTPS (DoH), bypassing local DNS

2. **Second Attempt: macOS Network Extensions** ⚠️
   - Implemented `NEFilterDataProvider` for content filtering
   - Works perfectly for Safari and system-respecting apps
   - Partial success for Chrome - requires SNI extraction

3. **Key Technical Challenges:**
   - **No hostname for Chrome**: Chrome makes direct IP connections without providing `remoteHostname`
   - **SNI extraction required**: Had to parse TLS ClientHello packets to extract Server Name Indication
   - **Subdomain explosion**: Must list all subdomains (e.g., `reddit.com`, `redditstatic.com`, `redd.it`) for complete blocking
   - **App Groups vs `/tmp`**: App Groups need paid developer cert, so using `/tmp` for local development

4. **What Actually Works:**
   - ✅ Safari: 100% blocking via `NEFilterDataProvider`
   - ❌ Chrome: SNI extraction works technically, but `.drop()` at packet level doesn't kill connections
   - 🔧 Future: PF (Packet Filter), transparent proxy, or hosts file for connection-level blocking

5. **The Packet vs Connection Problem:**
   - Network Extension can inspect packets and return `.drop()`
   - But by the time we extract SNI from TLS ClientHello, TCP connection is already established
   - Dropping packets ≠ killing connection
   - Chrome detects dropped packets and retries → eventually succeeds
   - This is why sites "block for 1 second then load" in Chrome
   - Safari works because it provides `remoteHostname` BEFORE connection is established, allowing blocking at flow creation time

### Code Highlights

**SNI Extraction** (`FilterDataProvider.swift:109-181`):
When Chrome doesn't provide a hostname, we:
1. Return `.filterDataVerdict()` to peek at outbound data
2. Parse the TLS ClientHello packet (starts with `0x16 0x03`)
3. Extract the SNI hostname from extension type `0x0000`
4. Block based on the extracted hostname

**Shared Data** (`/tmp/alwaysblock_domains.json`):
The CLI writes blocked domains as JSON, the Network Extension watches and reloads every second.

## Development

### Project Structure

```
alwaysblock/
├── AlwaysBlockApp/                 # Xcode project
│   ├── AlwaysBlockApp/            # Container app
│   └── AlwaysBlockExtension/      # Network Extension
├── alwaysblock_direct.py          # CLI implementation  
├── config_manager.py              # Configuration handling
├── db.py                          # SQLite database
└── config.yaml.example            # Example configuration
```

### Making Changes

1. **CLI changes**: Edit `alwaysblock_direct.py` and test immediately
2. **Blocking logic**: Edit `FilterDataProvider.swift` and rebuild in Xcode
3. **Configuration**: Update `config.yaml.example` with new options

### Re-enabling SIP

When done with development:
1. Boot into Recovery Mode
2. Run: `csrutil enable`
3. Restart

For production deployment, you'll need:
- Apple Developer account
- Proper code signing with Developer ID
- Notarization for distribution

## Uninstalling

1. Remove the system extension:
   ```bash
   systemextensionsctl uninstall - com.tavinathanson.AlwaysBlockApp.AlwaysBlockExtension
   ```

2. Remove the app:
   ```bash
   rm -rf /Applications/AlwaysBlock.app
   ```

3. Remove CLI and config:
   ```bash
   sudo rm /usr/local/bin/alwaysblock
   rm -rf ~/.config/alwaysblock
   rm -rf ~/.local/share/alwaysblock
   rm -rf ~/.alwaysblock-venv
   ```

4. Re-enable SIP if you disabled it

## License

MIT License - See LICENSE file for details

## Credits

Built as a complete rewrite of [taviblock](https://github.com/tavinathanson/taviblock) using modern macOS Network Extensions instead of DNS manipulation.