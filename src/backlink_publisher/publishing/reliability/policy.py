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
from backlink_publisher.publishing.adapters import publish as adapter_publish
from backlink_publisher.publishing.adapters.base import AdapterResult

from .circuit import (
    is_ban_signal,
    is_tripped,
    record_success,
    trip,
)
from .events import Outcome, emit_attempt, now_ms

if TYPE_CHECKING:
    from backlink_publisher.config import Config


# Browser-tier channels activated in v1 (Plan 2026-05-28-001 Key Decision 1)
_BROWSER_TIER: frozenset[str] = frozenset({"medium", "velog", "devto", "mastodon"})

#: Activation env var — mirrors BACKLINK_PUBLISHER_DEDUP_ENFORCE from PR #279.
#: When unset / not "1": publish_with_policy is a transparent passthrough.
#: When "1": full policy (health gate + circuit breaker + events) is active.
POLICY_ENV = "BACKLINK_PUBLISHER_RELIABILITY_POLICY_ENABLED"

#: Phase 3 — consecutive-failure trip thresholds (configurable). After this many
#: consecutive non-ban AuthExpiredError / ExternalServiceError, the circuit trips.
_AUTH_THRESHOLD_ENV = "BACKLINK_PUBLISHER_CIRCUIT_AUTH_THRESHOLD"
_ERROR_THRESHOLD_ENV = "BACKLINK_PUBLISHER_CIRCUIT_ERROR_THRESHOLD"
_DEFAULT_AUTH_THRESHOLD = 3
_DEFAULT_ERROR_THRESHOLD = 5


def policy_enabled() -> bool:
    """True iff the operator opted into the reliability policy layer."""
    return os.environ.get(POLICY_ENV) == "1"


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

    # --- Policy active (BACKLINK_PUBLISHER_RELIABILITY_POLICY_ENABLED=1) ---

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
            return AdapterResult(
                status="skipped_policy",
                adapter="policy",
                platform=platform,
                error=f"channel not bound (status={channel_status!r})",
            )

    # 2. Circuit breaker — ALL platforms (Phase 3 U9; fail-CLOSED: corrupt state
    #    → is_tripped returns True). Handles CLOSED, OPEN, and HALF_OPEN states.
    if is_tripped(platform, config):
        return AdapterResult(
            status="skipped_circuit_open",
            adapter="policy",
            platform=platform,
            error=f"circuit open for {platform}",
        )

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
            trip(platform, config)
            _reset_failures(platform, config)
            emit_attempt(platform, Outcome.AUTH_BANNED, duration)
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
