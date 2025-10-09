#!/bin/bash

# Create Xcode project from command line
cd AlwaysBlockApp

# Create the project using xcodebuild
cat > project_template.swift << 'EOF'
import Foundation

print("Creating Xcode project...")

// We'll create it manually in Xcode instead
print("Please open Xcode and:")
print("1. File → New → Project")
print("2. Choose macOS → App")
print("3. Product Name: AlwaysBlock")
print("4. Bundle ID: com.alwaysblock.app")
print("5. No UI (command line)")
print("")
print("Then:")
print("1. File → New → Target")
print("2. Choose macOS → Network Extension")
print("3. Product Name: AlwaysBlockExtension")
print("4. Type: Content Filter")
print("5. Bundle ID: com.alwaysblock.app.extension")
EOF

swift project_template.swift