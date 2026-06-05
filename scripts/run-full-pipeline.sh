#!/bin/bash
# run-full-pipeline.sh — One-command backlink pipeline from gap detection to publish
#
# Modes:
#   gap        equity-ledger → plan-gap → plan-backlinks → validate → publish
#   publish    validate-backlinks <input> → publish-backlinks       (stdin mode)
#
# Config via env vars:
#   BP_LANG          Seed language (default: zh-CN)
#   BP_DESIRED       Target dofollow count per target (default: 3)
#   BP_URL_MODE      URL mode A/B/C (default: A)
#   BP_PUBLISH_MODE  draft or publish (default: draft)
#   BP_PLATFORM      Target platform (default: auto-detect)
#   BP_OPTIMIZE      Run post-publish optimization (default: 1)
#   BP_DRY_RUN       Preview only, no side effects (default: 0)
#   BP_MAX_ROWS      Max rows per CLI stage (default: 1000)
#
# Usage:
#   ./scripts/run-full-pipeline.sh gap                     # full gap→publish
#   BP_DRY_RUN=1 ./scripts/run-full-pipeline.sh gap        # dry-run preview
#   cat seeds.jsonl | ./scripts/run-full-pipeline.sh publish  # bypass gap detection

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
VENV="$REPO_DIR/.venv"
LOG_DIR="$REPO_DIR/logs"
TIMESTAMP="$(date '+%Y-%m-%dT%H:%M:%S%z')"
mkdir -p "$LOG_DIR"

PYTHON="$VENV/bin/python"
cd "$REPO_DIR"

# ── Defaults ──────────────────────────────────────────────────────────
BP_LANG="${BP_LANG:-zh-CN}"
BP_DESIRED="${BP_DESIRED:-3}"
BP_URL_MODE="${BP_URL_MODE:-A}"
BP_PUBLISH_MODE="${BP_PUBLISH_MODE:-draft}"
BP_PLATFORM="${BP_PLATFORM:-}"
BP_OPTIMIZE="${BP_OPTIMIZE:-1}"
BP_DRY_RUN="${BP_DRY_RUN:-0}"
BP_MAX_ROWS="${BP_MAX_ROWS:-1000}"

log()  { echo "[$TIMESTAMP] $*" >> "$LOG_DIR/pipeline.log"; }
info() { echo "[pipeline] $*"; }

pipeline_log="$LOG_DIR/pipeline-$TIMESTAMP.log"
touch "$pipeline_log"

PY_BASE=("$PYTHON" -m backlink_publisher.cli)

# ── Helper: run a CLI stage ───────────────────────────────────────────
run_stage() {
    local stage_name="$1"
    shift
    log "[$stage_name] executing: $*"
    info "  → $stage_name …"

    if [[ "$BP_DRY_RUN" == "1" ]]; then
        log "[$stage_name] DRY-RUN — would run: $*"
        info "    (dry-run, skipped)"
        return 0
    fi

    if ! "$@" >> "$pipeline_log" 2>&1; then
        local exit_code=$?
        log "[$stage_name] FAILED (exit $exit_code)"
        info "    FAILED (exit $exit_code) — see $pipeline_log"
        return "$exit_code"
    fi
    log "[$stage_name] OK"
    return 0
}

# ── Mode: publish (stdin → validate → publish) ──────────────────────
do_publish() {
    info "≡ Pipeline: validate → publish"

    local validated
    validated=$("${PY_BASE[@]}.validate_backlinks" --input /dev/stdin --max-rows "$BP_MAX_ROWS" 2>>"$pipeline_log") || {
        info "  ✗ validate-backlinks failed"
        return 1
    }

    local pub_args=("--mode" "$BP_PUBLISH_MODE" "--max-rows" "$BP_MAX_ROWS")
    [[ -n "$BP_PLATFORM" ]] && pub_args+=("--platform" "$BP_PLATFORM")
    [[ "$BP_OPTIMIZE" == "1" ]] && pub_args+=("--optimize")

    echo "$validated" | run_stage "publish-backlinks" "${PY_BASE[@]}.publish_backlinks" "${pub_args[@]}" -i /dev/stdin
}

# ── Mode: gap (equity → plan-gap → plan → validate → publish) ──────
do_gap() {
    info "≡ Pipeline: equity-ledger → plan-gap → plan-backlinks → validate → publish"

    info "  Step 1/5: equity-ledger …"
    local ledger
    ledger=$("${PY_BASE[@]}.equity_ledger" 2>>"$pipeline_log") || {
        info "  ✗ equity-ledger failed"
        return 1
    }

    info "  Step 2/5: plan-gap (desired=$BP_DESIRED lang=$BP_LANG) …"
    local gap_seeds
    gap_seeds=$(echo "$ledger" | "${PY_BASE[@]}.plan_gap" \
        --desired "$BP_DESIRED" --language "$BP_LANG" \
        --url-mode "$BP_URL_MODE" --publish-mode "$BP_PUBLISH_MODE" \
        2>>"$pipeline_log") || {
        info "  ✗ plan-gap failed"
        return 1
    }

    if [[ -z "$gap_seeds" || "$gap_seeds" == "" ]]; then
        info "  ✓ No gaps to fill — all targets satisfied; pipeline complete."
        return 0
    fi

    info "  Step 3/5: plan-backlinks …"
    local plans
    plans=$(echo "$gap_seeds" | "${PY_BASE[@]}.plan_backlinks" --input /dev/stdin --language "$BP_LANG" 2>>"$pipeline_log") || {
        info "  ✗ plan-backlinks failed"
        return 1
    }

    info "  Step 4/5: validate-backlinks …"
    local validated
    validated=$(echo "$plans" | "${PY_BASE[@]}.validate_backlinks" --input /dev/stdin --max-rows "$BP_MAX_ROWS" 2>>"$pipeline_log") || {
        info "  ✗ validate-backlinks failed"
        return 1
    }

    info "  Step 5/5: publish-backlinks …"
    local pub_args=("--mode" "$BP_PUBLISH_MODE" "--max-rows" "$BP_MAX_ROWS")
    [[ -n "$BP_PLATFORM" ]] && pub_args+=("--platform" "$BP_PLATFORM")
    [[ "$BP_OPTIMIZE" == "1" ]] && pub_args+=("--optimize")

    echo "$validated" | run_stage "publish-backlinks" "${PY_BASE[@]}.publish_backlinks" "${pub_args[@]}" -i /dev/stdin
}

# ── Entry point ───────────────────────────────────────────────────────
MODE="${1:-gap}"

log "=== full-pipeline start mode=$MODE BP_DRY_RUN=$BP_DRY_RUN ==="

case "$MODE" in
    gap)
        do_gap
        ;;
    publish)
        do_publish
        ;;
    *)
        echo "Usage: $0 [gap|publish]"
        echo "  gap      — equity-ledger → plan-gap → plan → validate → publish (default)"
        echo "  publish  — validate <stdin> → publish-backlinks"
        echo ""
        echo "Env: BP_LANG, BP_DESIRED, BP_URL_MODE, BP_PUBLISH_MODE, BP_PLATFORM, BP_OPTIMIZE, BP_DRY_RUN, BP_MAX_ROWS"
        exit 1
        ;;
esac

exit_code=$?
log "=== full-pipeline exit=$exit_code ==="
info "≡ Done (exit $exit_code) — see $pipeline_log"
exit "$exit_code"
