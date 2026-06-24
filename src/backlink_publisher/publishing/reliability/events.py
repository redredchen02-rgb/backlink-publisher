"""Publish-attempt event emission — Plan 2026-05-28-001 Unit 1.

Extended for Stage 1 (Plan 2026-05-28-001):
- All adapters (not just browser-tier) emit events
- Enhanced Outcome enum for rate limiting
- HTTP method, URL, and status code in events

Design constraints:
- Never raises — side-effect only.
- Writes to ``opencli_logger`` (stderr-captured by WebUI subprocess pipe).
"""

from __future__ import annotations

import time
from enum import Enum
from typing import Any

from backlink_publisher._util.logger import opencli_logger as _log


class Outcome(str, Enum):
    SUCCESS = "success"
    AUTH_EXPIRED = "auth_expired"
    AUTH_BANNED = "auth_banned"
    EXTERNAL_ERROR = "external_error"
    TRANSIENT = "transient"
    RATE_LIMITED = "rate_limited"
    HTTP_ERROR = "http_error"
    # Observe-mode signals (Plan 2026-06-15-001 observe→enforce rollout): the gate
    # WOULD have skipped this publish under enforcement, but observe mode dispatched
    # anyway. Counting these tells operators how often enforcement would fire before
    # they flip it on.
    WOULD_SKIP_POLICY = "would_skip_policy"
    WOULD_SKIP_CIRCUIT = "would_skip_circuit"


def emit_attempt(
    platform: str,
    outcome: Outcome,
    duration_ms: float,
    run_id: str | None = None,
    *,
    http_method: str | None = None,
    http_url: str | None = None,
    http_status: int | None = None,
    error_class: str | None = None,
    **extra: Any,
) -> None:
    """Emit a ``publish_attempt`` event.

    Enhanced for Stage 1: includes HTTP method, URL, status code, and error class
    for better observability across all adapters.

    Never raises — any internal error is swallowed so reliability events
    never break a publish run.
    """
    try:
        payload: dict[str, Any] = {
            "event": "publish_attempt",
            "platform": platform,
            "outcome": outcome.value if isinstance(outcome, Outcome) else str(outcome),
            "duration_ms": round(duration_ms, 1),
        }
        if run_id is not None:
            payload["run_id"] = run_id
        if http_method is not None:
            payload["http_method"] = http_method
        if http_url is not None:
            payload["http_url"] = http_url
        if http_status is not None:
            payload["http_status"] = http_status
        if error_class is not None:
            payload["error_class"] = error_class
        payload.update(extra)
        _log.info(payload)  # type: ignore[arg-type]
    except Exception:  # noqa: BLE001
        pass


def now_ms() -> float:
    """Monotonic timestamp in milliseconds — for duration measurement."""
    return time.monotonic() * 1000
