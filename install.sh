#!/bin/bash

# alwaysblock installer
set -e

# Check if running with sudo
if [ "$EUID" -ne 0 ]; then 
    echo "This installer requires sudo access to install commands to /usr/local/bin"
    echo "Please run: sudo ./install.sh"
    exit 1
fi

# Colors (disable if not in terminal)
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

# Paths (use SUDO_USER's home if running with sudo)
REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
if [ -n "$SUDO_USER" ]; then
    USER_HOME=$(eval echo ~$SUDO_USER)
else
    USER_HOME=$HOME
fi
VENV_DIR="$USER_HOME/.alwaysblock-venv"
CONFIG_DIR="$USER_HOME/.config/alwaysblock"
CONFIG_FILE="$CONFIG_DIR/config.yaml"

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
    exit 1
}

print_success() {
    echo -e "${GREEN}[✓]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[!]${NC} $1"
}

# Check Python version
check_python() {
    if ! command -v python3 &> /dev/null; then
        print_error "Python 3 not found. Install Python 3.8+"
    fi
    
    PYTHON_VERSION=$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
    if [ "$(printf '%s\n' "3.8" "$PYTHON_VERSION" | sort -V | head -n1)" != "3.8" ]; then
        print_error "Python 3.8+ required (found $PYTHON_VERSION)"
    fi
    
    print_success "Python $PYTHON_VERSION"
}

# Create and setup venv
setup_venv() {
    if [ -d "$VENV_DIR" ]; then
        print_warning "Removing existing venv at $VENV_DIR"
        rm -rf "$VENV_DIR"
    fi
    
    # Create venv as the actual user if running with sudo
    if [ -n "$SUDO_USER" ]; then
        sudo -u "$SUDO_USER" python3 -m venv "$VENV_DIR"
    else
        python3 -m venv "$VENV_DIR"
    fi
    print_success "Created venv at $VENV_DIR"
    
    # Install dependencies as the actual user
    if [ -n "$SUDO_USER" ]; then
        sudo -u "$SUDO_USER" "$VENV_DIR/bin/pip" install --upgrade pip &>/dev/null
        sudo -u "$SUDO_USER" "$VENV_DIR/bin/pip" install -r "$REPO_DIR/requirements.txt"
    else
        source "$VENV_DIR/bin/activate"
        pip install --upgrade pip &>/dev/null
        pip install -r "$REPO_DIR/requirements.txt"
        deactivate
    fi
    
    print_success "Installed dependencies"
}

# Setup config
setup_config() {
    # Create config dir as the actual user if running with sudo
    if [ -n "$SUDO_USER" ]; then
        sudo -u "$SUDO_USER" mkdir -p "$CONFIG_DIR"
    else
        mkdir -p "$CONFIG_DIR"
    fi
    
    if [ -f "$CONFIG_FILE" ]; then
        print_warning "Config exists at $CONFIG_FILE (keeping it)"
    else
        # Create minimal config
        cat > "$CONFIG_FILE" << 'EOF'
# alwaysblock configuration
default_profile: standard

domains:
  # Add domains you want to block
  example.com:
    tags: [distracting]

profiles:
  standard:
    wait:
      base: 5
    duration: 30
  
  quick:
    wait: 0
    duration: 5
    cooldown: 30
EOF
        print_success "Created config at $CONFIG_FILE"
        print_warning "Edit $CONFIG_FILE to add domains to block"
    fi
}

# Install executables
install_executables() {
    # CLI wrapper
    cat > /tmp/alwaysblock << EOF
#!/bin/bash
source "$VENV_DIR/bin/activate"
exec python3 "$REPO_DIR/alwaysblock" "\$@"
EOF
    
    # Daemon wrapper  
    cat > /tmp/alwaysblockd << EOF
#!/bin/bash
source "$VENV_DIR/bin/activate"
exec python3 "$REPO_DIR/alwaysblockd.py" "\$@"
EOF
    
    mkdir -p /usr/local/bin
    cp /tmp/alwaysblock /usr/local/bin/
    cp /tmp/alwaysblockd /usr/local/bin/
    cp "$REPO_DIR/dns-helper.sh" /usr/local/bin/alwaysblock-dns
    cp "$REPO_DIR/service-helper.sh" /usr/local/bin/alwaysblock-service
    chmod +x /usr/local/bin/alwaysblock
    chmod +x /usr/local/bin/alwaysblockd
    chmod +x /usr/local/bin/alwaysblock-dns
    chmod +x /usr/local/bin/alwaysblock-service
    
    rm /tmp/alwaysblock /tmp/alwaysblockd
    print_success "Installed commands to /usr/local/bin"
}

# Main
echo -e "${GREEN}Installing alwaysblock${NC}"
echo

check_python

# Check if daemon is running (either manually or as service)
DAEMON_WAS_RUNNING=false
SERVICE_WAS_RUNNING=false

# Check for service
if sudo launchctl list | grep -q "com.alwaysblock.daemon"; then
    SERVICE_WAS_RUNNING=true
    print_warning "Stopping alwaysblock service..."
    sudo launchctl unload /Library/LaunchDaemons/com.alwaysblock.daemon.plist 2>/dev/null || true
    sleep 2
fi

# Check for manual daemon
if pgrep -f alwaysblockd > /dev/null; then
    DAEMON_WAS_RUNNING=true
    print_warning "Stopping existing daemon..."
    sudo killall alwaysblockd 2>/dev/null || true
    sleep 2
    
    if pgrep -f alwaysblockd > /dev/null; then
        print_warning "Daemon still running, forcing kill..."
        sudo killall -9 alwaysblockd 2>/dev/null || true
        sleep 1
    fi
fi

setup_venv
setup_config
install_executables

echo
echo -e "${GREEN}Installation complete!${NC}"
echo

# Restart service if it was running
if [ "$SERVICE_WAS_RUNNING" = true ]; then
    print_warning "Restarting service..."
    sudo launchctl load /Library/LaunchDaemons/com.alwaysblock.daemon.plist
    print_success "Service restarted"
elif [ "$DAEMON_WAS_RUNNING" = true ]; then
    echo
    echo "The daemon was stopped for the update."
    echo -e "To restart it, run: ${YELLOW}sudo alwaysblockd${NC}"
fi

echo
echo "Next steps:"
echo -e "1. ${GREEN}RECOMMENDED:${NC} Install as service: ${YELLOW}sudo alwaysblock-service install${NC}"
echo "   (starts automatically, restarts on crash, manages logs)"
echo
echo -e "   OR manually start: ${YELLOW}sudo alwaysblockd${NC}"
echo
echo -e "2. Configure DNS: ${YELLOW}alwaysblock-dns enable${NC}"
echo "3. Edit config: $CONFIG_FILE"
echo
echo "Commands:"
echo "  alwaysblock status              # Check what's blocked"
echo "  alwaysblock unblock [domain]    # Unblock a domain"
echo "  alwaysblock-dns status          # Check DNS settings"
echo "  alwaysblock-service status      # Check service status"