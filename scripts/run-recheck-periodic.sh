#!/bin/bash
# run-recheck-periodic.sh — Scheduled backlink-liveness re-verification
# Called by launchd; logs to logs/recheck-periodic.log
#
# Gated behind --probe (no network by default).  Remove --probe once the
# operator has reviewed the first few dry-run outputs.
#
# Usage:
#   ./scripts/run-recheck-periodic.sh                 # dry-run (preview)
#   ./scripts/run-recheck-periodic.sh --probe         # live probe
#   PROBE=1 ./scripts/run-recheck-periodic.sh         # same via env

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
VENV="$REPO_DIR/.venv"
LOG_DIR="$REPO_DIR/logs"
TIMESTAMP="$(date '+%Y-%m-%dT%H:%M:%S%z')"

mkdir -p "$LOG_DIR"

log() { echo "[$TIMESTAMP] $*" >> "$LOG_DIR/recheck.log"; }

log "=== recheck-backlinks run starting ==="

cd "$REPO_DIR"

if [ ! -f "$VENV/bin/python" ]; then
    log "ERROR: venv not found at $VENV"
    exit 1
fi

PYTHON="$VENV/bin/python"

# Support both flag and env-var gating
PROBE_FLAG=""
if [[ "${PROBE:-}" == "1" ]]; then
    PROBE_FLAG="--probe"
fi
for arg in "$@"; do
    if [[ "$arg" == "--probe" ]]; then
        PROBE_FLAG="--probe"
    fi
done

# Weekly sweep covers ALL due links, oldest-first, bounded by the CLI's
# probe-batch wall-clock budget (_BATCH_BUDGET_S, ~600s); leftovers defer to
# the next day. Raise the per-run cap via --limit (override RECHECK_LIMIT to tune).
RECHECK_LIMIT="${RECHECK_LIMIT:-1000}"

log "recheck-backlinks $([ -n "$PROBE_FLAG" ] && echo '--probe' || echo '(dry-run)') --limit $RECHECK_LIMIT …"
if "$PYTHON" -m backlink_publisher.cli.recheck_backlinks $PROBE_FLAG --limit "$RECHECK_LIMIT" >> "$LOG_DIR/recheck.log" 2>&1; then
    log "recheck-backlinks OK"
else
    exit_code=$?
    log "recheck-backlinks FAILED (exit $exit_code)"
fi

# Signal-freshness alarm (Plan 2026-06-15-007 U1): after the sweep, verify
# within-window liveness coverage still meets target. Advisory — logs a WARN if
# it dropped (exit 6), never aborts the cron. publish-metrics is read-only / no
# network. Surfaced in the log (and the operator's TG-bot tails it).
log "publish-metrics --alarm (coverage-freshness check) …"
if "$PYTHON" -m backlink_publisher.cli.publish_metrics --alarm >> "$LOG_DIR/recheck.log" 2>&1; then
    log "coverage OK (meets target)"
else
    log "WARN: within-window liveness coverage BELOW target — raise recheck cadence/budget (see runbook)"
fi

log "=== recheck-backlinks run complete ==="
