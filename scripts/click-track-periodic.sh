#!/usr/bin/env bash
# click-track-periodic — run click-track --probe from cron / launchd
#
# Resolves the canonical backlink-publisher directory, activates its venv,
# and runs `click-track --probe` (which reads targets from [click_track].sites
# in config.toml).  Output is logged with ISO-8601 timestamps.
#
# Exit codes:
#   0 — success (or nothing to do)
#   1 — setup error (no venv, no config)
#   2 — probe error (GA4 query failed for all targets)
#
# Usage:
#   ./scripts/click-track-periodic.sh                  # normal
#   ./scripts/click-track-periodic.sh --dry-run        # preview targets, no probe
#   CLICK_TRACK_PROPERTY_ID=123456 ./scripts/click-track-periodic.sh  # override property
#
# Environment:
#   CLICK_TRACK_PROPERTY_ID  — override the GA4 property ID (optional when
#                              [click_track].sites maps every target in config)
#   CLICK_TRACK_EXTRA_ARGS   — additional flags passed through to click-track
#                              (e.g. "--window-days 14 --store-path /tmp/events.db")

set -euo pipefail

# ── Auto-detect repo root ──────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd -P)"

# ── Python interpreter ─────────────────────────────────────────────────
PYTHON=""
if [[ -x "$REPO_DIR/.venv/bin/python" ]]; then
    PYTHON="$REPO_DIR/.venv/bin/python"
elif command -v python3 &>/dev/null; then
    PYTHON="$(command -v python3)"
else
    echo "[click-track-periodic] ERROR: no Python interpreter found" >&2
    exit 1
fi

# ── Config dir (default ~/.config/backlink-publisher) ──────────────────
# The test conftest also respects BACKLINK_PUBLISHER_CONFIG_DIR; exporting
# it empty lets the project use the default path.
export BACKLINK_PUBLISHER_CONFIG_DIR="${BACKLINK_PUBLISHER_CONFIG_DIR:-}"

# ── Flags ──────────────────────────────────────────────────────────────
DRY_RUN=0
for arg in "$@"; do
    case "$arg" in
        --dry-run) DRY_RUN=1 ;;
    esac
done

PROBE_FLAG=""
if [[ "$DRY_RUN" -eq 0 ]]; then
    PROBE_FLAG="--probe"
fi

PROPERTY_ARG=""
if [[ -n "${CLICK_TRACK_PROPERTY_ID:-}" ]]; then
    PROPERTY_ARG="--property ${CLICK_TRACK_PROPERTY_ID}"
fi

EXTRA_ARGS="${CLICK_TRACK_EXTRA_ARGS:-}"

# ── Log timestamp ──────────────────────────────────────────────────────
log() {
    echo "[click-track-periodic] $(date -u +%Y-%m-%dT%H:%M:%SZ) $*"
}

# ── Run ────────────────────────────────────────────────────────────────
log "starting (dry_run=${DRY_RUN})"

cd "$REPO_DIR"
export PYTHONPATH="${PYTHONPATH:-}:src"

# shellcheck disable=SC2086
if ! "$PYTHON" -m backlink_publisher.cli.click_track \
    $PROBE_FLAG \
    $PROPERTY_ARG \
    $EXTRA_ARGS \
    2>&1; then
    exit_code=$?
    log "click-track exited code ${exit_code}"
    exit 2
fi

log "finished"
