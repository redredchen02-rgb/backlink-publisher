#!/usr/bin/env bash
# probe-index daily GSC page-signal probe — invoked by com.dex.bp-probe-index launchd plist.
# Runs at UTC 02:30 (before probe-citations at 06:00 to avoid GSC quota contention).
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd -P)
BP_DIR=$(cd "$SCRIPT_DIR/.." && pwd -P)
LOG_DIR="$BP_DIR/logs"

mkdir -p "$LOG_DIR"

MAX_URLS="${BP_PROBE_INDEX_MAX_URLS:-200}"

set +e
"$BP_DIR/.venv/bin/probe-index" \
  --probe \
  --max-urls "$MAX_URLS" \
  >> "$LOG_DIR/probe-index.log" 2>&1
EXIT_CODE=$?
set -e

if [ "$EXIT_CODE" -eq 6 ]; then
  echo "WARN: probe-index exited with advisory 6 (GSC quota or error)" >&2
  exit 0
fi

exit "$EXIT_CODE"
