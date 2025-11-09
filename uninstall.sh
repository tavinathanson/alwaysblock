#!/bin/bash
# Uninstall script for AlwaysBlock

echo "AlwaysBlock Uninstall"
echo "===================="
echo ""

# Unload and remove LaunchDaemon if it exists
PLIST_PATH="/Library/LaunchDaemons/com.alwaysblock.daemon.plist"
if [ -f "$PLIST_PATH" ]; then
    echo "Removing auto-start LaunchDaemon..."
    sudo launchctl unload "$PLIST_PATH" 2>/dev/null || true
    sudo rm -f "$PLIST_PATH"
fi

# Remove daemon script
if [ -f "/usr/local/bin/alwaysblock-daemon" ]; then
    sudo rm -f /usr/local/bin/alwaysblock-daemon
fi

# Remove passwordless sudo configuration
SUDOERS_FILE="/etc/sudoers.d/alwaysblock"
if [ -f "$SUDOERS_FILE" ]; then
    echo "Removing passwordless sudo configuration..."
    sudo rm -f "$SUDOERS_FILE"
fi

# Stop proxy if running
if command -v alwaysblock &> /dev/null; then
    echo "Stopping proxy daemon..."
    sudo alwaysblock stop-proxy 2>/dev/null || true

    echo "Disabling system proxy..."
    sudo alwaysblock disable-proxy 2>/dev/null || true
fi

# Kill any processes on port 8905
PIDS=$(lsof -ti :8905 2>/dev/null || true)
if [ ! -z "$PIDS" ]; then
    echo "Killing proxy processes..."
    sudo kill -9 $PIDS 2>/dev/null || true
fi

# Remove CLI
if [ -f "/usr/local/bin/alwaysblock" ]; then
    echo "Removing CLI..."
    sudo rm -f /usr/local/bin/alwaysblock
fi

# Remove PF rules
if [ -f "/etc/pf.anchors/com.alwaysblock" ]; then
    echo "Removing PF rules..."
    sudo rm -f /etc/pf.anchors/com.alwaysblock
fi

if [ -f "/etc/pf.conf" ]; then
    if grep -q "com.alwaysblock" /etc/pf.conf; then
        echo "Cleaning PF configuration..."
        sudo sed -i.backup '/com.alwaysblock/d' /etc/pf.conf
        sudo sed -i.backup '/AlwaysBlock/d' /etc/pf.conf
        sudo pfctl -f /etc/pf.conf 2>/dev/null || true
    fi
fi

# Remove old Network Extension if exists
if [ -d "/Applications/AlwaysBlock.app" ]; then
    echo "Removing Network Extension app..."
    rm -rf "/Applications/AlwaysBlock.app"
fi

# Prompt for data removal
echo ""
read -p "Remove configuration and data? [y/N] " -n 1 -r
echo ""
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "Removing configuration and data..."
    rm -rf ~/.config/alwaysblock
    rm -rf ~/.local/share/alwaysblock
    rm -rf ~/.alwaysblock-venv
    echo "Configuration and data removed."
else
    echo "Keeping configuration and data:"
    echo "  Config: ~/.config/alwaysblock"
    echo "  Data:   ~/.local/share/alwaysblock"
    echo "  Venv:   ~/.alwaysblock-venv"
    echo ""
    echo "To remove manually: rm -rf ~/.config/alwaysblock ~/.local/share/alwaysblock ~/.alwaysblock-venv"
fi

echo ""
echo "✅ AlwaysBlock uninstalled successfully!"
echo ""
