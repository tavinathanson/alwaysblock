#!/bin/bash
# AlwaysBlock daemon script
# Runs at boot to start proxy and enable system proxy
# This script is called by LaunchDaemon (runs as root)

set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
VENV_PATH="$HOME/.alwaysblock-venv"

# Log function
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

log "AlwaysBlock daemon starting..."

# Wait a bit for network to be ready
sleep 5

# Start the proxy daemon
log "Starting proxy daemon..."
if ! "$VENV_PATH/bin/python3" "$SCRIPT_DIR/alwaysblock.py" start-proxy 2>&1; then
    log "Failed to start proxy daemon"
    exit 1
fi

# Enable system proxy
log "Enabling system proxy..."
if ! "$VENV_PATH/bin/python3" "$SCRIPT_DIR/alwaysblock.py" enable-proxy 2>&1; then
    log "Failed to enable system proxy"
    exit 1
fi

log "AlwaysBlock daemon started successfully"

# Keep running (LaunchDaemon will restart us if we exit)
# We don't actually need to stay running, but KeepAlive will restart us if services stop
while true; do
    sleep 60

    # Health check: ensure proxy is still running
    if ! lsof -i :8905 >/dev/null 2>&1; then
        log "Proxy daemon stopped, restarting..."
        "$VENV_PATH/bin/python3" "$SCRIPT_DIR/alwaysblock.py" start-proxy 2>&1
    fi

    # Health check: ensure system proxy is still enabled
    if ! networksetup -getwebproxy "Wi-Fi" 2>/dev/null | grep -q "127.0.0.1"; then
        # Try other common service names
        for service in "Ethernet" "USB 10/100/1000 LAN" "Thunderbolt Ethernet"; do
            if networksetup -listallnetworkservices 2>/dev/null | grep -q "$service"; then
                if ! networksetup -getwebproxy "$service" 2>/dev/null | grep -q "127.0.0.1"; then
                    log "System proxy disabled on $service, re-enabling..."
                    "$VENV_PATH/bin/python3" "$SCRIPT_DIR/alwaysblock.py" enable-proxy 2>&1
                    break
                fi
            fi
        done
    fi
done
