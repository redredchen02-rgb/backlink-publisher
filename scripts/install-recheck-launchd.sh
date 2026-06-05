#!/bin/bash
# install-recheck-launchd.sh
# Installs the bp-recheck launchd agent and loads it.
# Run once after cloning / setting up.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PLIST_SRC="$SCRIPT_DIR/com.dex.bp-recheck.plist"
PLIST_DST="$HOME/Library/LaunchAgents/com.dex.bp-recheck.plist"

mkdir -p "$HOME/Library/LaunchAgents"

cp "$PLIST_SRC" "$PLIST_DST"
chmod 644 "$PLIST_DST"

# Unload if already loaded, then load
launchctl unload "$PLIST_DST" 2>/dev/null || true
launchctl load "$PLIST_DST"

echo "✅ com.dex.bp-recheck installed and loaded."
echo "   Logs: $SCRIPT_DIR/../logs/recheck-launchd.log"
echo ""
echo "  launchctl list | grep bp-recheck     — check status"
echo "  launchctl stop com.dex.bp-recheck    — trigger immediately"
