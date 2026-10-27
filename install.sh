#!/bin/sh
# Installs everything from this repo: links cx and ccx into ~/.local/bin and builds the menu bar app.
set -e
repo=$(cd "$(dirname "$0")" && pwd)

mkdir -p "$HOME/.local/bin"
ln -sf "$repo/bin/cx" "$HOME/.local/bin/cx"
ln -sf "$repo/bin/ccx" "$HOME/.local/bin/ccx"
chmod +x "$repo/bin/cx" "$repo/bin/ccx" "$repo/app/build.sh"

"$repo/app/build.sh"
open "$HOME/Applications/AI Usage.app"
echo "Installed. Save your current accounts with: cx save && ccx save"
