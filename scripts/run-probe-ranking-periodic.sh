#!/usr/bin/env bash
# probe-ranking weekly GSC keyword ranking snapshot — invoked by
# com.dex.bp-probe-ranking launchd plist. Runs Sunday UTC 03:30.
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd -P)
BP_DIR=$(cd "$SCRIPT_DIR/.." && pwd -P)
LOG_DIR="$BP_DIR/logs"

mkdir -p "$LOG_DIR"

set +e
"$BP_DIR/.venv/bin/probe-ranking" \
  --probe \
  >> "$LOG_DIR/probe-ranking.log" 2>&1
EXIT_CODE=$?
set -e

if [ "$EXIT_CODE" -eq 6 ]; then
  echo "WARN: probe-ranking exited with advisory 6 (GSC error)" >&2
  exit 0
fi

exit "$EXIT_CODE"
