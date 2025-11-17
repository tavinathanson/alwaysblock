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

    echo "Stopping existing services..."
    sudo alwaysblock stop 2>/dev/null || true
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

# Copy example config if needed (preserve existing config)
# If config is a symlink (old behavior), convert it to a real file
if [ -L "$CONFIG_DIR/config.yaml" ]; then
    echo "Converting symlinked config to standalone file..."
    TEMP_CONFIG=$(mktemp)
    cp -L "$CONFIG_DIR/config.yaml" "$TEMP_CONFIG"
    rm "$CONFIG_DIR/config.yaml"
    mv "$TEMP_CONFIG" "$CONFIG_DIR/config.yaml"
    echo "Config is now a standalone file (no longer a symlink)"
elif [ ! -e "$CONFIG_DIR/config.yaml" ]; then
    if [ -f "$SCRIPT_DIR/config.yaml.example" ]; then
        echo "Creating default configuration..."
        cp "$SCRIPT_DIR/config.yaml.example" "$CONFIG_DIR/config.yaml"
        echo "Config copied from: $SCRIPT_DIR/config.yaml.example"
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

# Ask about passwordless sudo
echo ""
echo "Do you want to enable passwordless sudo for AlwaysBlock commands?"
echo "(Allows commands like 'sudo alwaysblock start' without password)"
read -p "Enable passwordless sudo? [y/N]: " -r PASSWORDLESS_RESPONSE

if [[ "$PASSWORDLESS_RESPONSE" =~ ^[Yy]$ ]]; then
    echo ""
    echo "Setting up passwordless sudo..."

    # Create sudoers file with username substitution
    SUDOERS_FILE="/etc/sudoers.d/alwaysblock"
    CURRENT_USER=$(whoami)

    # Create temporary file with username replaced
    TEMP_SUDOERS=$(mktemp)
    sed "s/USERNAME/$CURRENT_USER/g" "$SCRIPT_DIR/com.alwaysblock.sudoers" > "$TEMP_SUDOERS"

    # Validate the sudoers file before installing
    if sudo visudo -cf "$TEMP_SUDOERS"; then
        sudo cp "$TEMP_SUDOERS" "$SUDOERS_FILE"
        sudo chmod 440 "$SUDOERS_FILE"
        echo "✅ Passwordless sudo configured!"
    else
        echo "❌ Error: sudoers file validation failed"
        rm -f "$TEMP_SUDOERS"
    fi
    rm -f "$TEMP_SUDOERS"
    echo ""
fi

# Ask about auto-start on boot
echo ""
echo "Do you want AlwaysBlock to start automatically on boot?"
echo "(Services will start when your Mac restarts)"
read -p "Enable auto-start on boot? [y/N]: " -r AUTOSTART_RESPONSE

if [[ "$AUTOSTART_RESPONSE" =~ ^[Yy]$ ]]; then
    echo ""
    echo "Setting up auto-start on boot..."

    # Create daemon script with proper venv path substitution
    DAEMON_SCRIPT="/usr/local/bin/alwaysblock-daemon"
    TEMP_DAEMON=$(mktemp)

    # Substitute __VENV_PATH__ with actual venv path
    sed "s|__VENV_PATH__|$VENV_PATH|g" "$SCRIPT_DIR/alwaysblock-daemon.sh" > "$TEMP_DAEMON"

    sudo cp "$TEMP_DAEMON" "$DAEMON_SCRIPT"
    sudo chmod +x "$DAEMON_SCRIPT"
    rm -f "$TEMP_DAEMON"

    # Install LaunchDaemon plist
    PLIST_PATH="/Library/LaunchDaemons/com.alwaysblock.daemon.plist"
    sudo cp "$SCRIPT_DIR/com.alwaysblock.daemon.plist" "$PLIST_PATH"
    sudo chown root:wheel "$PLIST_PATH"
    sudo chmod 644 "$PLIST_PATH"

    # Load the LaunchDaemon
    sudo launchctl load "$PLIST_PATH" 2>/dev/null || true

    echo "✅ Auto-start configured!"
    echo ""
    echo "Waiting for services to start..."

    # Wait for daemon to start services (max 10 seconds)
    for i in {1..10}; do
        sleep 1
        if lsof -i :8905 >/dev/null 2>&1; then
            break
        fi
    done
else
    # Manual start
    # Restart services if they were running
    if [ "$PROXY_WAS_RUNNING" = true ] || [ "$SYSPROXY_WAS_ENABLED" = true ]; then
        echo "Restarting services..."
        sudo alwaysblock start
    fi

    # Show status if services were restarted
    if [ "$PROXY_WAS_RUNNING" = true ] || [ "$SYSPROXY_WAS_ENABLED" = true ]; then
        echo ""
        alwaysblock status
        echo ""
    else
        # First time install - show setup instructions
        echo "Setup (run these commands):"
        echo "  1. sudo alwaysblock start    # Start all services"
        echo "  2. alwaysblock status        # Verify everything is running"
        echo ""
    fi
fi

echo ""
echo "✅ Installation complete!"
echo ""
alwaysblock status
echo ""
echo "Quick start:"
echo "  alwaysblock unblock reddit   # Temporarily unblock a site"
echo "  alwaysblock block-all        # Block everything immediately"
echo ""
echo "Config: $CONFIG_DIR/config.yaml"
echo "Docs:   $SCRIPT_DIR/README.md"
echo ""
