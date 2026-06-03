"""Coordinated publish policy layer — Plan 2026-05-28-001 Units 2–3.

``publish_with_policy`` is the single entry point.  It wraps ``adapter_publish``
(the real dispatch) for ALL channels with:

1. **Health gate** — checks ``channel_status.get_status(platform)``; non-"bound"
   status returns a ``skipped_policy`` sentinel without dispatching.

2. **Circuit breaker** — checks per-platform flock-based state; tripped circuit
   returns a ``skipped_circuit_open`` sentinel without dispatching.
   Supports CLOSED, OPEN, and HALF_OPEN states.

3. **Observability** — emits a structured ``publish_attempt`` event on every
   dispatch outcome (success, auth_expired, auth_banned, external_error,
   rate_limited, http_error).

**Activation flag**: set ``BACKLINK_PUBLISHER_RELIABILITY_POLICY_ENABLED=1`` to
activate the full policy (health gate + circuit breaker).  When unset the function
is a transparent passthrough — identical to calling ``adapter_publish`` directly.
This mirrors the PR #279 observe → enforce rollout pattern.

**Note**: Stage 1 extends policy to ALL adapters, not just browser-tier.
The policy now applies uniformly across all 20+ platforms.

Plan: docs/plans/2026-05-28-001-feat-publish-reliability-policy-plan.md
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any, Callable

from backlink_publisher._util.errors import AuthExpiredError, ExternalServiceError
from backlink_publisher.publishing.adapters import publish as adapter_publish
from backlink_publisher.publishing.adapters.base import AdapterResult

from .circuit import (
    CircuitState,
    is_ban_signal,
    is_tripped,
    record_success,
    trip,
    trip_on_error,
    _increment_half_open_try,
    _transition_to_half_open,
    _get_state,
)
from .events import Outcome, emit_attempt, now_ms

if TYPE_CHECKING:
    from backlink_publisher.config import Config


#: Activation env var — mirrors BACKLINK_PUBLISHER_DEDUP_ENFORCE from PR #279.
#: When unset / not "1": publish_with_policy is a transparent passthrough.
#: When "1": full policy (health gate + circuit breaker + events) is active.
POLICY_ENV = "BACKLINK_PUBLISHER_RELIABILITY_POLICY_ENABLED"

#: Half-open allowed in Stage 1 (Plan 2026-05-28-001)
HALF_OPEN_ALLOWED = True


def policy_enabled() -> bool:
    """True iff the operator opted into the reliability policy layer."""
    return os.environ.get(POLICY_ENV) == "1"


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
    Non-browser-tier platforms now also get health gate + circuit breaker + events.

    This function must NOT be called with dry-run payloads — the dry-run seam in
    ``publish_backlinks.py:233`` remains a direct ``adapter_publish(..., dry_run=True)``
    call. This function ignores dry_run=True if somehow called, but the convention
    is: callers are responsible for not routing dry-runs here.
    """
    full_payload = {**payload, "platform": platform}

    # Passthrough when policy is disabled (default)
    if not policy_enabled():
        return adapter_publish(
            payload=full_payload,
            mode=mode,
            config=config,
            dry_run=False,
            banner_emit=banner_emit,
        )

    # --- Policy active (BACKLINK_PUBLISHER_RELIABILITY_POLICY_ENABLED=1) ---

    # 1. Health gate (already fail-CLOSED: JSONDecodeError → {} → "unbound")
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

    # 2. Circuit breaker check with HALF_OPEN support
    state = _get_state(platform, config)
    current_state = state.get("state", CircuitState.CLOSED.value)

    if current_state == CircuitState.OPEN:
        return AdapterResult(
            status="skipped_circuit_open",
            adapter="policy",
            platform=platform,
            error=f"circuit open for {platform}",
        )

    # 3. HALF_OPEN: check if we've exceeded trial count
    if current_state == CircuitState.HALF_OPEN:
        if not _increment_half_open_try(platform, config):
            return AdapterResult(
                status="skipped_circuit_open",
                adapter="policy",
                platform=platform,
                error=f"circuit half-open trials exhausted for {platform}",
            )

    # 4. Dispatch + observe
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
        return result

    except AuthExpiredError as exc:
        duration = now_ms() - t0
        if is_ban_signal(exc):
            trip(platform, config)
            emit_attempt(platform, Outcome.AUTH_BANNED, duration)
        else:
            emit_attempt(platform, Outcome.AUTH_EXPIRED, duration)
        raise

    except ExternalServiceError as exc:
        duration = now_ms() - t0
        # Extract status code for circuit breaker and event emission
        import re

        match = re.search(r"\b(\d{3})\b", str(exc))
        status_code = int(match.group(1)) if match else None

        # For transient errors (429/502/503/504) or timeout-like errors, use trip_on_error
        # which handles both immediate trip and consecutive error counting
        if status_code in (429, 502, 503, 504):
            trip_on_error(platform, config, status_code)
            emit_attempt(
                platform, Outcome.HTTP_ERROR, duration, http_status=status_code
            )
        elif "timeout" in str(exc).lower() or "connection" in str(exc).lower():
            trip_on_error(platform, config, status_code=None)
            emit_attempt(platform, Outcome.TRANSIENT, duration)
        else:
            emit_attempt(
                platform, Outcome.EXTERNAL_ERROR, duration, http_status=status_code
            )
        raise

    except Exception as exc:
        emit_attempt(
            platform, Outcome.TRANSIENT, now_ms() - t0, error_class=type(exc).__name__
        )
        raise
