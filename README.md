# alwaysblock

A clean, modern DNS-based domain blocker for macOS. Built as a complete rewrite of [taviblock](https://github.com/tavinathanson/taviblock), focusing on simplicity, performance, and reliability.

## Why alwaysblock?

Traditional domain blocking approaches have significant drawbacks:
- **`/etc/hosts` editing**: Slow DNS propagation, requires root, causes system monitoring overhead
- **Browser extensions**: Browser-specific, easily bypassed, don't affect native apps
- **Firewall-only blocking**: Can't handle CDNs/rotating IPs, long-lived connections survive

**alwaysblock** solves these problems with a DNS proxy approach:
- Instant blocking/unblocking (no DNS cache issues)
- Works system-wide for all applications
- Handles CDNs and rotating IPs naturally
- Integrates with PF to kill existing connections

## Features

- 🚫 **DNS-based blocking**: All domains blocked by default (resolve to 0.0.0.0)
- ⏱️ **Profile-based timing**: Configurable wait times, durations, and cooldowns
- 🏷️ **Tag system**: Group domains by category with tag-specific rules
- 🔄 **Session management**: Track active unblock sessions with automatic expiration
- 🌐 **Domain groups**: Define collections of related domains
- 🔧 **macOS PF integration**: Kills existing connections when domains are re-blocked
- 📊 **Concurrent penalties**: Discourage multiple simultaneous unblocks
- 🎯 **YAML configuration**: Human-readable config compatible with taviblock

## Installation

### Prerequisites

- macOS (required for PF integration)
- Python 3.8+
- pip

### Install

```bash
# Clone the repository
git clone https://github.com/yourusername/alwaysblock.git
cd alwaysblock

# Install dependencies
pip3 install -r requirements.txt

# Create config directory
mkdir -p ~/.config/alwaysblock

# Copy and edit configuration
cp config.yaml.example ~/.config/alwaysblock/config.yaml
```

## Quick Start

1. **Start the daemon:**
   ```bash
   # Run with default DNS port (requires sudo)
   sudo python3 alwaysblockd.py
   
   # Or use custom port (no sudo required, but needs DNS configuration)
   python3 alwaysblockd.py --port 5353
   ```

2. **Configure your Mac to use alwaysblock:**
   - System Preferences → Network → Advanced → DNS
   - Add `127.0.0.1` (if using port 53)
   - Or configure your DNS to forward to `127.0.0.1:5353`

3. **Use the CLI:**
   ```bash
   # Check status
   ./alwaysblock status
   
   # Unblock with default profile
   ./alwaysblock unblock netflix
   
   # Unblock with specific profile
   ./alwaysblock bypass unblock google
   
   # Block everything immediately
   ./alwaysblock block-all
   ```

## Configuration

### Basic Structure

```yaml
# Default profile when none specified
default_profile: unblock

# Domain definitions
domains:
  # Individual domain with tags
  netflix.com:
    tags: [entertainment, streaming]
  
  # Domain group
  google:
    domains:
      - google.com
      - gmail.com
      - calendar.google.com
      - docs.google.com
    tags: [work, productivity]

# Profile definitions
profiles:
  # Standard unblock with wait time
  unblock:
    description: "Standard unblock"
    wait:
      base: 5              # Base wait time in minutes
      concurrent_penalty: 5 # Extra minutes per concurrent session
    duration: 30           # How long domains stay unblocked
    
  # Emergency bypass
  bypass:
    description: "Emergency bypass - once per hour"
    wait: 0
    duration: 5
    cooldown: 60  # Can only use once per hour
```

### Advanced Features

#### Tag-based Rules

Override wait times for specific tags:

```yaml
profiles:
  unblock:
    wait:
      base: 5
    duration: 30
    tag_rules:
      - tags: [social, ultra_distracting]
        wait_override: 30  # 30 minute wait for social media
```

#### Profile Scopes

Profiles can target specific sets of domains:

```yaml
profiles:
  # Unblock everything
  unblock-all:
    all: true
    wait: 10
    duration: 60
    
  # Unblock only domains with specific tags
  work-only:
    tags: [work, productivity]
    wait: 0
    duration: 120
    
  # Unblock only specific domains
  email-only:
    only: [gmail, "mail.google.com"]
    wait: 0
    duration: 30
```

## CLI Usage

### Profile-based Commands

The CLI follows the pattern: `alwaysblock [profile] command [args]`

```bash
# Use default profile
./alwaysblock unblock netflix youtube

# Use specific profile
./alwaysblock bypass unblock reddit

# Quick access profile (if configured)
./alwaysblock quick
```

### Status and Management

```bash
# Show current status
./alwaysblock status

# Cancel active session
./alwaysblock cancel [session_id]

# Replace current session
./alwaysblock replace [profile] [domains...]

# Block all immediately
./alwaysblock block-all
```

## Architecture

- **`alwaysblockd.py`**: Main daemon with asyncio event loop
- **`dns_proxy.py`**: DNS interception using dnslib
- **`config_manager.py`**: YAML configuration and profile management
- **`db.py`**: SQLite session and cooldown tracking
- **`pf_manager.py`**: macOS PF state management
- **`cli_interface.py`**: Unix socket control interface
- **`alwaysblock`**: CLI client

## Running as a Service

### macOS (launchd)

Create `/Library/LaunchDaemons/com.alwaysblock.daemon.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" 
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.alwaysblock.daemon</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/local/bin/python3</string>
        <string>/path/to/alwaysblockd.py</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/var/log/alwaysblock.log</string>
    <key>StandardErrorPath</key>
    <string>/var/log/alwaysblock.error.log</string>
</dict>
</plist>
```

Load with: `sudo launchctl load /Library/LaunchDaemons/com.alwaysblock.daemon.plist`

## Development

### Running Tests

```bash
# Basic functionality test
python3 test_alwaysblock.py

# DNS resolution test
dig @127.0.0.1 -p 5353 google.com
```

### Debug Mode

```bash
# Run with verbose logging
python3 alwaysblockd.py --verbose
```

## Troubleshooting

### DNS not working?
- Check if the daemon is running: `./alwaysblock status`
- Verify DNS configuration: `scutil --dns | grep nameserver`
- Test resolution: `dig @127.0.0.1 google.com`

### Sessions not activating?
- Check database: `sqlite3 ~/.alwaysblock/alwaysblock.db "SELECT * FROM sessions;"`
- Check logs for errors
- Verify system time is correct

### PF states not flushing?
- Run with sudo for PF access
- Check PF is enabled: `sudo pfctl -s info`

## License

MIT License - see LICENSE file

## Contributing

Pull requests welcome! Please:
- Keep the codebase minimal and clean
- Add tests for new features
- Update documentation
- Follow existing code style

## Credits

Built as a clean rewrite of [taviblock](https://github.com/tavinathanson/taviblock) by Tavi Nathanson.