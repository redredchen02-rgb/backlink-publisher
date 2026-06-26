#!/bin/bash
# run-optimization.sh
# Scheduled runner for the continuous optimisation loop.
# Called by launchd; logs to a sibling logs/ directory.
#
# Stages:
#   1. collect-signals — gather recheck/canary/equity signals
#   2. optimize-weights — evaluate rules, adjust dispatch weights
#
# Both commands use --dry-run by default. Remove --dry-run to
# enable live writes once the signal sources are validated.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
VENV="$REPO_DIR/.venv"
LOG_DIR="$REPO_DIR/logs"
TIMESTAMP="$(date '+%Y-%m-%dT%H:%M:%S%z')"

mkdir -p "$LOG_DIR"

log() { echo "[$TIMESTAMP] $*" >> "$LOG_DIR/optimization.log"; }

log "=== optimization run starting ==="

cd "$REPO_DIR"

if [ ! -f "$VENV/bin/python" ]; then
    log "ERROR: venv not found at $VENV"
    exit 1
fi

PYTHON="$VENV/bin/python"

# Stage 1 — collect signals
log "collect-signals …"
if "$PYTHON" -m backlink_publisher.cli.collect_signals >> "$LOG_DIR/optimization.log" 2>&1; then
    log "collect-signals OK"
else
    log "collect-signals FAILED (exit $?) — continuing …"
fi

# Stage 2 — optimize weights
log "optimize-weights …"
if "$PYTHON" -m backlink_publisher.cli.optimize_weights >> "$LOG_DIR/optimization.log" 2>&1; then
    log "optimize-weights OK"
else
    log "optimize-weights FAILED (exit $?)"
fi

log "=== optimization run complete ==="
