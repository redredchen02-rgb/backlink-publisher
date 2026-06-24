"""In-process publish runtime for the SDK (plan 2026-06-22-001 U5a-2).

Replaces the ``publish-backlinks`` subprocess for **API-tier** platforms: drives
the SystemExit-free :func:`publish_rows` engine in-process, serialized by a
process-level lock so two concurrent callers (scheduler autopilot job +
``/api/v1`` handler) can never overlap, with platform leases acquired/released in
``try/finally`` — idempotent for a live PID, so the long-lived Flask process
never self-locks and never accumulates ``atexit`` callbacks (the CLI shell's
``_acquire_publish_leases`` registers an ``atexit`` release that would only fire
at interpreter exit).

Browser-tier platforms are NOT run here — the SDK wrapper routes them to the CLI
subprocess so the long-lived Flask process never spawns Chrome (credential-
exposure containment, plan §"浏览器兜底"). As defense-in-depth, a browser-tier
platform that reaches this runtime is refused with a typed ``DependencyError``
result rather than silently driving a browser layer in-process.

SCOPE (plan line 163 — pre-filter ownership "实现时定"): this runtime replicates
the shell gates that change an observable ``PipeResult`` and are reachable from
SDK callers — payload validation (exit 2), the tier-1 dofollow filter, the
paused-platform partition, and per-platform adapter-setup verification (exit 3).
``enforce_precondition_or_exit`` (only active under ``BACKLINK_PUBLISHER_DEDUP_
ENFORCE=1``) is NOT replicated here — the per-row dedup gate inside
``publish_rows`` still runs; the back-catalogue precondition stays a CLI concern
(follow-on).
"""

from __future__ import annotations

import io
import json
import os
import threading
from typing import Any

from backlink_publisher._util.logger import publish_logger


# Module-level lock. Serializes ALL in-process publish runs: the scheduler
# autopilot job and the /api/v1 publish handler both go through publish()/
# publish_seed() and therefore share this one lock — they cannot interleave (no
# interleaved dispatch, no double-publish). Per plan U5 "并发串行化".
_PUBLISH_LOCK = threading.Lock()


class _PublishLeaseGuard:
    """Acquire/release platform publish leases for an in-process run.

    Unlike the CLI's ``_acquire_publish_leases`` (atexit-based, fits a one-shot
    process), this guard releases in a caller ``try/finally`` and is safe to call
    repeatedly: ``release()`` is idempotent and only deletes leases this guard
    actually took, ``acquire()`` rolls back partial acquisitions on contention.
    ``EventStore.acquire_lease`` takes over a lease already owned by the calling
    PID, so a live Flask PID never self-locks.
    """

    def __init__(self, platforms: set[str]) -> None:
        self._platforms = sorted(p for p in platforms if p)
        self._acquired: list[str] = []
        self._store: Any = None
        self._pid = os.getpid()

    def acquire(self) -> str | None:
        """Take a lease on every platform. Return ``None`` on success, or an
        operator-facing contention message when another **live** process holds
        one (mirrors the CLI's exit-3 abort text)."""
        if not self._platforms:
            return None
        from backlink_publisher.events.store import EventStore

        self._store = EventStore()
        for plat in self._platforms:
            if self._store.acquire_lease(plat, self._pid, ttl_seconds=3600):
                self._acquired.append(plat)
            else:
                details = self._store.get_lease(plat)
                owner = f"PID {details['owner_pid']}" if details else "unknown"
                self.release()  # roll back the leases already taken this attempt
                return (
                    f"error: another publish process ({owner}) is currently "
                    f"active for platform {plat!r}. Aborting to prevent "
                    "concurrent publishing conflicts."
                )
        return None

    def release(self) -> None:
        if self._store is None:
            return
        for plat in self._acquired:
            try:
                self._store.release_lease(plat, self._pid)
            except Exception as exc:  # noqa: BLE001 — release is best-effort
                publish_logger.warning(f"Failed to release lease on {plat!r}: {exc}")
        self._acquired = []


def _read_publish_rows_strict(jsonl_str: str) -> tuple[list[dict[str, Any]], Any]:
    """Strict JSONL read mirroring ``_util.jsonl.read_jsonl(strict=True)``.

    The CLI shell feeds publish input through ``read_jsonl`` (strict), which
    ``emit_error(exit_code=2)`` s on empty input, a malformed line, or a non-dict
    line (e.g. a top-level JSON array — the shape ``scheduler`` builds via
    ``json.dumps([seed])``). The old subprocess publish therefore returned a typed
    InputValidationError/exit-2 ``PipeResult`` for those inputs; the lenient
    ``_parse_jsonl_rows`` (used by plan/validate) would instead silently drop them.
    Returns ``(rows, None)`` on clean input or ``([], PipeResult)`` carrying the
    exact exit-2 message the CLI would have produced. Kept in sync with
    ``read_jsonl`` by construction (same messages, same line counting).
    """
    from .api import PipeResult

    _MAX_LINE_LENGTH = 65536  # mirror _util.jsonl.MAX_LINE_LENGTH

    def _err(message: str) -> tuple[list[dict[str, Any]], Any]:
        return [], PipeResult(
            success=False, error=message,
            error_class="InputValidationError", exit_code=2,
        )

    rows: list[dict[str, Any]] = []
    line_num = 0
    has_data = False
    for raw_line in (jsonl_str or "").split("\n"):
        line = raw_line.rstrip("\r")
        if not line:
            continue
        has_data = True
        line_num += 1
        if len(line) > _MAX_LINE_LENGTH:
            return _err(f"line {line_num}: exceeds maximum line length ({_MAX_LINE_LENGTH})")
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            return _err(f"line {line_num}: malformed JSON: {exc}")
        if not isinstance(obj, dict):
            return _err(f"line {line_num}: expected a JSON object, got {type(obj).__name__}")
        rows.append(obj)
    if not has_data:
        return _err("empty input: no JSONL rows provided")
    return rows, None


def _target_platforms(rows: list[dict[str, Any]], platform: str | None) -> set[str]:
    """The set of non-empty platforms a run will touch (explicit arg wins)."""
    return {(platform or r.get("platform", "")) for r in rows if (platform or r.get("platform", ""))}


def _validate_rows(rows: list[dict[str, Any]], platform: str | None) -> Any:
    """Mirror the CLI shell's per-row validation gate (exit 2).

    Returns a failed ``PipeResult`` (InputValidationError / exit 2) for the first
    offending row, or ``None`` when every row is publishable. Parity with
    ``_prepare_publish_rows``: ``reject_unsupported_platform`` then
    ``validate_publish_payload``.
    """
    from .api import PipeResult
    from backlink_publisher.schema import (
        reject_unsupported_platform,
        validate_publish_payload,
    )

    for idx, row in enumerate(rows, start=1):
        plat = platform or row.get("platform", "")
        platform_msg = reject_unsupported_platform(plat)
        if platform_msg is not None:
            return PipeResult(
                success=False,
                error=f"row {idx}: {platform_msg}",
                error_class="InputValidationError",
                exit_code=2,
            )
        errs = validate_publish_payload(row)
        if errs:
            for err in errs:
                publish_logger.warning(f"row {idx}: {err}")
            return PipeResult(
                success=False,
                error=f"row {idx}: payload validation failed",
                error_class="InputValidationError",
                exit_code=2,
            )
    return None


def _apply_tier1_filter(
    rows: list[dict[str, Any]], platform: str | None
) -> list[dict[str, Any]]:
    """Keep only dofollow (Tier-1) rows — mirrors the ``--tier-1`` shell gate."""
    from backlink_publisher.publishing.registry import dofollow_status

    kept: list[dict[str, Any]] = []
    for row in rows:
        plat = platform or row.get("platform", "")
        if dofollow_status(plat) is True:
            kept.append(row)
    return kept


def _verify_setup(platforms: set[str], config: Any) -> Any:
    """Mirror the CLI shell's per-platform ``verify_adapter_setup`` gate (exit 3).

    Returns a failed ``PipeResult`` (DependencyError / exit 3) when a platform's
    adapter setup is incomplete (e.g. missing credentials), or ``None`` when all
    are ready. Resolved from the ``publish_backlinks`` namespace so the same
    ``@patch(...publish_backlinks.verify_adapter_setup)`` seam used by the CLI
    golden fires for the in-process path too.
    """
    from .api import PipeResult
    from backlink_publisher._util.errors import DependencyError
    from backlink_publisher.cli.publish_backlinks import verify_adapter_setup
    from backlink_publisher.schema import supported_platforms

    supported = supported_platforms()
    for plat in sorted(platforms):
        if plat not in supported:
            continue
        try:
            verify_adapter_setup(plat, config)
        except DependencyError as exc:
            return PipeResult(
                success=False,
                error=str(exc),
                error_class="DependencyError",
                exit_code=3,
            )
    return None


def _build_pipe_result(outcome: Any, *, dry_run: bool) -> Any:
    """Map a :class:`PublishOutcome` to the ``PipeResult`` the subprocess path
    would have produced — exact parity with the CLI epilogue + ``_invoke_capture``.

    - Abort runs (conflict/auth/dependency) skip the epilogue → empty stdout, a
      typed error, exit 1/3/3.
    - Otherwise the pure ``_decide_publish_exit`` verdict drives stdout (only the
      successful rows are written, exactly as ``_publish_epilogue``) and the
      exit-code → error_class mapping mirrors ``emit_error`` /
      ``emit_envelope_and_exit`` (which ``_invoke_capture`` re-parses from stderr).
    """
    from .api import PipeResult
    from backlink_publisher._util.jsonl import write_jsonl
    from backlink_publisher.cli._publish_helpers import _decide_publish_exit

    state = outcome.state

    if state.conflict_aborted:
        return PipeResult(
            success=False,
            error=state.conflict_error or "force-manifest conflict",
            error_class="UsageError",
            exit_code=1,
        )
    if state.auth_aborted:
        return PipeResult(
            success=False,
            error=state.auth_error or "auth expired during publish",
            error_class=state.auth_error_class or "AuthExpiredError",
            exit_code=3,
        )
    if state.dependency_aborted:
        return PipeResult(
            success=False,
            error=state.dependency_error or "dependency error during publish",
            error_class="DependencyError",
            exit_code=3,
        )

    decision = _decide_publish_exit(
        state.outputs, dry_run=dry_run, dedup_hold_count=state.dedup_hold_count
    )
    buf = io.StringIO()
    if decision.successful:
        write_jsonl(decision.successful, buf)
    stdout = buf.getvalue()

    if decision.kind == "ok":
        return PipeResult(stdout=stdout, success=True, exit_code=0)

    # failed→4 / unverified→5 / all_held→3 / none_published→5. error_class mirrors
    # the CLI's stderr envelope: emit_envelope_and_exit names the class directly;
    # emit_error derives it from the exit code via _EXIT_CODE_CLASS_NAME.
    error_class = {
        "failed": "ExternalServiceError",       # emit_envelope_and_exit("ExternalServiceError", 4)
        "unverified": "InternalError",          # emit_envelope_and_exit("InternalError", 5)
        "all_held": "DependencyError",          # emit_error(exit 3) -> _EXIT_CODE_CLASS_NAME[3]
        "none_published": "InternalError",      # emit_error(exit 5) -> _EXIT_CODE_CLASS_NAME[5]
    }[decision.kind]
    return PipeResult(
        stdout=stdout,
        success=False,
        error=decision.message,
        error_class=error_class,
        exit_code=decision.exit_code,
    )


def publish_inprocess(
    plans_jsonl: str,
    *,
    platform: str | None,
    mode: str | None,
    tier_1: bool,
) -> Any:
    """In-process publish entry — returns a ``PipeResult`` byte-for-byte
    consistent with the old ``publish-backlinks`` subprocess for API-tier runs.

    Pre-loop gates mirror ``_prepare_publish_rows`` (validate → tier-1 → paused
    partition → lease → verify), then ``publish_rows`` runs the SystemExit-free
    loop, then the outcome is mapped to a ``PipeResult``. The process lock + lease
    bracket the dispatch so concurrent in-process callers serialize.
    """
    from .api import PipeResult
    from backlink_publisher.config import load_config
    from backlink_publisher.cli._publish_helpers import (
        _load_throttle_config,
        _partition_paused,
    )
    from backlink_publisher.cli.publish_backlinks._engine import (
        PublishOptions,
        publish_rows,
    )
    from backlink_publisher.publishing.reliability.policy import _is_browser_tier

    # Strict JSONL parse — empty / array / malformed input returns the same
    # exit-2 InputValidationError the CLI's read_jsonl would (parity, not the
    # lenient drop _parse_jsonl_rows does for plan/validate).
    rows, parse_err = _read_publish_rows_strict(plans_jsonl)
    if parse_err is not None:
        return parse_err

    # Defense-in-depth: a browser-tier platform must never drive a browser layer
    # inside the long-lived process. The SDK wrapper routes these to the CLI
    # subprocess; if one still arrives here, refuse with a typed result.
    for plat in _target_platforms(rows, platform):
        if _is_browser_tier(plat):
            return PipeResult(
                success=False,
                error=(
                    f"in-process publish refused for browser-tier platform "
                    f"{plat!r}; browser-backed publishing must run via the "
                    "publish-backlinks CLI subprocess"
                ),
                error_class="DependencyError",
                exit_code=3,
            )

    # Gate 1: per-row payload validation (exit 2).
    invalid = _validate_rows(rows, platform)
    if invalid is not None:
        return invalid

    # Gate 2: tier-1 dofollow filter. All-filtered mirrors the shell's exit-0
    # (nothing to publish is a clean no-op, not a failure).
    if tier_1:
        rows = _apply_tier1_filter(rows, platform)
        if not rows:
            return PipeResult(stdout="", success=True, exit_code=0)

    config = load_config()

    # Gate 3: drop operator-paused platforms (fail-safe). All-paused mirrors the
    # shell's exit-0.
    rows, paused = _partition_paused(rows, platform, config)
    for plat in paused:
        publish_logger.warning(
            f"publish-backlinks: skipping paused platform '{plat}' "
            "(resume via /ce:health)"
        )
    if not rows:
        return PipeResult(stdout="", success=True, exit_code=0)

    throttle_min, throttle_max = _load_throttle_config()
    options = PublishOptions(
        platform=platform,
        mode=mode,
        dry_run=False,
        skip_publish_time_check=False,
        no_verify=False,
        reason=None,
        throttle_min=throttle_min,
        throttle_max=throttle_max,
    )
    platforms = _target_platforms(rows, platform)

    with _PUBLISH_LOCK:
        guard = _PublishLeaseGuard(platforms)
        contended = guard.acquire()
        if contended is not None:
            return PipeResult(
                success=False,
                error=contended,
                error_class="DependencyError",
                exit_code=3,
            )
        try:
            # Gate 4: per-platform adapter setup (exit 3) — held under the lease,
            # mirroring the CLI order (lease acquired, then verify).
            setup_err = _verify_setup(platforms, config)
            if setup_err is not None:
                return setup_err
            outcome = publish_rows(
                rows, config, options=options, forced_keys=set()
            )
        finally:
            guard.release()

    return _build_pipe_result(outcome, dry_run=False)
