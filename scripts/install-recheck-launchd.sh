#!/bin/bash
# install-recheck-launchd.sh
# Installs the bp-recheck (daily liveness recheck + coverage alarm) and
# bp-selector-drift (daily static selector-manifest guard) launchd agents.
# Run once after cloning / setting up.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

mkdir -p "$HOME/Library/LaunchAgents"

install_agent() {
    local label="$1"
    local src="$SCRIPT_DIR/$label.plist"
    local dst="$HOME/Library/LaunchAgents/$label.plist"
    cp "$src" "$dst"
    chmod 644 "$dst"
    launchctl unload "$dst" 2>/dev/null || true
    launchctl load "$dst"
    echo "✅ $label installed and loaded."
}

install_agent com.dex.bp-recheck
install_agent com.dex.bp-selector-drift

echo ""
echo "   Logs: $SCRIPT_DIR/../logs/recheck-launchd.log, selector-drift-launchd.log"
echo ""
echo "  launchctl list | grep -E 'bp-recheck|bp-selector-drift'  — check status"
echo "  launchctl stop com.dex.bp-recheck         — trigger recheck now"
echo "  launchctl stop com.dex.bp-selector-drift  — trigger drift check now"
