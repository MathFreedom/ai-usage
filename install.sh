#!/bin/sh
# Installs everything from this repo: symlinks the scripts, builds the menu bar app,
# and points the Claude Code status line at claude/statusline.sh.
set -e
repo=$(cd "$(dirname "$0")" && pwd)

command -v jq >/dev/null || { echo "jq est requis : brew install jq"; exit 1; }

mkdir -p "$HOME/.local/bin" "$HOME/.claude"
ln -sf "$repo/bin/cx" "$HOME/.local/bin/cx"
ln -sf "$repo/bin/ccx" "$HOME/.local/bin/ccx"
ln -sf "$repo/claude/statusline.sh" "$HOME/.claude/statusline-cache.sh"
chmod +x "$repo/bin/cx" "$repo/bin/ccx" "$repo/claude/statusline.sh" "$repo/app/build.sh"

settings="$HOME/.claude/settings.json"
[ -f "$settings" ] || echo '{}' > "$settings"
current=$(jq -r '.statusLine.command // ""' "$settings")
if [ "$current" != "~/.claude/statusline-cache.sh" ]; then
  cp "$settings" "$settings.bak-ai-usage"
  jq '.statusLine = {"type": "command", "command": "~/.claude/statusline-cache.sh", "refreshInterval": 60}' \
    "$settings.bak-ai-usage" > "$settings"
  echo "Status line Claude Code configurée (ancien réglage : $settings.bak-ai-usage)"
fi

"$repo/app/build.sh"
open "$HOME/Applications/AI Usage.app"
echo "Installé. Ajoute tes comptes Codex avec : cx save <nom> / cx add"
