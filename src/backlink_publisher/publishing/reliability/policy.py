"""Coordinated publish policy layer — Plan 2026-05-28-001 Units 2–3.

``publish_with_policy`` is the single entry point.  It wraps ``adapter_publish``
(the real dispatch) for browser-tier channels with:

1. **Health gate** — checks ``channel_status.get_status(platform)``; non-"bound"
   status returns a ``skipped_policy`` sentinel without dispatching.
   Browser-tier only — API-tier platforms bypass the health gate.

2. **Circuit breaker** — checks per-platform flock-based state; tripped circuit
   returns a ``skipped_circuit_open`` sentinel without dispatching.
   Applies to ALL platforms (Phase 3). Supports CLOSED, OPEN, and HALF_OPEN states.

3. **Observability** — emits a structured ``publish_attempt`` event on every
   dispatch outcome (success, auth_expired, auth_banned, external_error).

Non-browser-tier channels bypass the health gate but still go through the circuit
breaker and event emission.

**Activation flag**: set ``BACKLINK_PUBLISHER_RELIABILITY_POLICY_ENABLED=1`` to
activate the full policy (health gate + circuit breaker).  When unset the function
is a transparent passthrough — identical to calling ``adapter_publish`` directly.
This mirrors the PR #279 observe → enforce rollout pattern.

**Dry-run callers must NOT route through this function** — the dry-run call at
``publish_backlinks.py:233`` remains a direct ``adapter_publish(…, dry_run=True)``
call.  This function ignores ``dry_run=True`` if somehow called with it, but the
convention is: callers are responsible for not routing dry-runs here.

Plan: docs/plans/2026-05-28-001-feat-publish-reliability-policy-plan.md
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any, Callable

from backlink_publisher._util.errors import AuthExpiredError, ExternalServiceError
from backlink_publisher._util.logger import opencli_logger as _log
from backlink_publisher.publishing.adapters import publish as adapter_publish
from backlink_publisher.publishing.adapters.base import AdapterResult

from .circuit import (
    circuit_status,
    is_ban_signal,
    is_degraded,
    is_tripped,
    record_success,
    trip,
)
from .events import Outcome, emit_attempt, now_ms

if TYPE_CHECKING:
    from backlink_publisher.config import Config


# Browser-tier channels activated in v1 (Plan 2026-05-28-001 Key Decision 1)
_BROWSER_TIER: frozenset[str] = frozenset({"medium", "velog", "devto", "mastodon"})

#: Activation env var — observe→enforce rollout (Plan 2026-06-15-001), mirrors the
#: BACKLINK_PUBLISHER_DEDUP_ENFORCE pattern from PR #279. Resolved by ``policy_mode()``:
#:   unset / unrecognized → "off"     (transparent passthrough; default)
#:   "observe"            → "observe" (run gates, EMIT would-skip events, still dispatch)
#:   "1" / "enforce"      → "enforce" (actually skip on blocked gate / open circuit)
POLICY_ENV = "BACKLINK_PUBLISHER_RELIABILITY_POLICY_ENABLED"

#: Per-channel enforce allowlist (Plan 2026-06-15-006 Unit 7). Comma-separated
#: channel names; in ``enforce`` mode ONLY listed channels actually skip — every
#: other channel falls back to observe behavior (measure, dispatch anyway). Ships
#: EMPTY (unset) → ``enforce`` skips NO channel, so flipping ``POLICY_ENV`` to
#: enforce is a no-op until the operator adds a channel here (after observe data
#: justifies it, per Unit 4 readiness). Re-read per call so removing a channel
#: (rollback) takes effect on the next publish run without a restart.
ENFORCE_ALLOWLIST_ENV = "BACKLINK_PUBLISHER_RELIABILITY_ENFORCE_CHANNELS"

#: Phase 3 — consecutive-failure trip thresholds (configurable). These are the
#: ONLY env vars that gate the live publish trip path: ``publish_with_policy``
#: counts consecutive non-ban ``AuthExpiredError`` / ``ExternalServiceError`` in
#: the health-store ``consecutive_failures`` field and trips ``circuit.trip``
#: when the count reaches the matching threshold below.
_AUTH_THRESHOLD_ENV = "BACKLINK_PUBLISHER_CIRCUIT_AUTH_THRESHOLD"
_ERROR_THRESHOLD_ENV = "BACKLINK_PUBLISHER_CIRCUIT_ERROR_THRESHOLD"
_DEFAULT_AUTH_THRESHOLD = 3
_DEFAULT_ERROR_THRESHOLD = 5

#: 006-U1: legacy circuit-layer knob. ``circuit._consecutive_errors_threshold``
#: reads this env, but its sole consumer ``circuit.trip_on_error`` has **no src
#: caller** on the ``publish_with_policy`` trip path (verified 2026-06-05; only a
#: direct unit test invokes it) — and it increments a *different* counter (the
#: circuit state-file ``consecutive_errors`` field, not the health-store
#: ``consecutive_failures`` the live path uses). So setting this env does nothing
#: to live trip behavior. We warn once when it is set so the dead knob never
#: "silently does nothing" (success criterion U1). The active knobs are
#: ``_ERROR_THRESHOLD_ENV`` / ``_AUTH_THRESHOLD_ENV`` above.
_LEGACY_CONSECUTIVE_ENV = "BACKLINK_PUBLISHER_CIRCUIT_CONSECUTIVE_ERRORS"
_legacy_consecutive_warned = False


def _warn_legacy_consecutive_env_once() -> None:
    """Emit a one-shot deprecation warning if the dead circuit knob is set.

    Idempotent via the module-level ``_legacy_consecutive_warned`` flag so a
    long publish run does not flood stderr. Tests reset the flag to re-arm it.
    """
    global _legacy_consecutive_warned
    if _legacy_consecutive_warned:
        return
    if os.environ.get(_LEGACY_CONSECUTIVE_ENV) is not None:
        _legacy_consecutive_warned = True
        _log.warning(
            f"{_LEGACY_CONSECUTIVE_ENV} is set but has NO effect on the live "
            "publish trip path (it is read only by circuit.trip_on_error, which "
            "nothing on the publish path calls). The active trip thresholds are "
            f"{_ERROR_THRESHOLD_ENV} (default {_DEFAULT_ERROR_THRESHOLD}) and "
            f"{_AUTH_THRESHOLD_ENV} (default {_DEFAULT_AUTH_THRESHOLD}).",
            legacy_env=_LEGACY_CONSECUTIVE_ENV,
        )


def policy_mode() -> str:
    """Resolve the reliability-policy rollout mode from ``POLICY_ENV``.

    Returns one of ``"off"`` | ``"observe"`` | ``"enforce"`` (observe→enforce
    rollout, Plan 2026-06-15-001):

    * ``off`` (default / unrecognized) — transparent passthrough, no gating, no
      events. Identical to calling ``adapter_publish`` directly.
    * ``observe`` — run the health-gate + circuit checks and EMIT what they would
      do (``would_skip_policy`` / ``would_skip_circuit`` events) plus full trip
      accounting, but STILL dispatch (never actually skips). Lets operators see
      how often enforcement would fire before flipping it on.
    * ``enforce`` — actually skip on a blocked health gate / open circuit.

    Back-compat: the historical ``"1"`` value maps to ``enforce``.
    """
    val = (os.environ.get(POLICY_ENV) or "").strip().lower()
    if val in ("1", "enforce"):
        return "enforce"
    if val == "observe":
        return "observe"
    return "off"


def policy_enabled() -> bool:
    """True when the policy layer runs at all (observe OR enforce).

    The publish-loop seam routes through ``publish_with_policy`` whenever this is
    True; observe mode needs that routing to gather data, so it counts as enabled.
    """
    return policy_mode() != "off"


def enforce_allowlist() -> frozenset[str]:
    """Channels actually enforced in ``enforce`` mode (Plan 2026-06-15-006 U7).

    Read per call (no caching) from ``ENFORCE_ALLOWLIST_ENV`` so a rollback (remove
    a channel) takes effect on the next publish run. Empty when unset → enforce
    mode skips nothing.
    """
    raw = os.environ.get(ENFORCE_ALLOWLIST_ENV) or ""
    return frozenset(c.strip() for c in raw.split(",") if c.strip())


def _enforcing_for(platform: str) -> bool:
    """True only when mode is ``enforce`` AND *platform* is in the allowlist.

    A channel in enforce mode but not allowlisted falls back to observe behavior
    (measure would-skips, dispatch anyway), so enforce rolls out one channel at a
    time instead of flipping every channel at once.
    """
    return policy_mode() == "enforce" and platform in enforce_allowlist()


def _is_browser_tier(platform: str) -> bool:
    return platform in _BROWSER_TIER


def _threshold(env_name: str, default: int) -> int:
    try:
        return max(1, int(os.environ.get(env_name, default)))
    except (ValueError, TypeError):
        return default


def _reset_failures(platform: str, config: Config) -> None:
    """Reset the consecutive-failure counter (on success or after a trip)."""
    try:
        from backlink_publisher.health.persistence import locked_store

        locked_store.update(
            platform, lambda e: {**e, "consecutive_failures": 0}, config
        )
    except Exception:  # noqa: BLE001 — health-store faults never block publishing
        pass


def _record_failure_and_maybe_trip(
    platform: str, config: Config, threshold: int
) -> None:
    """Increment the consecutive-failure counter; trip the circuit at *threshold*.

    Counts in ``LockedHealthStore.consecutive_failures`` (Phase 1's field, now
    live). On reaching *threshold* the circuit trips and the counter resets so
    the post-cooldown window starts fresh. Fail-soft: a health-store error is
    swallowed so a transient fault never escalates a single failure into a trip.
    """
    try:
        from backlink_publisher.health.persistence import locked_store

        locked_store.update(
            platform,
            lambda e: {**e, "consecutive_failures": int(e.get("consecutive_failures", 0)) + 1},
            config,
        )
        count = locked_store.get(platform, config)["consecutive_failures"]
    except Exception:  # noqa: BLE001
        return
    if count >= threshold:
        trip(platform, config)
        _reset_failures(platform, config)
        # Reaching the threshold is a transition into degraded (the counter was
        # reset after any prior trip), so this is not per-run spam.
        _record_decision(platform, "degraded", policy_mode(), reason="circuit_trip")


def _record_decision(
    platform: str, decision: str, mode: str, reason: str | None = None
) -> None:
    """Best-effort: persist a ``reliability.decision`` to events.db (Units 2 & 6).

    Makes observe would-skips, enforce skips, and degraded-entry alerts queryable
    for readiness (Unit 4) / the rollout panel (Unit 5) / the external alert stack
    (Unit 6). Never raises — events.db faults must not block a publish, mirroring
    ``emit_attempt``'s never-raise contract. Runs on a fresh ``EventStore``
    connection at the dispatch seam (NOT inside a projector reducer transaction),
    so it cannot trigger the WAL nested-connection deadlock.
    """
    try:
        from backlink_publisher.events.store import EventStore
        from .events_store import append_reliability_decision

        append_reliability_decision(
            EventStore(), platform=platform, decision=decision, mode=mode, reason=reason
        )
    except Exception:  # noqa: BLE001 — events.db faults never block publishing
        pass


def _enforce_circuit_skip(platform: str, config: Config) -> AdapterResult | None:
    """Enforce-mode circuit decision (Plan 2026-06-15-006 U8).

    Returns a ``skipped_circuit_open`` result ONLY for a genuine OPEN trip. Returns
    ``None`` (caller falls through to dispatch) otherwise:
    - ``unreadable`` (corrupt/malformed state) → degrade + record
      ``circuit_state_unreadable`` (don't silently skip every channel);
    - ``half-open`` / ``closed`` → the entry cooled down or was reset between the
      gate's ``is_tripped`` read and this read (a cooldown-boundary straddle); the
      channel should be allowed through, not skipped.
    """
    status = circuit_status(platform, config)
    if status == "open":
        _record_decision(platform, "skipped_circuit_open", "enforce")
        return AdapterResult(
            status="skipped_circuit_open",
            adapter="policy",
            platform=platform,
            error=f"circuit open for {platform}",
        )
    if status == "unreadable":
        _record_decision(
            platform, "circuit_state_unreadable", "enforce", reason="degrade_to_observe"
        )
    return None


def publish_with_policy(
    platform: str,
    payload: dict[str, Any],
    config: Config,
    *,
    mode: str = "draft",
    banner_emit: Callable[[str, dict[str, Any]], None] | None = None,
) -> AdapterResult:
    """Policy-wrapped dispatch for ALL channels (Stage 1 extension).

    Extended from browser-tier-only to all adapters (Plan 2026-05-28-001).
    Non-browser-tier platforms still get circuit breaker + events; health gate
    is browser-scoped only (API-tier platforms have no channel status binding).

    This function must NOT be called with dry-run payloads — the dry-run seam in
    ``publish_backlinks.py:233`` remains a direct ``adapter_publish(..., dry_run=True)``
    call. This function ignores dry_run=True if somehow called, but the convention
    is: callers are responsible for not routing dry-runs here.
    """
    full_payload = {**payload, "platform": platform}

    # Passthrough when policy is disabled (default).
    if not policy_enabled():
        return adapter_publish(
            payload=full_payload,
            mode=mode,
            config=config,
            dry_run=False,
            banner_emit=banner_emit,
        )

    # --- Policy active: observe OR enforce -------------------------------------
    # In ``observe`` the gates below EMIT what they would do but do NOT skip; in
    # ``enforce`` they actually skip — but ONLY for allowlisted channels (U7). A
    # non-allowlisted channel under enforce falls back to observe behavior, so the
    # rollout is per-channel.
    enforcing = _enforcing_for(platform)

    # 006-U1: surface the dead consecutive-errors knob (one-shot) before any
    # trip bookkeeping, so an operator who set it learns it has no effect here.
    _warn_legacy_consecutive_env_once()

    # 1. Health gate — browser-tier only. The "bound" status tracks a browser
    #    session binding that API-tier platforms do not have, so applying it to
    #    them would skip every non-browser publish. (Phase 3 keeps the health
    #    gate browser-scoped while the circuit below covers all platforms.)
    if _is_browser_tier(platform):
        try:
            from webui_store.channel_status import get_status

            status_info = get_status(platform)
            channel_status = status_info.get("status", "unbound")
        except Exception:  # noqa: BLE001
            channel_status = "unbound"

        if channel_status != "bound":
            if enforcing:
                _record_decision(platform, "skipped_policy", "enforce")
                return AdapterResult(
                    status="skipped_policy",
                    adapter="policy",
                    platform=platform,
                    error=f"channel not bound (status={channel_status!r})",
                )
            # observe: record the would-be skip, then dispatch anyway.
            emit_attempt(
                platform, Outcome.WOULD_SKIP_POLICY, 0.0,
                error_class=f"channel_status={channel_status}",
            )
            _record_decision(platform, "would_skip_policy", "observe")

    # 2. Circuit breaker — ALL platforms (Phase 3 U9; fail-CLOSED: corrupt state
    #    → is_tripped returns True). Handles CLOSED, OPEN, and HALF_OPEN states.
    if is_tripped(platform, config):
        if enforcing:
            skip = _enforce_circuit_skip(platform, config)
            if skip is not None:
                return skip
            # else: state unreadable → degraded to observe; fall through to dispatch.
        else:
            # observe: record the would-be skip, then fall through to dispatch.
            emit_attempt(platform, Outcome.WOULD_SKIP_CIRCUIT, 0.0)
            _record_decision(platform, "would_skip_circuit", "observe")

    # 3. Dispatch + observe + consecutive-failure trip accounting.
    t0 = now_ms()
    try:
        result = adapter_publish(
            payload=full_payload,
            mode=mode,
            config=config,
            dry_run=False,
            banner_emit=banner_emit,
        )
        record_success(platform, config)
        emit_attempt(platform, Outcome.SUCCESS, now_ms() - t0)
        _reset_failures(platform, config)
        return result

    except AuthExpiredError as exc:
        duration = now_ms() - t0
        if is_ban_signal(exc):
            # Ban/suspend → trip immediately (v1 behavior).
            # Transition check BEFORE tripping: only alert on entering degraded,
            # not on every re-dispatch into an already-degraded channel. Use
            # is_degraded (raw tripped flag) NOT is_tripped — the latter returns
            # False in HALF_OPEN, which would re-alert every cooldown cycle.
            newly_degraded = not is_degraded(platform, config)
            trip(platform, config)
            _reset_failures(platform, config)
            emit_attempt(platform, Outcome.AUTH_BANNED, duration)
            if newly_degraded:
                _record_decision(platform, "degraded", policy_mode(), reason="ban")
        else:
            # Plain session expiry → trip only after N consecutive (U10).
            emit_attempt(platform, Outcome.AUTH_EXPIRED, duration)
            _record_failure_and_maybe_trip(
                platform, config, _threshold(_AUTH_THRESHOLD_ENV, _DEFAULT_AUTH_THRESHOLD)
            )
        raise

    except ExternalServiceError as exc:
        # Upstream error → trip after N consecutive (U11).
        emit_attempt(platform, Outcome.EXTERNAL_ERROR, now_ms() - t0)
        _record_failure_and_maybe_trip(
            platform, config, _threshold(_ERROR_THRESHOLD_ENV, _DEFAULT_ERROR_THRESHOLD)
        )
        raise

    except Exception as exc:
        emit_attempt(
            platform, Outcome.TRANSIENT, now_ms() - t0, error_class=type(exc).__name__
        )
        raise
