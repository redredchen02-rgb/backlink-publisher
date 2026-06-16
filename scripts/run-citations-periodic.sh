#!/usr/bin/env bash
# probe-citations daily probe — invoked by com.dex.bp-citations launchd plist.
# Runs at 06:00; --max-pairs and --cost-cap are conservative defaults.
# Adjust BP_CITATIONS_MAX_PAIRS / BP_CITATIONS_COST_CAP per Perplexity v1 quota.
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd -P)
BP_DIR=$(cd "$SCRIPT_DIR/.." && pwd -P)

MAX_PAIRS="${BP_CITATIONS_MAX_PAIRS:-5}"
COST_CAP="${BP_CITATIONS_COST_CAP:-10}"

exec "$BP_DIR/.venv/bin/probe-citations" \
  --probe \
  --max-pairs "$MAX_PAIRS" \
  --cost-cap "$COST_CAP"
