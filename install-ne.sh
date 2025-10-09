#!/bin/bash
# Installation script for AlwaysBlock Network Extension version

set -e

echo "AlwaysBlock Network Extension Installer"
echo "======================================="
echo ""

# Check if running on macOS
if [[ "$OSTYPE" != "darwin"* ]]; then
    echo "Error: This script only works on macOS"
    exit 1
fi

# Check if developer mode is enabled
if ! systemextensionsctl developer 2>/dev/null | grep -q "on"; then
    echo "Error: Developer mode is not enabled"
    echo ""
    echo "To enable developer mode:"
    echo "1. Disable SIP in Recovery Mode (if not already done)"
    echo "2. Run: sudo systemextensionsctl developer on"
    exit 1
fi

# Install the CLI
echo "Installing CLI..."
if [ -f "/usr/local/bin/alwaysblock" ]; then
    echo "Removing old CLI..."
    sudo rm -f /usr/local/bin/alwaysblock
fi

sudo cp alwaysblock /usr/local/bin/
sudo chmod +x /usr/local/bin/alwaysblock
echo "✓ CLI installed to /usr/local/bin/alwaysblock"

# Check if Xcode project is built
if [ ! -d "AlwaysBlockApp/build" ] && [ ! -d "$HOME/Library/Developer/Xcode/DerivedData" ]; then
    echo ""
    echo "The AlwaysBlock app needs to be built first."
    echo ""
    echo "Please:"
    echo "1. Open AlwaysBlockApp/AlwaysBlock.xcodeproj in Xcode"
    echo "2. Select your development team (or 'Sign to Run Locally')"
    echo "3. Build and run the app (Cmd+R)"
    echo "4. Allow the system extension when prompted"
    echo ""
    echo "The extension will be automatically installed when you run the app."
else
    echo ""
    echo "If you've already built the app, you can run it now to install the extension."
fi

echo ""
echo "Installation complete!"
echo ""
echo "Usage:"
echo "  alwaysblock block reddit.com"
echo "  alwaysblock block twitter.com -d 30"
echo "  alwaysblock status"
echo "  alwaysblock unblock reddit.com"
echo "  alwaysblock unblock-all"