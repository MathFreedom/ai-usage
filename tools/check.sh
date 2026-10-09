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

# The scans below rely on git: refuse to run (rather than pass) outside a work tree.
git rev-parse --is-inside-work-tree >/dev/null 2>&1 || fail "not a git work tree"

step "shell syntax (every tracked or new .sh file)"
git -c core.quotePath=false ls-files --cached --others --exclude-standard -- '*.sh' > "$tmp/scripts"
while IFS= read -r f; do
  [ -e "$f" ] || continue  # tracked but deleted in the work tree
  sh -n "$f" || fail "syntax error in $f"
done < "$tmp/scripts"

step "cx, ccx parse as Python 3.9 (the Command Line Tools' python3)"
/usr/bin/python3 -B - bin/cx bin/ccx <<'EOF' || fail "Python syntax"
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
# Patterns are written so they never match their own source: this file is scanned too.
# git grep exits 1 when nothing matches; anything else, or a file it couldn't read, is an
# error, not a pass.
scan() {
  set +e
  git grep --untracked "$@" > "$tmp/found" 2> "$tmp/grep-errors"
  code=$?
  set -e
  [ "$code" -le 1 ] && [ ! -s "$tmp/grep-errors" ] || { cat "$tmp/grep-errors"; fail "git grep failed ($code)"; }
}
scan -nIE '(^|[^A-Za-z0-9])(sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})|eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}|/U[s]ers/[A-Za-z]' -- .
if [ -s "$tmp/found" ]; then cat "$tmp/found"; fail "token or absolute home path above"; fi
scan -hIoE '[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}' -- .
emails=$(grep -viE '@([a-z0-9-]+\.)*example(\.(com|org|net))?$|@users\.noreply\.github\.com$|@[0-9]x\.(png|jpe?g)$' "$tmp/found" || true)
[ -z "$emails" ] || { printf '%s\n' "$emails"; fail "real-looking email above (use example.com)"; }

echo "check: OK"
