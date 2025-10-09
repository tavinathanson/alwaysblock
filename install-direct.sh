#!/bin/bash
# AlwaysBlock Direct (daemon-free) installer
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

echo "AlwaysBlock Direct Installer"
echo "============================"
echo ""

# Check Python version
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}Error: Python 3 is not installed${NC}"
    exit 1
fi

PYTHON_VERSION=$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
REQUIRED_VERSION="3.8"

if [ "$(printf '%s\n' "$REQUIRED_VERSION" "$PYTHON_VERSION" | sort -V | head -n1)" != "$REQUIRED_VERSION" ]; then
    echo -e "${RED}Error: Python $REQUIRED_VERSION or higher is required (found $PYTHON_VERSION)${NC}"
    exit 1
fi

# Create venv if it doesn't exist
VENV_DIR="$HOME/.alwaysblock-venv"
if [ ! -d "$VENV_DIR" ]; then
    echo "Creating virtual environment at $VENV_DIR..."
    python3 -m venv "$VENV_DIR"
    echo -e "${GREEN}✓ Virtual environment created${NC}"
else
    echo -e "${GREEN}✓ Using existing virtual environment${NC}"
fi

# Activate venv and install dependencies
echo "Installing Python dependencies..."
source "$VENV_DIR/bin/activate"
pip install --quiet --upgrade pip
pip install --quiet pyyaml

# Get the absolute path to this repo
REPO_DIR="$(cd "$(dirname "$0")" && pwd)"

# Create wrapper script that uses venv
echo "Installing alwaysblock command..."
cat > /tmp/alwaysblock << EOF
#!/bin/bash
# AlwaysBlock CLI wrapper
VENV_DIR="\$HOME/.alwaysblock-venv"
ALWAYSBLOCK_SCRIPT="$REPO_DIR/alwaysblock_direct.py"

# Check if venv exists
if [ ! -f "\$VENV_DIR/bin/python" ]; then
    echo "Error: Virtual environment not found at \$VENV_DIR"
    echo "Please run the installer again"
    exit 1
fi

# Run with venv
exec "\$VENV_DIR/bin/python" "\$ALWAYSBLOCK_SCRIPT" "\$@"
EOF

# Install to /usr/local/bin (requires sudo)
if [ -w /usr/local/bin ]; then
    mv /tmp/alwaysblock /usr/local/bin/alwaysblock
    chmod +x /usr/local/bin/alwaysblock
else
    echo -e "${YELLOW}Need sudo to install to /usr/local/bin${NC}"
    sudo mv /tmp/alwaysblock /usr/local/bin/alwaysblock
    sudo chmod +x /usr/local/bin/alwaysblock
fi
echo -e "${GREEN}✓ CLI installed${NC}"

# Create config directory and copy example config
CONFIG_DIR="$HOME/.config/alwaysblock"
mkdir -p "$CONFIG_DIR"

if [ ! -f "$CONFIG_DIR/config.yaml" ]; then
    if [ -f "config.yaml.example" ]; then
        cp config.yaml.example "$CONFIG_DIR/config.yaml"
        echo -e "${GREEN}✓ Created config file at $CONFIG_DIR/config.yaml${NC}"
        echo -e "${YELLOW}  Please edit it to add your domains${NC}"
    fi
fi

# Create data directory
DATA_DIR="$HOME/.local/share/alwaysblock"
mkdir -p "$DATA_DIR"
echo -e "${GREEN}✓ Created data directory${NC}"

# Check if Network Extension is running
if systemextensionsctl list 2>/dev/null | grep -q "com.tavinathanson.AlwaysBlockApp.AlwaysBlockExtension.*activated.*enabled"; then
    echo -e "${GREEN}✓ Network Extension is active${NC}"
else
    echo -e "${YELLOW}! Network Extension not detected${NC}"
    echo "  Please run the AlwaysBlock app to install the extension"
fi

echo ""
echo -e "${GREEN}Installation complete!${NC}"
echo ""
echo "Next steps:"
echo "1. Edit ~/.config/alwaysblock/config.yaml to configure your domains"
echo "2. Run 'alwaysblock status' to check status"
echo "3. Run 'alwaysblock unblock reddit' to temporarily unblock a site"
echo ""
echo "Note: No daemon required! The Network Extension handles all blocking."