#!/bin/sh
# Builds ~/Applications/AI Usage.app from AIUsage.swift.
set -e
cd "$(dirname "$0")"
app="$HOME/Applications/AI Usage.app"

mkdir -p "$app/Contents/MacOS" "$app/Contents/Resources"
# Brand logos: the monochrome menu bar templates shipped with the Claude and ChatGPT apps
cp "/Applications/Claude.app/Contents/Resources/TrayIconTemplate@3x.png" "$app/Contents/Resources/claude.png" 2>/dev/null || true
cp "/Applications/ChatGPT.app/Contents/Resources/chatgptTemplate@2x.png" "$app/Contents/Resources/openai.png" 2>/dev/null || true
cat > "$app/Contents/Info.plist" <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleIdentifier</key><string>io.github.mathfreedom.ai-usage</string>
  <key>CFBundleName</key><string>AI Usage</string>
  <key>CFBundleExecutable</key><string>AIUsage</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>CFBundleVersion</key><string>1</string>
  <key>LSMinimumSystemVersion</key><string>14.0</string>
  <key>LSUIElement</key><true/>
</dict>
</plist>
EOF

xcrun swiftc -parse-as-library -O -swift-version 5 -target "$(uname -m)-apple-macosx14.0" \
  AIUsage.swift -o "$app/Contents/MacOS/AIUsage"
codesign --force --sign - "$app"
echo "Built $app"
