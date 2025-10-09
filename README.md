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

```bash
git clone https://github.com/yourusername/alwaysblock.git
cd alwaysblock
sudo ./install.sh
```

This will:
- Check Python 3.8+ is installed
- Create a virtual environment at `~/.alwaysblock-venv` (owned by your user)
- Install dependencies (dnslib, pyyaml)
- Create config at `~/.config/alwaysblock/config.yaml` (owned by your user)
- Install commands to `/usr/local/bin`:
  - `alwaysblock` - CLI for managing blocks
  - `alwaysblockd` - The daemon (usually run as service)
  - `alwaysblock-dns` - DNS configuration helper
  - `alwaysblock-service` - Service management

## Setup

After installation:

1. **Install as service** (recommended):
   ```bash
   sudo alwaysblock-service install
   ```
   This runs alwaysblock as a macOS service that starts automatically.

2. **Configure DNS**:
   ```bash
   alwaysblock-dns enable
   ```

3. **Edit config** to add domains:
   ```bash
   nano ~/.config/alwaysblock/config.yaml
   ```

Verify with `alwaysblock status`

## Configuration

`~/.config/alwaysblock/config.yaml` controls what domains are blocked and how unblocking works.

### Basic Example

```yaml
default_profile: standard

domains:
  netflix.com:
    tags: [entertainment]
  reddit.com:
    tags: [social]
  
  # Domain group
  google:
    domains:
      - google.com
      - gmail.com
    tags: [work]

profiles:
  standard:
    wait:
      base: 5      # Wait 5 minutes before unblocking
    duration: 30   # Stay unblocked for 30 minutes
  
  quick:
    wait: 0
    duration: 5
    cooldown: 30   # Can only use once per 30 minutes
```

See `config.yaml.example` for all features (tag rules, profile scopes, etc).

## Daily Usage

```bash
alwaysblock status                    # What's blocked?
alwaysblock unblock netflix           # Unblock for 30 min (with 5 min wait)
alwaysblock quick unblock reddit      # Quick 5 min unblock
alwaysblock block-all                 # Block everything NOW
```

**Network Switching**: When you switch networks (WiFi↔Ethernet), DNS settings don't carry over. Run `alwaysblock-dns enable` to reactivate blocking on the new interface.

## Management

### Service Commands
```bash
sudo alwaysblock-service install   # Install as service
sudo alwaysblock-service status    # Check status
sudo alwaysblock-service restart   # Restart
sudo alwaysblock-service logs      # View logs
sudo alwaysblock-service uninstall # Remove service
```

### Updates
```bash
cd alwaysblock && git pull && sudo ./install.sh
```
The installer automatically handles service restarts.

### Config Changes
Edit `~/.config/alwaysblock/config.yaml` - changes apply on next unblock.


## Troubleshooting

- **DNS not working?** Run `alwaysblock-dns status` to see which interfaces are configured
- **Switched networks?** Run `alwaysblock-dns enable` to set DNS on new interface
- **Service issues?** Check logs: `sudo alwaysblock-service logs`
- **Port already in use?** Stop any manual daemon: `sudo killall -9 alwaysblockd`
- **Want to disable?** Run `alwaysblock-dns disable` to restore original DNS

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