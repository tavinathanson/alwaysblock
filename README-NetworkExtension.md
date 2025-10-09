# AlwaysBlock Network Extension

This version uses macOS Network Extensions for more robust blocking that can't be bypassed.

## Prerequisites

1. **macOS 13+** (Ventura or later)
2. **Xcode** installed
3. **SIP disabled** and **developer mode enabled** (for development)

## Setup Instructions

### 1. Enable Developer Mode

Since you've already disabled SIP:

```bash
sudo systemextensionsctl developer on
```

### 2. Build the App in Xcode

1. Open `AlwaysBlockApp/AlwaysBlock.xcodeproj` in Xcode
2. Select the AlwaysBlock target
3. Under "Signing & Capabilities":
   - Choose "Sign to Run Locally" or select your team
   - Do the same for the AlwaysBlockExtension target
4. Build and run (Cmd+R)

### 3. Allow the Extension

When you first run the app:
1. You'll see a prompt to allow the extension
2. Click "Allow" 
3. If prompted, go to System Settings → Privacy & Security
4. Allow the blocked system software

### 4. Install the CLI

```bash
./install-ne.sh
```

## Usage

The CLI works exactly the same as before:

```bash
# Block a domain permanently
alwaysblock block reddit.com

# Block for 30 minutes
alwaysblock block twitter.com -d 30

# Check status
alwaysblock status

# Unblock a domain
alwaysblock unblock reddit.com

# Unblock everything
alwaysblock unblock-all
```

## How It Works

1. **Network Extension** intercepts all network connections at the system level
2. **JSON file** stores blocked domains in ~/Documents/alwaysblock_domains.json
3. **CLI** updates the JSON file
4. **Extension** monitors the file and blocks matching connections

## Advantages Over DNS Blocking

- **Can't be bypassed** - works at network packet level
- **Blocks immediately** - no DNS cache issues
- **Works everywhere** - even with hardcoded IPs or custom DNS
- **More reliable** - no conflicts with other DNS tools

## Troubleshooting

### Extension not blocking?

1. Check if it's running:
   ```bash
   systemextensionsctl list
   ```

2. View logs:
   ```bash
   log stream --subsystem com.tavinathanson.AlwaysBlockApp
   ```

3. Make sure the app is running (it needs to stay open)

### Re-enable SIP Later

When done developing:
1. Boot into Recovery Mode
2. Run `csrutil enable`
3. Restart

For production use, you'd need a Developer ID certificate from Apple.