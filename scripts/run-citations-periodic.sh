#!/usr/bin/env bash
# probe-citations daily probe — invoked by com.dex.bp-citations launchd plist.
# Runs at 06:00; --max-pairs and --cost-cap are conservative defaults.
# Adjust BP_CITATIONS_MAX_PAIRS / BP_CITATIONS_COST_CAP per Perplexity v1 quota.
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd -P)
BP_DIR=$(cd "$SCRIPT_DIR/.." && pwd -P)
LOG_DIR="$BP_DIR/logs"
ALERT_FILE="$LOG_DIR/citation-share-alert.json"

mkdir -p "$LOG_DIR"

MAX_PAIRS="${BP_CITATIONS_MAX_PAIRS:-5}"
COST_CAP="${BP_CITATIONS_COST_CAP:-10}"

# Remove stale alert before this run
rm -f "$ALERT_FILE"

set +e
"$BP_DIR/.venv/bin/probe-citations" \
  --probe \
  --max-pairs "$MAX_PAIRS" \
  --cost-cap "$COST_CAP" \
  --fail-on-low-share
EXIT_CODE=$?
set -e

if [ "$EXIT_CODE" -eq 6 ]; then
  # Write alert sentinel — sites.html picks this up for autopilot notify
  printf '{"alert":"low_citation_share","ts":"%s"}\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$ALERT_FILE"
  echo "WARN: citation share below threshold — alert written to $ALERT_FILE" >&2
  exit 0  # non-critical; don't fail the launchd job
fi

exit "$EXIT_CODE"
