#!/bin/bash
# install-full-pipeline-launchd.sh
# Installs the bp-full-pipeline launchd agent and loads it.
# Run once after cloning / setting up.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PLIST_SRC="$SCRIPT_DIR/com.dex.bp-full-pipeline.plist"
PLIST_DST="$HOME/Library/LaunchAgents/com.dex.bp-full-pipeline.plist"

mkdir -p "$HOME/Library/LaunchAgents"

cp "$PLIST_SRC" "$PLIST_DST"
chmod 644 "$PLIST_DST"

launchctl unload "$PLIST_DST" 2>/dev/null || true
launchctl load "$PLIST_DST"

echo "✅ com.dex.bp-full-pipeline installed and loaded."
echo "   Logs: $SCRIPT_DIR/../logs/pipeline-launchd.log"
echo ""
echo "  launchctl list | grep bp-full-pipeline     — check status"
echo "  launchctl stop com.dex.bp-full-pipeline    — trigger immediately"
