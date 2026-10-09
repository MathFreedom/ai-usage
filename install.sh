#!/bin/sh
# Installs everything from this repo: symlinks the scripts, builds the menu bar app,
# and points the Claude Code status line at claude/statusline.sh.
set -e
repo=$(cd "$(dirname "$0")" && pwd)

command -v jq >/dev/null || { echo "jq is required: brew install jq"; exit 1; }

mkdir -p "$HOME/.local/bin" "$HOME/.claude"
ln -sf "$repo/bin/cx" "$HOME/.local/bin/cx"
ln -sf "$repo/bin/ccx" "$HOME/.local/bin/ccx"
ln -sf "$repo/claude/statusline.sh" "$HOME/.claude/statusline-cache.sh"
chmod +x "$repo/bin/cx" "$repo/bin/ccx" "$repo/claude/statusline.sh" "$repo/app/build.sh"

settings="$HOME/.claude/settings.json"
[ -f "$settings" ] || echo '{}' > "$settings"
current=$(jq -r '.statusLine.command // ""' "$settings")
case "$current" in
  *statusline-cache.sh*) ;;  # already ours, in whatever form
  *)
    [ -f "$settings.bak-ai-usage" ] || cp "$settings" "$settings.bak-ai-usage"  # keep the first backup
    if [ -n "$current" ]; then  # keep feeding the previous status line command
      mkdir -p "$HOME/.config/ai-usage"
      printf '%s\n' "$current" > "$HOME/.config/ai-usage/statusline-chain"
      echo "Your previous status line now runs in the background (output hidden):"
      echo "  $current"
      echo "Delete ~/.config/ai-usage/statusline-chain to stop it."
    fi
    # Written through (not replaced): a settings.json symlinked from a dotfiles repo stays a link.
    tmp=$(mktemp)
    jq '.statusLine = {"type": "command", "command": "~/.claude/statusline-cache.sh", "refreshInterval": 60}' \
      "$settings" > "$tmp" && cat "$tmp" > "$settings" && rm -f "$tmp"
    echo "Claude Code status line configured (settings before the first install: $settings.bak-ai-usage)"
    ;;
esac

"$repo/app/build.sh"
open "$HOME/Applications/AI Usage.app"
echo "Installed. Save your current accounts with: cx save && ccx save"
