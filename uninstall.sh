#!/bin/bash

# alwaysblock uninstaller
set -e

# Colors
if [ -t 1 ]; then
    RED='\033[0;31m'
    GREEN='\033[0;32m'
    YELLOW='\033[1;33m'
    NC='\033[0m'
else
    RED=''
    GREEN=''
    YELLOW=''
    NC=''
fi

print_warning() {
    echo -e "${YELLOW}[!]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[✓]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if running with sudo
if [ "$EUID" -ne 0 ]; then 
    echo "This uninstaller requires sudo access"
    echo "Please run: sudo ./uninstall.sh"
    exit 1
fi

echo -e "${RED}Uninstalling alwaysblock${NC}"
echo "This will remove:"
echo "  - Service (if installed)"
echo "  - Commands from /usr/local/bin"
echo "  - Virtual environment"
echo "  - Database and runtime files"
echo "  - DNS settings (restore to original)"
echo
echo "Config file will be preserved at ~/.config/alwaysblock/"
echo

read -p "Continue with uninstall? [y/N] " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Uninstall cancelled"
    exit 0
fi

# Get user home directory
if [ -n "$SUDO_USER" ]; then
    USER_HOME=$(eval echo ~$SUDO_USER)
else
    USER_HOME=$HOME
fi

# 1. Stop and uninstall service
if [ -f "/Library/LaunchDaemons/com.alwaysblock.daemon.plist" ]; then
    print_warning "Stopping service..."
    launchctl unload /Library/LaunchDaemons/com.alwaysblock.daemon.plist 2>/dev/null || true
    rm -f /Library/LaunchDaemons/com.alwaysblock.daemon.plist
    print_success "Service removed"
fi

# 2. Kill any running daemons
if pgrep -f alwaysblockd > /dev/null; then
    print_warning "Stopping daemon..."
    killall -9 alwaysblockd 2>/dev/null || true
    sleep 1
fi

# 3. Restore DNS settings
if command -v alwaysblock-dns >/dev/null 2>&1; then
    print_warning "Restoring DNS settings..."
    alwaysblock-dns disable 2>/dev/null || true
    print_success "DNS restored"
fi

# 4. Remove commands
print_warning "Removing commands..."
rm -f /usr/local/bin/alwaysblock
rm -f /usr/local/bin/alwaysblockd
rm -f /usr/local/bin/alwaysblock-dns
rm -f /usr/local/bin/alwaysblock-service
print_success "Commands removed"

# 5. Remove virtual environment
if [ -d "$USER_HOME/.alwaysblock-venv" ]; then
    print_warning "Removing virtual environment..."
    rm -rf "$USER_HOME/.alwaysblock-venv"
    print_success "Virtual environment removed"
fi

# 6. Remove runtime files
print_warning "Removing runtime files..."
rm -f "$USER_HOME/.alwaysblock/control.sock"
rm -f "$USER_HOME/.alwaysblock/alwaysblock.db"
rm -f "$USER_HOME/.config/alwaysblock/.dns_backup_*"
rm -f /var/log/alwaysblock.log
rm -f /var/log/alwaysblock.error.log
print_success "Runtime files removed"

echo
echo -e "${GREEN}Uninstall complete!${NC}"
echo
echo "Preserved:"
echo "  - Config file: $USER_HOME/.config/alwaysblock/config.yaml"
echo "  - Source code: $(pwd)"
echo
echo "To completely remove everything:"
echo "  rm -rf $USER_HOME/.config/alwaysblock"
echo "  rm -rf $(pwd)"