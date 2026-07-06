"""Medium session liveness check service — Plan 2026-06-01-001 Unit 7.

Extracted from webui_app/medium_liveness.py. Flask-free: calls webui_store
and the adapter probe, no Flask request/session/render.

webui_app/medium_liveness.py is now a thin re-export shim.
"""
from __future__ import annotations

import concurrent.futures

from backlink_publisher._util.logger import opencli_logger as log
from backlink_publisher.publishing.adapters.medium_liveness import (
    _active_probe,
    _load_storage_state_for_probe,
    _storage_state_path,
    LivenessResult,
    MEDIUM_LIVENESS_ACTIVE_PROBE_ENABLED,
)

# 5-minute cache on last_verified_at — every Settings page load within this
# window short-circuits to CACHED_BOUND without spawning a probe.
_LIVENESS_TTL_SECONDS = 300


def _last_verified_age_seconds(last_verified_at: str | None) -> float:
    """Seconds since *last_verified_at* (ISO string). Returns ``inf`` if absent
    or unparseable."""
    if not last_verified_at:
        return float("inf")
    try:
        from datetime import datetime
        ts = datetime.fromisoformat(last_verified_at)
        now = datetime.fromisoformat(
            datetime.now(ts.tzinfo).isoformat(timespec="seconds")
            if ts.tzinfo
            else datetime.now().isoformat(timespec="seconds")
        )
        return (now - ts).total_seconds()
    except (ValueError, TypeError):
        return float("inf")


def medium_liveness_check(timeout_s: float = 10.0) -> LivenessResult:
    """Determine the live state of the Medium binding.

    Side effects on definite outcomes:
      - ``LOGGED_IN`` → ``mark_verified('medium')`` updates last_verified_at.
      - ``EXPIRED`` → ``mark_expired('medium')`` flips the store state.
      - ``NEVER_BOUND``, ``CACHED_BOUND``, ``NEEDS_RECHECK`` are read-only.

    Returns ``NEEDS_RECHECK`` if the probe exceeds *timeout_s* so the caller
    (typically ``_settings_context`` in helpers/contexts.py) can render
    without blocking.
    """
    from webui_store.channel_status import (
        get_status,
        mark_expired,
        mark_verified,
    )

    status = get_status("medium")
    state = status.get("status", "unbound")

    if state == "unbound" or not _storage_state_path().exists():
        return LivenessResult.NEVER_BOUND

    if state == "expired":
        return LivenessResult.EXPIRED

    age = _last_verified_age_seconds(status.get("last_verified_at"))
    if age < _LIVENESS_TTL_SECONDS:
        return LivenessResult.CACHED_BOUND

    if not MEDIUM_LIVENESS_ACTIVE_PROBE_ENABLED:
        return LivenessResult.NEEDS_RECHECK

    storage_state = _load_storage_state_for_probe()
    if storage_state is None:
        return LivenessResult.NEVER_BOUND

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(_active_probe, storage_state)
            result = future.result(timeout=timeout_s)
    except concurrent.futures.TimeoutError:
        log.warn(
            f"medium_liveness: probe exceeded {timeout_s}s budget; needs_recheck"
        )
        return LivenessResult.NEEDS_RECHECK
    except Exception as exc:  # noqa: BLE001 — defensive
        log.warn(
            f"medium_liveness: probe raised: "
            f"{type(exc).__name__}: {exc}"
        )
        return LivenessResult.NEEDS_RECHECK

    if result == LivenessResult.LOGGED_IN:
        try:
            mark_verified("medium")
        except Exception as exc:  # noqa: BLE001
            log.warn(
                f"medium_liveness: mark_verified failed: "
                f"{type(exc).__name__}: {exc}"
            )
    elif result == LivenessResult.EXPIRED:
        try:
            mark_expired("medium")
        except Exception as exc:  # noqa: BLE001
            log.warn(
                f"medium_liveness: mark_expired failed: "
                f"{type(exc).__name__}: {exc}"
            )

    return result
