#!/bin/sh
# Regenerates docs/screenshots/*.png from the app's SwiftUI views with fictional data.
set -e
cd "$(dirname "$0")"
root=$(cd ../.. && pwd)
build=$(mktemp -d)
trap 'rm -rf "$build"' EXIT

# Same logos as the app (see app/build.sh); SF Symbols are used when they are missing.
cp "/Applications/Claude.app/Contents/Resources/TrayIconTemplate@3x.png" "$build/claude.png" 2>/dev/null || true
cp "/Applications/ChatGPT.app/Contents/Resources/chatgptTemplate@2x.png" "$build/openai.png" 2>/dev/null || true

# macOS 15 target for MeshGradient (screenshots only; the app itself still targets macOS 14).
xcrun swiftc -parse-as-library -swift-version 5 -D SCREENSHOTS -target "$(uname -m)-apple-macosx15.0" \
  "$root/app/AIUsage.swift" Screenshots.swift -o "$build/screenshots"

out="$root/docs/screenshots"
mkdir -p "$out"
"$build/screenshots" "$out"

# The desktops have no transparency: JPEG keeps them a fraction of the PNG size.
for f in "$out"/desktop-*.png; do
  sips -s format jpeg -s formatOptions 90 "$f" --out "${f%.png}.jpg" >/dev/null && rm "$f"
done
