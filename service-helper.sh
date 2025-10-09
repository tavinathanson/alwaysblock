#!/bin/bash

# Service helper for alwaysblock
set -e

# Colors
if [ -t 1 ]; then
    GREEN='\033[0;32m'
    YELLOW='\033[1;33m'
    RED='\033[0;31m'
    NC='\033[0m'
else
    GREEN=''
    YELLOW=''
    RED=''
    NC=''
fi

print_usage() {
    echo "Usage: $0 [install|uninstall|start|stop|restart|status|logs]"
    echo "  install   - Install launchd service"
    echo "  uninstall - Remove launchd service"
    echo "  start     - Start the service"
    echo "  stop      - Stop the service"
    echo "  restart   - Restart the service"
    echo "  status    - Show service status"
    echo "  logs      - Show recent logs"
    exit 1
}

PLIST_NAME="com.alwaysblock.daemon"
PLIST_PATH="/Library/LaunchDaemons/$PLIST_NAME.plist"

# Get actual user info
ACTUAL_USER=${SUDO_USER:-$USER}
ACTUAL_HOME=$(eval echo ~$ACTUAL_USER)
CONFIG_PATH="$ACTUAL_HOME/.config/alwaysblock/config.yaml"

case "${1:-}" in
    install)
        if [ -f "$PLIST_PATH" ]; then
            echo -e "${YELLOW}Service already installed${NC}"
            exit 0
        fi
        
        echo "Installing alwaysblock service..."
        
        # Create plist file
        sudo tee "$PLIST_PATH" > /dev/null << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$PLIST_NAME</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/local/bin/alwaysblockd</string>
        <string>--config</string>
        <string>$CONFIG_PATH</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <dict>
        <key>SuccessfulExit</key>
        <false/>
    </dict>
    <key>StandardOutPath</key>
    <string>/var/log/alwaysblock.log</string>
    <key>StandardErrorPath</key>
    <string>/var/log/alwaysblock.error.log</string>
    <key>WorkingDirectory</key>
    <string>$ACTUAL_HOME</string>
    <key>UserName</key>
    <string>root</string>
</dict>
</plist>
EOF
        
        sudo chmod 644 "$PLIST_PATH"
        sudo launchctl load "$PLIST_PATH" 2>&1
        
        # Check if actually started
        sleep 1
        if sudo launchctl list | grep -q "$PLIST_NAME"; then
            echo -e "${GREEN}✓ Service installed and started${NC}"
        else
            echo -e "${GREEN}✓ Service installed${NC}"
            echo -e "${YELLOW}Note: Service may not have started. Check logs:${NC}"
        fi
        echo "Logs: /var/log/alwaysblock.log"
        ;;
        
    uninstall)
        if [ ! -f "$PLIST_PATH" ]; then
            echo "Service not installed"
            exit 0
        fi
        
        echo "Uninstalling alwaysblock service..."
        sudo launchctl unload "$PLIST_PATH" 2>/dev/null || true
        sudo rm "$PLIST_PATH"
        echo -e "${GREEN}✓ Service uninstalled${NC}"
        ;;
        
    start)
        sudo launchctl load "$PLIST_PATH" 2>/dev/null || echo "Service already running"
        echo -e "${GREEN}✓ Service started${NC}"
        ;;
        
    stop)
        sudo launchctl unload "$PLIST_PATH" 2>/dev/null || echo "Service not running"
        echo -e "${GREEN}✓ Service stopped${NC}"
        ;;
        
    restart)
        echo "Restarting service..."
        sudo launchctl unload "$PLIST_PATH" 2>/dev/null || true
        sleep 1
        sudo launchctl load "$PLIST_PATH"
        echo -e "${GREEN}✓ Service restarted${NC}"
        ;;
        
    status)
        if sudo launchctl list | grep -q "$PLIST_NAME"; then
            echo -e "${GREEN}✓ Service is running${NC}"
            sudo launchctl list | grep "$PLIST_NAME"
        else
            echo -e "${RED}✗ Service is not running${NC}"
        fi
        ;;
        
    logs)
        echo "Recent logs:"
        echo "=========="
        if [ -f "/var/log/alwaysblock.log" ]; then
            tail -n 20 /var/log/alwaysblock.log
        else
            echo "No logs yet"
        fi
        
        if [ -f "/var/log/alwaysblock.error.log" ]; then
            echo
            echo "Recent errors:"
            echo "============="
            tail -n 10 /var/log/alwaysblock.error.log
        fi
        ;;
        
    *)
        print_usage
        ;;
esac