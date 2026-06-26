"""Publish-loop state and per-row execution kernel.

Unit 3b: the per-row loop body extracted from __init__.py::main() so that
the publish-backlinks dispatcher stays focused on setup and orchestration.

Seam binding strategy (D1): loop-called seams are resolved by a late
(in-function) re-import from the publish_backlinks package namespace at
call time, so every ``@patch("...publish_backlinks.X")`` test still fires:

    from backlink_publisher.cli.publish_backlinks import adapter_publish

This mirrors the proven cli/plan_backlinks/_engine.py pattern.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC
from typing import Any

from backlink_publisher._util.recon import emit_recon

_AUTH_ABORT = "auth_abort"  # sentinel returned to signal epilogue must be skipped
_ROW_CONTINUE = "continue"  # sentinel: the row was handled, advance to next
_DEP_ABORT = "dependency_abort"  # sentinel: DependencyError aborts the run (exit 3),
# epilogue skipped — same immediate-abort semantics as _AUTH_ABORT, but the
# SystemExit is now raised by the CLI shell (main), not inside the loop, so the
# engine is callable in-process and returns a typed outcome. (Plan 2026-06-22-001 U4-2)
_CONFLICT_ABORT = "conflict_abort"  # sentinel: a force-manifest conflict (force on a
# live "done" key, R11) aborts the run with exit 1 (UsageError, NOT 3). Only reachable
# with a non-empty forced_keys; the SystemExit is raised by the CLI shell. (U4-1)


@dataclass
class PublishOptions:
    """Typed publish-run configuration for the in-process engine (U4-1).

    Field names mirror the argparse Namespace attributes the publish loop reads,
    so a ``PublishOptions`` is a drop-in for ``args`` when passed into
    ``run_publish_loop`` (the loop only does attribute reads). ``main()`` builds
    one from its parsed args; an embedded SDK caller constructs it directly.

    SCOPE: ``publish_rows`` consumes ALREADY-FILTERED rows. The pre-loop gates
    (tier-1 dofollow filter, ``--preview-manifest``, ``--force-manifest``,
    paused-platform partition, dedup enforce-precondition, lease acquisition)
    stay in the CLI shell — they are NOT re-implemented here. ``forced_keys`` is
    passed to ``publish_rows`` separately (it is derived from a force manifest,
    a shell concern).
    """

    platform: str | None = None
    mode: str | None = None
    dry_run: bool = False
    skip_publish_time_check: bool = False
    no_verify: bool = False
    reason: str | None = None
    throttle_min: int = 60
    throttle_max: int = 300


@dataclass
class PublishRunState:
    """Loop-carried state for the fresh publish loop.

    Threaded into the per-row body rather than captured by a closure so
    the extracted helper stays module-level (the CC gate only sees
    top-level blocks) and the counters survive across iterations exactly
    as before.  Mirrors cli/_resume.py::_ResumeLoopState.

    Field semantics:
    - Counter fields are mutated in-place.
    - run_id is value-rebound (state.run_id = helper(...)); assign back at
      each rebinding site.
    - auth_aborted is set True on AuthExpiredError so main() can skip
      _publish_epilogue (R3a invariant).
    """

    # Accumulation outputs
    outputs: list[dict[str, Any]] = field(default_factory=list)
    # Counters
    success_count: int = 0
    fail_count: int = 0
    skipped_unreachable_count: int = 0
    skipped_quarantined_count: int = 0
    publish_path_drift_count: int = 0
    dedup_skip_count: int = 0
    dedup_hold_count: int = 0
    # Throttle-adjacency tracking
    last_medium_success_idx: int = -1
    # Checkpoint run identity (value-rebound, not mutated-in-place)
    run_id: str | None = None
    # Dedup warning deduplication per platform
    canary_warned: set[str] = field(default_factory=set)
    # R3a: signals main() to skip _publish_epilogue after AuthExpiredError
    auth_aborted: bool = False
    # U4-1: AuthExpiredError no longer SystemExits inside the loop (so the engine
    # is callable in-process); the message + real exception class name are carried
    # to the shell, which raises emit_error(exit_code=3, error_class=...).
    auth_error: str | None = None
    auth_error_class: str | None = None
    # U4-2: DependencyError aborts the run (exit 3); main() skips _publish_epilogue
    # and raises the exit-3 in the shell. dependency_error carries the message.
    # U4-1 also routes mid-run token-drift (rotated credentials) through this path.
    dependency_aborted: bool = False
    dependency_error: str | None = None
    # U4-1: force-manifest conflict (force on a live "done" key) aborts with exit 1
    # (NOT 3); main() raises emit_error(exit_code=1) in the shell. conflict_error
    # carries the message. Only set when forced_keys is non-empty.
    conflict_aborted: bool = False
    conflict_error: str | None = None


@dataclass
class PublishOutcome:
    """Typed result of an in-process publish run (U4-1).

    Wraps the loop-carried ``PublishRunState`` plus the ``checkpoint_disabled``
    flag (computed at checkpoint-creation time, not on the state) and the
    ``options`` used, and derives ``terminal_exit_code`` — the exit code the CLI
    shell would raise — WITHOUT any SystemExit. An embedded caller reads
    ``outputs`` (the successful rows) + ``terminal_exit_code`` (to map to HTTP /
    a return value); the CLI ``main()`` still drives the impure epilogue.
    """

    state: PublishRunState
    options: PublishOptions
    checkpoint_disabled: bool = False

    @property
    def outputs(self) -> list[dict[str, Any]]:
        return self.state.outputs

    @property
    def success_count(self) -> int:
        return self.state.success_count

    @property
    def fail_count(self) -> int:
        return self.state.fail_count

    @property
    def auth_aborted(self) -> bool:
        return self.state.auth_aborted

    @property
    def dependency_aborted(self) -> bool:
        return self.state.dependency_aborted

    @property
    def terminal_exit_code(self) -> int:
        """The exit code the CLI epilogue would raise for this run (0/3/4/5).

        Auth- and dependency-aborts skip the epilogue and exit 3 (the
        AuthExpiredError / DependencyError family). Otherwise the verdict comes
        from the SAME pure function the impure epilogue dispatches off
        (``_decide_publish_exit``), so an embedded caller and the CLI can never
        disagree about exit codes for the same output set.
        """
        if self.state.conflict_aborted:
            return 1
        if self.state.auth_aborted or self.state.dependency_aborted:
            return 3
        from backlink_publisher.cli._publish_helpers import _decide_publish_exit
        return _decide_publish_exit(
            self.state.outputs,
            dry_run=self.options.dry_run,
            dedup_hold_count=self.state.dedup_hold_count,
        ).exit_code


def run_publish_loop(
    rows: list[dict[str, Any]],
    args: Any,
    config: Any,
    state: PublishRunState,
    ts: str,
    banner_emit: Any,
    forced_keys: set,
    throttle_min: int,
    throttle_max: int,
    initial_token_revs: dict[str, int],
) -> None:
    """Drive the per-row publish loop, mutating state in place.

    Returns normally. Sets state.auth_aborted=True when an AuthExpiredError
    fires mid-loop; main() must skip _publish_epilogue in that case (R3a).
    """
    for row_idx, row in enumerate(rows):
        result = _publish_one_row(
            row_idx, row, state, args, config, ts, banner_emit,
            forced_keys, throttle_min, throttle_max, initial_token_revs,
        )
        if result == _AUTH_ABORT:
            state.auth_aborted = True
            return
        if result == _DEP_ABORT:
            state.dependency_aborted = True
            return
        if result == _CONFLICT_ABORT:
            state.conflict_aborted = True
            return


def publish_rows(
    rows: list[dict[str, Any]],
    config: Any,
    *,
    options: PublishOptions,
    forced_keys: set | None = None,
) -> PublishOutcome:
    """In-process publish entry point — NEVER raises SystemExit (U4-1).

    Creates the resume checkpoint (fail-soft), runs the per-row publish loop, and
    returns a typed PublishOutcome. The caller decides what to do with the
    verdict: the CLI shell (``main``) drives the impure epilogue (stdout +
    SystemExit); an embedded caller reads ``outcome.outputs`` +
    ``outcome.terminal_exit_code``.

    ``rows`` must be ALREADY FILTERED (see PublishOptions — the pre-loop gates
    live in the CLI shell). Concurrency safety for concurrent in-process callers
    (scheduler vs /api/v1) is the caller's responsibility via a process-level
    publish lock (plan U5); ``publish_rows`` itself holds no such lock.
    """
    from datetime import datetime

    from backlink_publisher._util.logger import publish_logger
    from backlink_publisher.cli._publish_helpers import _make_banner_emit
    from backlink_publisher.config import snapshot_token_revs

    from ... import checkpoint

    if forced_keys is None:
        forced_keys = set()

    run_id: str | None = None
    checkpoint_disabled = False
    if not options.dry_run:
        try:
            run_id, _ = checkpoint.create_checkpoint(
                rows,
                platform=options.platform,
                mode=options.mode or "draft",
                flags={"skip_publish_time_check": options.skip_publish_time_check},
            )
            publish_logger.info(f"publish-backlinks: run_id={run_id}")
        except Exception as exc:
            checkpoint_disabled = True
            publish_logger.warning(
                f"[WARN] checkpoint not created — this run cannot be resumed: {exc}"
            )

    state = PublishRunState(run_id=run_id)
    ts = datetime.now(UTC).isoformat()
    banner_emit = _make_banner_emit()
    initial_token_revs = snapshot_token_revs()

    run_publish_loop(
        rows, options, config, state, ts, banner_emit,
        forced_keys, options.throttle_min, options.throttle_max, initial_token_revs,
    )
    return PublishOutcome(
        state=state, options=options, checkpoint_disabled=checkpoint_disabled,
    )


def _publish_one_row(  # noqa: C901 -- per-row publish gate; real logic in sub-helpers below
    row_idx: int,
    row: dict[str, Any],
    state: PublishRunState,
    args: Any,
    config: Any,
    ts: str,
    banner_emit: Any,
    forced_keys: set,
    throttle_min: int,
    throttle_max: int,
    initial_token_revs: dict[str, int],
) -> str | None:
    """Handle one row in the fresh publish loop.

    Returns _AUTH_ABORT when an AuthExpiredError requires aborting the run,
    _ROW_CONTINUE (or None implicitly) otherwise.
    """
    # ── Late re-import of loop-called seams from the publish_backlinks namespace.
    # Tests patch these at backlink_publisher.cli.publish_backlinks.X; re-reading
    # the name here at call time means every @patch(...publish_backlinks.X) fires.
    from datetime import datetime

    from backlink_publisher._util.errors import (
        AuthExpiredError,
        BannerUploadError,
        ContentRejectedError,
        DependencyError,
        ExternalServiceError,
    )
    from backlink_publisher._util.logger import publish_logger
    from backlink_publisher.cli._dedup_gate import (
        gate_with_force,
        record_done,
        record_failure,
    )

    # ── Non-seam collaborators — import from their real modules. ─────────────
    from backlink_publisher.cli._publish_helpers import (
        _build_failure_row,
        _build_skip_row,
        _canary_gate,
        _check_row_reachability,
        _check_token_drift,
        _do_verify,
        _error_class,
        _medium_throttle_sleep,
        _record_publish_failure,
        _record_publish_path,
        _try_update_ckpt_failed,
    )
    from backlink_publisher.cli.publish_backlinks import (
        _handle_auth_expired,
        adapter_publish,
        policy_enabled,
        publish_with_policy,
    )
    from backlink_publisher.schema import supported_platforms

    from ... import checkpoint

    _medium_throttle_sleep(
        row_idx, state.last_medium_success_idx,
        args.platform or row.get("platform", ""),
        throttle_min, throttle_max,
        dry_run=args.dry_run,
    )

    platform = args.platform or row.get("platform", "")
    mode = args.mode or row.get("publish_mode", "draft")
    target_domain = row.get("target_url", row.get("main_domain", "")).split("//")[-1].split("/")[0] if row.get("target_url", row.get("main_domain", "")) else ""
    emit_recon("info", command="publish-backlinks", phase="row",
               row=str(row_idx + 1), platform=platform, target=target_domain)

    canary_skip, canary_reason = _canary_gate(platform, warned=state.canary_warned)
    if canary_skip:
        row_id = row.get("id", "")
        publish_logger.warn(
            f"[publish-backlinks] row_id={row_id} platform={platform} "
            f"status=skipped_quarantined — {canary_reason}"
        )
        state.skipped_quarantined_count += 1
        return _ROW_CONTINUE

    if not args.dry_run and not args.skip_publish_time_check:
        ok, failing_url = _check_row_reachability(row)
        if not ok:
            row_id = row.get("id", "")
            publish_logger.warn(
                f"[publish-backlinks] row_id={row_id} "
                f"status=skipped_unreachable url={failing_url}"
            )
            state.outputs.append(_build_failure_row(
                "skipped_unreachable", row, platform,
                f"target unreachable at publish-time: {failing_url}",
                ts,
                failing_url=failing_url,
            ))
            state.skipped_unreachable_count += 1
            return _ROW_CONTINUE

    if platform not in supported_platforms():
        state.outputs.append(_build_failure_row(
            "failed", row, platform,
            f"unsupported platform: {platform}",
            ts, adapter=platform,
        ))
        state.fail_count += 1
        return _ROW_CONTINUE

    if args.dry_run:
        result = adapter_publish(
            payload={**row, "platform": platform},
            mode=mode,
            config=config,
            dry_run=True,
        )
        state.outputs.append({
            "id": row.get("id", ""),
            "platform": platform,
            "status": result.status,
            "title": row.get("title", ""),
            "draft_url": result.draft_url,
            "published_url": result.published_url,
            "created_at": ts,
            "adapter": result.adapter,
            "error": None,
            "_dry_run": True,
            "_command": result._command,
        })
        state.success_count += 1
        publish_logger.debug(
            f"dry-run: {platform} id={row.get('id', '')}",
            extra={"id": row.get("id"), "platform": platform},
        )
        return _ROW_CONTINUE

    publish_logger.info(
        f"publishing: {platform} id={row.get('id', '')}",
        extra={"id": row.get("id"), "platform": platform, "mode": mode},
    )

    # U4-1: mid-run credential rotation aborts the run without SystemExit-ing
    # inside the loop (keeps publish_rows callable in-process). Same exit-3 abort
    # semantics as DependencyError — main raises emit_error(3) in the shell.
    drift_msg = _check_token_drift(initial_token_revs, raises=False)
    if drift_msg:
        state.dependency_error = drift_msg
        return _DEP_ABORT

    verdict, drec = gate_with_force(
        row, platform, run_id=state.run_id, forced_keys=forced_keys, reason=args.reason
    )
    if verdict == "conflict":
        # U4-1: force on a live "done" key (R11). gate_with_force no longer
        # SystemExits; abort via a typed sentinel so publish_rows stays callable
        # in-process. main maps conflict_aborted -> emit_error(exit_code=1).
        state.conflict_error = (
            f"force-manifest conflict: {platform} key is already published "
            "(done); refusing to re-publish — use --forget if truly intended"
        )
        return _CONFLICT_ABORT
    if verdict == "skip":
        state.outputs.append(_build_skip_row(
            row, platform, drec.live_url if drec else None, ts
        ))
        state.dedup_skip_count += 1
        publish_logger.info(
            f"dedup skip (already published): {platform} id={row.get('id', '')}",
            extra={"id": row.get("id"), "platform": platform},
        )
        return _ROW_CONTINUE
    if verdict == "hold":
        state.dedup_hold_count += 1
        publish_logger.warn(
            f"dedup hold (uncertain/in-flight): {platform} id={row.get('id', '')}",
            extra={"id": row.get("id"), "platform": platform},
        )
        return _ROW_CONTINUE

    try:
        if policy_enabled():
            result = publish_with_policy(
                platform,
                payload=row,
                config=config,
                mode=mode,
                banner_emit=banner_emit,
            )
        else:
            result = adapter_publish(
                payload={**row, "platform": platform},
                mode=mode,
                config=config,
                dry_run=False,
                banner_emit=banner_emit,
            )
    except AuthExpiredError as exc:
        # U4-1: run the side effects (channel flip + checkpoint mark + log) but do
        # NOT SystemExit inside the loop; capture the message + real class so main
        # raises emit_error(exit_code=3) in the shell (R3a epilogue-skip preserved).
        record_failure(row, platform, error_class="auth_expired", run_id=state.run_id)
        _handle_auth_expired(exc, state.run_id, row, publish_logger, raises=False)
        state.auth_error = str(exc)
        state.auth_error_class = type(exc).__name__
        return _AUTH_ABORT
    except BannerUploadError as exc:
        state.fail_count += 1
        state.run_id = _record_publish_failure(
            state.outputs, row, platform, ts, state.run_id, exc,
            "banner_upload", f"banner upload failed: {exc}",
        )
        return _ROW_CONTINUE
    except ContentRejectedError as exc:
        state.fail_count += 1
        state.run_id = _record_publish_failure(
            state.outputs, row, platform, ts, state.run_id, exc,
            "content_rejected", f"content rejected: {exc}",
        )
        return _ROW_CONTINUE
    except DependencyError as exc:
        # U4-2: record the dedup failure then abort the run via a typed sentinel
        # instead of raising SystemExit inside the loop. main() (the CLI shell)
        # maps dependency_aborted -> emit_error(exit_code=3); an in-process caller
        # reads the typed outcome. Immediate-abort semantics (exit 3, epilogue
        # skipped, no stdout) are preserved — same as _AUTH_ABORT.
        record_failure(row, platform, error_class="dependency", run_id=state.run_id)
        state.dependency_error = str(exc)
        return _DEP_ABORT
    except ExternalServiceError as exc:
        state.fail_count += 1
        state.run_id = _record_publish_failure(
            state.outputs, row, platform, ts, state.run_id, exc,
            _error_class(exc), f"service error: {exc}",
        )
        return _ROW_CONTINUE
    except Exception as exc:
        state.fail_count += 1
        state.run_id = _record_publish_failure(
            state.outputs, row, platform, ts, state.run_id, exc,
            "unexpected", f"unexpected error: {exc}",
        )
        return _ROW_CONTINUE

    state.outputs.append(result.to_publish_output(row, ts))
    if result.error:
        state.fail_count += 1
        record_failure(row, platform, error_class=None, run_id=state.run_id)
        _ckpt_error_class = (
            checkpoint.POLICY_SKIP
            if result.status in ("skipped_policy", "skipped_circuit_open")
            else "unexpected"
        )
        state.run_id = _try_update_ckpt_failed(
            state.run_id, row.get("id", ""), str(result.error), _ckpt_error_class
        )
    else:
        state.success_count += 1
        if result.post_publish_delay_seconds > 0:
            state.last_medium_success_idx = row_idx

        state.publish_path_drift_count += _record_publish_path(platform, result, row)

        verify_ok, verify_reason = _do_verify(
            args.no_verify, args.dry_run, result, row
        )
        if not verify_ok:
            state.outputs[-1]["status"] += "_unverified"
            publish_logger.warn(
                f"verification failed: id={row.get('id', '')} reason={verify_reason}",
                extra={"id": row.get("id"), "adapter": result.adapter},
            )

        record_done(
            row, platform,
            live_url=(result.published_url or result.draft_url) or None,
            verify_ok=verify_ok,
            run_id=state.run_id,
        )

        if state.run_id is not None:
            try:
                checkpoint.update_item(
                    state.run_id, row.get("id", ""), "done",
                    published_url=result.published_url,
                    article_urls=[u for u in (result.published_url, result.draft_url) if u],
                    adapter=result.adapter,
                    completed_at=datetime.now(UTC).isoformat(),
                    verified=verify_ok,
                )
            except Exception as ckpt_exc:
                publish_logger.warning(f"[WARN] checkpoint update failed: {ckpt_exc}")
                state.run_id = None
        publish_logger.info(
            f"published: id={row.get('id', '')} status={result.status}",
            extra={"id": row.get("id"), "status": result.status},
        )

    row_status = "success" if not result.error else "fail"
    emit_recon("info", command="publish-backlinks", phase="row_result",
               row=str(row_idx + 1), status=row_status, platform=platform)
    return None
