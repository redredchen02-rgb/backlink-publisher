#!/bin/bash
# install-optimization-launchd.sh
# Installs the bp-optimisation launchd agent and loads it.
# Run once after cloning / setting up.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PLIST_SRC="$SCRIPT_DIR/com.dex.bp-optimization.plist"
PLIST_DST="$HOME/Library/LaunchAgents/com.dex.bp-optimization.plist"

mkdir -p "$HOME/Library/LaunchAgents"

cp "$PLIST_SRC" "$PLIST_DST"
chmod 644 "$PLIST_DST"

# Unload if already loaded, then load
launchctl unload "$PLIST_DST" 2>/dev/null || true
launchctl load "$PLIST_DST"

echo "✅ com.dex.bp-optimization installed and loaded."
echo "   Logs: $SCRIPT_DIR/../logs/optimization-launchd.log"
echo ""
echo "  launchctl list | grep bp-optimization  — check status"
echo "  launchctl stop com.dex.bp-optimization — trigger immediately"
