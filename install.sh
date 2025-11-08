#!/bin/bash
# Installation script for AlwaysBlock
# Handles clean install, upgrade, and uninstall of any previous versions

set -e

echo "AlwaysBlock Installation"
echo "========================"
echo ""

# Check for Python 3
if ! command -v python3 &> /dev/null; then
    echo "Error: Python 3 is required but not installed"
    exit 1
fi

# Get the directory where this script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Configuration
VENV_PATH="$HOME/.alwaysblock-venv"
CONFIG_DIR="$HOME/.config/alwaysblock"
DATA_DIR="$HOME/.local/share/alwaysblock"
CLI_SCRIPT="/usr/local/bin/alwaysblock"

echo "Checking for existing installation..."

# Check if proxy was running and system proxy was enabled
PROXY_WAS_RUNNING=false
SYSPROXY_WAS_ENABLED=false

if command -v alwaysblock &> /dev/null; then
    # Check if proxy was running
    if lsof -i :8905 >/dev/null 2>&1; then
        PROXY_WAS_RUNNING=true
    fi

    # Check if system proxy was enabled
    if networksetup -getwebproxy "Wi-Fi" 2>/dev/null | grep -q "127.0.0.1"; then
        SYSPROXY_WAS_ENABLED=true
    fi

    echo "Stopping existing proxy..."
    sudo alwaysblock stop-proxy 2>/dev/null || true
fi

# Kill any processes on port 8905
echo "Cleaning up port 8905..."
PIDS=$(lsof -ti :8905 2>/dev/null || true)
if [ ! -z "$PIDS" ]; then
    echo "Killing existing processes: $PIDS"
    kill -9 $PIDS 2>/dev/null || true
fi

# Remove old CLI if exists
if [ -f "$CLI_SCRIPT" ]; then
    echo "Removing old CLI..."
    sudo rm -f "$CLI_SCRIPT"
fi

# Remove old Network Extension app if exists
if [ -d "/Applications/AlwaysBlock.app" ]; then
    echo "Removing old Network Extension app..."
    rm -rf "/Applications/AlwaysBlock.app"
fi

# Check for old system extensions
echo "Checking for old system extensions..."
if systemextensionsctl list 2>/dev/null | grep -q "AlwaysBlock"; then
    echo "Found old Network Extension - attempting removal..."
    echo "(This may show multiple entries from previous installations)"
    # Try to uninstall - may require reboot to fully remove
    systemextensionsctl uninstall - com.tavinathanson.AlwaysBlockApp.AlwaysBlockExtension 2>/dev/null || true
    echo "Note: Old extensions marked for removal. May require reboot to fully clean up."
fi

# Remove PF rules if they exist
echo "Cleaning up old PF rules..."
if [ -f "/etc/pf.anchors/com.alwaysblock" ]; then
    sudo rm -f "/etc/pf.anchors/com.alwaysblock"
fi

# Remove PF anchor from pf.conf if it exists
if [ -f "/etc/pf.conf" ]; then
    if grep -q "com.alwaysblock" /etc/pf.conf; then
        echo "Removing PF anchor from pf.conf..."
        sudo sed -i.backup '/com.alwaysblock/d' /etc/pf.conf
        sudo sed -i.backup '/AlwaysBlock/d' /etc/pf.conf
        sudo pfctl -f /etc/pf.conf 2>/dev/null || true
    fi
fi

echo ""
echo "Installing AlwaysBlock..."
echo ""

# Create virtual environment
if [ ! -d "$VENV_PATH" ]; then
    echo "Creating Python virtual environment..."
    python3 -m venv "$VENV_PATH"
else
    echo "Using existing virtual environment..."
fi

# Install/upgrade dependencies (disable proxy so pip can connect)
echo "Installing dependencies..."
NO_PROXY="*" "$VENV_PATH/bin/pip" install -q --upgrade pip
NO_PROXY="*" "$VENV_PATH/bin/pip" install -q PyYAML

# Create config directories with proper ownership
mkdir -p "$CONFIG_DIR"
mkdir -p "$DATA_DIR"

# Ensure data directory is owned by current user (not root)
# This prevents database permission issues when the proxy daemon creates it
chown -R "$(whoami):staff" "$DATA_DIR"

# Create symlink to example config if needed (preserve existing config)
if [ ! -e "$CONFIG_DIR/config.yaml" ]; then
    if [ -f "$SCRIPT_DIR/config.yaml.example" ]; then
        echo "Creating default configuration..."
        ln -sf "$SCRIPT_DIR/config.yaml.example" "$CONFIG_DIR/config.yaml"
        echo "Config symlinked to: $SCRIPT_DIR/config.yaml.example"
    fi
else
    echo "Preserving existing configuration..."
fi

# Install CLI script
echo "Installing CLI..."
sudo tee "$CLI_SCRIPT" > /dev/null <<EOF
#!/bin/bash
# AlwaysBlock CLI wrapper
exec ~/.alwaysblock-venv/bin/python3 "$SCRIPT_DIR/alwaysblock.py" "\$@"
EOF

sudo chmod +x "$CLI_SCRIPT"

# Initialize database with proper permissions (as current user)
echo "Initializing database..."
"$VENV_PATH/bin/python3" -c "
import sys
sys.path.insert(0, '$SCRIPT_DIR')
from db import Database
from pathlib import Path
db = Database(Path('$DATA_DIR/alwaysblock.db'))
print('Database initialized')
"

echo ""
echo "✅ Installation complete!"
echo ""

# Restart services if they were running
if [ "$PROXY_WAS_RUNNING" = true ] || [ "$SYSPROXY_WAS_ENABLED" = true ]; then
    echo "Restarting proxy daemon..."
    sudo alwaysblock start-proxy
fi

if [ "$SYSPROXY_WAS_ENABLED" = true ]; then
    echo "Re-enabling system proxy..."
    sudo alwaysblock enable-proxy
fi

# Show status if services were restarted
if [ "$PROXY_WAS_RUNNING" = true ] || [ "$SYSPROXY_WAS_ENABLED" = true ]; then
    echo ""
    alwaysblock status
    echo ""
else
    # First time install - show setup instructions
    echo "Setup (run these commands):"
    echo "  1. sudo alwaysblock start-proxy       # Start the proxy daemon"
    echo "  2. sudo alwaysblock enable-proxy      # Enable system proxy"
    echo "  3. alwaysblock status                 # Verify everything is running"
    echo ""
fi

echo "Usage:"
echo "  alwaysblock status                    # Show current status"
echo "  alwaysblock unblock reddit            # Temporarily unblock reddit"
echo "  alwaysblock block-all                 # Block everything immediately"
echo ""
echo "Files:"
echo "  Configuration: $CONFIG_DIR/config.yaml"
echo "  Proxy logs:    /tmp/proxy.log"
echo "  Documentation: $SCRIPT_DIR/README.md"
echo ""
