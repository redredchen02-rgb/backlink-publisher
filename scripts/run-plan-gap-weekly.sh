#!/usr/bin/env bash
# plan-gap weekly — invoked by com.dex.bp-plan-gap launchd plist.
# Runs Sunday 02:00: equity-ledger | plan-gap → logs/plan-gap-latest.json
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd -P)
BP_DIR=$(cd "$SCRIPT_DIR/.." && pwd -P)
PYTHON="$BP_DIR/.venv/bin/python"
LOG_DIR="$BP_DIR/logs"
TMP="$LOG_DIR/plan-gap-latest.json.tmp"
OUT="$LOG_DIR/plan-gap-latest.json"
export PYTHONPATH="$BP_DIR/src:$BP_DIR${PYTHONPATH:+:$PYTHONPATH}"

DESIRED="${BP_PLAN_GAP_DESIRED:-3}"
LANGUAGE="${BP_PLAN_GAP_LANGUAGE:-zh-CN}"

mkdir -p "$LOG_DIR"

"$PYTHON" -m backlink_publisher.cli.equity_ledger \
  | "$PYTHON" -m backlink_publisher.cli.plan_gap \
      --desired "$DESIRED" \
      --language "$LANGUAGE" \
  > "$TMP"

mv "$TMP" "$OUT"
echo "plan-gap-weekly OK → $OUT ($(wc -l < "$OUT") lines)"
