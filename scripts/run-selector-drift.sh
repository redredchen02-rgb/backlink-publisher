#!/bin/bash
# run-selector-drift.sh — Scheduled browser selector-drift static guard.
# Called by launchd (com.dex.bp-selector-drift.plist); logs to logs/selector-drift.log
#
# Runs the STATIC manifest check only (no browser): asserts the per-channel
# selector constants are present and the success regexes still compile. This
# catches a selector/login-flow constant being deleted or mangled in-repo. It does
# NOT verify selectors against the live sites — that is the attended
# `make selector-smoke` (needs an attached Chrome) and stays operator-run.
#
# Plan 2026-06-15-007 R9.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
VENV="$REPO_DIR/.venv"
LOG_DIR="$REPO_DIR/logs"
TIMESTAMP="$(date '+%Y-%m-%dT%H:%M:%S%z')"

mkdir -p "$LOG_DIR"
log() { echo "[$TIMESTAMP] $*" >> "$LOG_DIR/selector-drift.log"; }

log "=== selector-drift static check starting ==="
cd "$REPO_DIR"

if [ ! -f "$VENV/bin/python" ]; then
    log "ERROR: venv not found at $VENV"
    exit 1
fi

if PYTHONPATH=src "$VENV/bin/python" -m pytest tests/test_browser_selector_manifest.py -q \
        >> "$LOG_DIR/selector-drift.log" 2>&1; then
    log "selector-drift OK (manifest intact)"
else
    log "WARN: selector-drift DETECTED — browser selector/login constants changed; review before next browser publish"
fi

log "=== selector-drift static check complete ==="
