#!/bin/sh
# Pre-flight: the one command run before committing, and by the independent auditor
# (docs/PROCESS_AUDIT.md). Read-only for the repo and for the user's data: builds go to a
# temp dir, nothing is installed, no account or Keychain is touched. Ends with "check: OK".
set -eu
cd "$(dirname "$0")/.."
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

step() { printf '• %s\n' "$1"; }
fail() { printf 'check: FAILED (%s)\n' "$1"; exit 1; }

step "shell syntax"
for f in install.sh app/build.sh claude/statusline.sh tools/*.sh tools/*/*.sh; do
  if [ -f "$f" ]; then sh -n "$f" || fail "syntax error in $f"; fi
done

step "cx, ccx parse as Python 3.9 (the Command Line Tools' python3)"
/usr/bin/python3 - bin/cx bin/ccx <<'EOF' || fail "Python syntax"
import ast, sys
for path in sys.argv[1:]:
    with open(path) as f:
        ast.parse(f.read(), path, feature_version=(3, 9))
EOF

# Same compiler invocations as app/build.sh and tools/screenshots/render.sh, output in $tmp.
step "app builds"
xcrun swiftc -parse-as-library -O -swift-version 5 -target "$(uname -m)-apple-macosx14.0" \
  app/AIUsage.swift -o "$tmp/AIUsage" || fail "app build"

step "screenshot tool builds"
xcrun swiftc -parse-as-library -swift-version 5 -D SCREENSHOTS -target "$(uname -m)-apple-macosx15.0" \
  app/AIUsage.swift tools/screenshots/Screenshots.swift -o "$tmp/screenshots" || fail "screenshot tool build"

step "no secrets or personal data (tracked and new files)"
exclude=':!tools/check.sh'  # holds the patterns themselves
if git grep --untracked -nIE 'sk-ant-[A-Za-z0-9_-]{10,}|eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}|/Users/[A-Za-z]' -- . "$exclude"; then
  fail "token or absolute home path above"
fi
emails=$(git grep --untracked -hIoE '[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}' -- . "$exclude" \
  | grep -vE '@([A-Za-z0-9-]+\.)*example(\.com)?$|@users\.noreply\.github\.com$|@[0-9]x\.(png|jpe?g)$' || true)
[ -z "$emails" ] || { printf '%s\n' "$emails"; fail "real-looking email above (use example.com)"; }

echo "check: OK"
