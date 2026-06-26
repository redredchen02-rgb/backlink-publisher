"""Publish validated backlink payloads via adapter dispatcher."""

from __future__ import annotations

import sys
from typing import Any

from backlink_publisher._util.errors import (
    AuthExpiredError,
    BannerUploadError,
    ContentRejectedError,
    DependencyError,
    emit_envelope_and_exit,
    emit_error,
    ExternalServiceError,
)
from backlink_publisher._util.jsonl import read_jsonl
from backlink_publisher._util.logger import publish_logger
from backlink_publisher._util.recon import emit_recon
from backlink_publisher.cli._dedup_gate import (
    enforce_enabled,
    enforce_precondition_or_exit,
    gate_with_force,
    record_done,
    record_failure,
)
from backlink_publisher.cli._dedup_ops import _handle_dedup_ops, load_force_manifest
from backlink_publisher.cli._publish_helpers import (
    _acquire_publish_leases,
    _build_failure_row,
    _build_parser,
    _build_skip_row,
    _canary_gate,
    _check_row_reachability,
    _check_token_drift,
    _do_verify,
    _error_class,
    _handle_auth_expired,
    _handle_checkpoint_ops,
    _load_throttle_config,
    _maybe_emit_gate_banner,
    _medium_throttle_sleep,
    _partition_paused,
    _publish_epilogue,
    _record_publish_failure,
    _record_publish_path,
    _try_update_ckpt_failed,
)
from backlink_publisher.cli._resume import _run_resume  # noqa: F401
from backlink_publisher.cli.publish_backlinks._engine import publish_rows, PublishOptions
from backlink_publisher.config import load_config
from backlink_publisher.publishing.adapters import publish as adapter_publish
from backlink_publisher.publishing.adapters import verify_adapter_setup
from backlink_publisher.publishing.reliability.policy import policy_enabled, publish_with_policy

# checkpoint is re-exported into this namespace as a test-patch seam: tests patch
# `...publish_backlinks.checkpoint.create_checkpoint` to simulate checkpoint
# failures, and publish_rows() (in _engine) calls create_checkpoint on the SAME
# module object, so the patch applies even though the call site moved (U4-1).
from ... import checkpoint, config_echo  # noqa: F401 -- checkpoint = patch seam
from ...schema import reject_unsupported_platform, supported_platforms, validate_publish_payload


def _prepare_publish_rows(args: Any) -> tuple[list[dict[str, Any]], set, Any]:
    """Pre-loop CLI preparation for publish-backlinks (U4-5).

    Runs every shell-side gate that must precede the in-process publish_rows:
    input read + max-rows truncation, per-row payload validation, the tier-1
    dofollow filter, the read-only --preview-manifest exit, the dedup
    enforce-precondition + --force-manifest load, paused-platform partition,
    lease acquisition, and per-platform adapter-setup verification. These gates
    keep their SystemExit / emit_error — they are shell concerns and stay OUT of
    the SystemExit-free publish_rows. Returns (filtered_rows, forced_keys, config).
    """
    publish_logger.info("publish-backlinks started", extra={
        "platform": args.platform,
        "mode": args.mode,
        "dry_run": args.dry_run,
    })

    if not args.dry_run:
        _maybe_emit_gate_banner(args.skip_publish_time_check)

    try:
        rows = list(read_jsonl(args.input))
    except SystemExit as exc:
        raise SystemExit(exc.code)

    if len(rows) > args.max_rows:
        print(
            f"[warn] publish-backlinks: truncated input from {len(rows)} to"
            f" {args.max_rows} rows (--max-rows={args.max_rows})",
            file=sys.stderr,
        )
        rows = rows[:args.max_rows]

    publish_logger.info(f"processing {len(rows)} payloads")

    mode = args.mode or "draft"
    emit_recon("info", command="publish-backlinks", row_count=str(len(rows)), mode=mode)

    config = load_config()
    config_echo.emit_banner(config, "publish-backlinks")

    for idx, row in enumerate(rows, start=1):
        platform = args.platform or row.get("platform", "")
        platform_msg = reject_unsupported_platform(platform)
        if platform_msg is not None:
            emit_error(f"row {idx}: {platform_msg}", exit_code=2)
        errs = validate_publish_payload(row)
        if errs:
            for e in errs:
                publish_logger.warning(f"row {idx}: {e}")
            emit_envelope_and_exit(
                "InputValidationError", 2, f"row {idx}: payload validation failed"
            )

    if getattr(args, "tier_1", False):
        from backlink_publisher.publishing.registry import dofollow_status
        filtered: list[dict[str, Any]] = []
        for row in rows:
            plat = args.platform or row.get("platform", "")
            ds = dofollow_status(plat)
            if ds is True:
                filtered.append(row)
            else:
                emit_recon("info", row=row.get('id', ''), platform=plat,
                           dofollow=repr(ds), skipped="", reason="tier-filter")
        rows = filtered
        if not rows:
            emit_recon("info", reason="tier-filter", result="all-filtered")
            raise SystemExit(0)

    if args.preview_manifest:
        # Read-only dedup preview over the validated planned rows. Emits verdicts
        # and exits 0 before any lease/checkpoint/dispatch side effect (U3).
        from backlink_publisher.cli.preview_manifest import emit_manifest
        emit_manifest(rows, args.platform)
        raise SystemExit(0)

    forced_keys: set = set()
    if not args.dry_run:
        # R19b: enforce refuses to run until the dedup store covers the
        # back-catalogue (no-op in observe). Checked before acquiring leases so a
        # not-ready run fails fast without holding a platform lease.
        enforce_precondition_or_exit()
        if args.force_manifest:
            # U7c: honor force-flags from a preview manifest (enforce only).
            if not enforce_enabled():
                emit_error(
                    "error: --force-manifest requires "
                    "BACKLINK_PUBLISHER_DEDUP_ENFORCE=1",
                    exit_code=1,
                )
            forced_keys = load_force_manifest(
                args.force_manifest, confirm=args.confirm, reason=args.reason
            )
        # Phase 2 U8: drop platforms an operator paused via /ce:health BEFORE
        # acquiring leases — a paused platform must hold no lease and create
        # no checkpoint.
        rows, paused_platforms = _partition_paused(rows, args.platform, config)
        for plat in paused_platforms:
            publish_logger.warning(
                f"publish-backlinks: skipping paused platform '{plat}' "
                f"(resume via /ce:health)"
            )
        if not rows:
            publish_logger.warning(
                "publish-backlinks: all target platforms are paused; "
                "nothing to publish"
            )
            raise SystemExit(0)

        platforms_in_use = {
            args.platform or row.get("platform", "") for row in rows
        }
        _acquire_publish_leases(platforms_in_use, False)
        emit_recon("info", command="publish-backlinks", phase="leases_acquired",
                   platform_count=str(len(platforms_in_use)))
        for plat in platforms_in_use:
            if plat not in supported_platforms():
                continue
            try:
                verify_adapter_setup(plat, config)
            except DependencyError as exc:
                emit_error(str(exc), exit_code=3)

    return rows, forced_keys, config


def main(argv: list[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)

    from backlink_publisher._util.logger import set_log_level
    from backlink_publisher._util.profiling import profile_if_enabled
    set_log_level(args.log_level)

    _handle_checkpoint_ops(args)
    _handle_dedup_ops(args)

    if args.resume:
        _run_resume(args)
        return

    with profile_if_enabled(args):
        # U4-5: all pre-loop CLI gates (read/validate/tier-1/preview/enforce/
        # force-manifest/partition/lease/verify) live in the shell helper; they
        # keep their SystemExit/emit_error and never enter publish_rows.
        rows, forced_keys, config = _prepare_publish_rows(args)

        # U4-1: checkpoint creation + the per-row loop now live behind the
        # in-process publish_rows entry. main() builds typed options, calls it,
        # then drives the impure epilogue (stdout + SystemExit) off the outcome.
        throttle_min, throttle_max = _load_throttle_config()
        options = PublishOptions(
            platform=args.platform,
            mode=args.mode,
            dry_run=args.dry_run,
            skip_publish_time_check=args.skip_publish_time_check,
            no_verify=args.no_verify,
            reason=args.reason,
            throttle_min=throttle_min,
            throttle_max=throttle_max,
        )
        outcome = publish_rows(rows, config, options=options, forced_keys=forced_keys)
        state = outcome.state
        checkpoint_disabled = outcome.checkpoint_disabled

        # U4-1/U4-2: the loop no longer raises SystemExit on a force-manifest
        # conflict, DependencyError, mid-run token drift, or AuthExpiredError; it
        # returns with the abort flag set. Raise the exit HERE in the shell (before
        # the complete-recon + epilogue) to preserve the prior immediate-abort
        # behavior (conflict->exit 1, the rest->exit 3; no complete-recon, epilogue
        # skipped, no stdout).
        if state.conflict_aborted:
            emit_error(
                state.conflict_error or "force-manifest conflict",
                exit_code=1,
            )
        if state.dependency_aborted:
            emit_error(
                state.dependency_error or "dependency error during publish",
                exit_code=3,
            )
        if state.auth_aborted:
            emit_error(
                state.auth_error or "auth expired during publish",
                exit_code=3,
                error_class=state.auth_error_class,
            )

        skipped = state.skipped_unreachable_count + state.skipped_quarantined_count + state.dedup_skip_count + state.dedup_hold_count
        emit_recon("info", command="publish-backlinks", phase="complete",
                   success=str(state.success_count), fail=str(state.fail_count),
                   skipped=str(skipped))

    # NB: conflict_aborted / dependency_aborted / auth_aborted already exited above
    # via emit_error (each raises SystemExit), so none reaches here; the epilogue
    # runs only on a non-aborted run.
    _publish_epilogue(
        state.outputs,
        rows,
        args,
        state.run_id,
        state.success_count,
        state.fail_count,
        state.skipped_unreachable_count,
        state.skipped_quarantined_count,
        state.publish_path_drift_count,
        state.dedup_skip_count,
        state.dedup_hold_count,
        checkpoint_disabled=checkpoint_disabled,
    )

    # W2: post-publish signal collection
    if getattr(args, "optimize", False) and state.success_count > 0:
        try:
            from backlink_publisher.optimization import OptimizationState
            from backlink_publisher.optimization.collector import collect_all_signals
            _state = OptimizationState()
            collected = collect_all_signals(_state, dry_run=args.dry_run)
            plat_count = len(collected.get("merged", {}))
            publish_logger.info(
                f"post-publish optimisation: collected signals for {plat_count} platforms"
            )
        except Exception as exc:
            publish_logger.warning(f"post-publish optimisation failed: {exc}")
