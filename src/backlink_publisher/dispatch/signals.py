"""Signal collection layer for dispatch-backlinks.

Reads live signal sources at execution time:
- Registry metadata (dofollow, referral_value, language whitelist, visibility)
- Channel binding status (bound/expired/unbound)
- Canary health (quarantined, degraded, last check timestamp)

All signals are read-only — no writes to any store.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from backlink_publisher.canary.store import get_health
from backlink_publisher.publishing.registry import (
    active_platforms,
    dispatch_weight as registry_dispatch_weight,
    dofollow_status,
    policy,
    referral_value,
    visibility as registry_visibility,
)


@dataclass
class PlatformSignal:
    """Aggregated signal state for one publishing platform.

    This is the canonical input into the routing scorer. Every field is
    resolved at signal-collection time from live sources.
    """

    name: str
    # Dofollow capability (True / False / "uncertain" / None)
    dofollow: bool | str | None = None
    # Referral sub-grade for nofollow platforms ("high" / "low" / None)
    referral: str | None = None
    # Channel binding status ("bound" / "expired" / "unbound")
    binding: str = "unbound"
    # Canary health status ("link-alive" / "drift-confirmed" / "advisory" / "not-configured")
    canary_status: str = "not-configured"
    # True if the platform is currently quarantined by the canary
    quarantined: bool = False
    # True if the platform's last canary verdict was degraded
    degraded: bool = False
    # ISO timestamp of last successful canary check, or None
    canary_last_ok_at: str | None = None
    # Language whitelist (empty tuple = no restriction)
    language_whitelist: tuple[str, ...] = ()
    # Visibility (defaults to "active")
    visibility: str = "active"
    language: str = "default"
    # Routing reliability discount from registry (0.0 < weight <= 1.0)
    dispatch_weight: float = 1.0


# Platforms that are always considered "bound" — they have no credential
# lifecycle (auth_type = "anon") and therefore no channel-status entry.
_ALWAYS_BOUND: frozenset[str] = frozenset({
    "telegraph", "txtfyi", "rentry", "notesio",
})


def _get_binding(platform: str, channel_data: dict[str, Any] | None) -> str:
    """Resolve binding status for ``platform``.

    Anon platforms (telegraph, txtfyi, rentry, notesio) are always bound.
    All other platforms read from channel_status_store data.
    """
    if platform in _ALWAYS_BOUND:
        return "bound"
    if channel_data is None:
        return "unbound"
    rec = channel_data.get(platform)
    if rec is None or not isinstance(rec, dict):
        return "unbound"
    return cast(str, rec.get("status", "unbound"))


def collect_all(
    channel_data: dict[str, Any] | None = None,
    language: str = "default",
) -> dict[str, PlatformSignal]:
    """Collect live signals for every active publishing platform.

    Args:
        channel_data: Pre-loaded channel-status store data (dict).
            If None, all non-anon platforms are treated as unbound.
        language: Language scope for dispatch-weight lookup.

    Returns:
        Mapping of platform name -> PlatformSignal with resolved values.
    """
    platforms = active_platforms()
    signals: dict[str, PlatformSignal] = {}

    for name in platforms:
        dof = dofollow_status(name)
        ref = referral_value(name)
        pol = policy(name)
        visibility_str = registry_visibility(name) or "active"  # type: ignore[unreachable]

        whitelist: tuple[str, ...] = ()
        if pol is not None and pol.language_whitelist:
            whitelist = pol.language_whitelist

        canary_rec = get_health(name)
        canary_status = canary_rec.get("status", "not-configured")
        quarantined = bool(canary_rec.get("quarantined", False))
        degraded = bool(canary_rec.get("degraded", False))
        last_ok_at = canary_rec.get("last_ok_at")

        sig = PlatformSignal(
            name=name,
            dofollow=dof,
            referral=ref,
            binding=_get_binding(name, channel_data),
            canary_status=canary_status,
            quarantined=quarantined,
            degraded=degraded,
            canary_last_ok_at=last_ok_at,
            language_whitelist=whitelist,
            visibility=visibility_str,
            language=language,
            dispatch_weight=registry_dispatch_weight(name, language=language),
        )
        signals[name] = sig

    return signals
