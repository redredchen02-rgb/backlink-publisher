"""Group the settings overview channels into automation tiers.

Pure presentation-layer helper for the WebUI ``/settings`` overview panel
(Plan 2026-05-29-003). Takes the existing ``dashboard_channels`` list
``[(name, status_dict), ...]`` and buckets it into three independent
automation tiers derived solely from ``status['auth_type']``:

  - tier-1 「开箱即用」     anon                         — no credentials needed
  - tier-2 「填凭证即自动」  token / token_fields / oauth /
                           userpass / None / unknown     — fill credentials, then auto
  - tier-3 「需浏览器登录态」 paste_blob / live_browser     — browser login state

Within each tier, ready channels (already bound, or anon = no binding needed)
sort ahead of unconfigured ones; both segments preserve the caller's input
order (the caller passes ``active_platforms()`` order, i.e. alphabetical) for
stable rendering. Empty tiers are dropped.

Computed fresh on every call (never cached), mirroring
``registry.platforms_by_auth_type()`` — a newly registered platform is
reflected without a reload.
"""

from __future__ import annotations

from typing import Any

# Authoritative auth_type → tier mapping (Plan 2026-05-29-003 R4).
# ``None`` and any unrecognized auth_type fall back to tier-2 (R4a) so a
# channel never silently disappears from all groups.
TIER_BY_AUTH_TYPE: dict[str | None, str] = {
    "anon": "tier-1",
    "token": "tier-2",
    "token_fields": "tier-2",
    "oauth": "tier-2",
    "userpass": "tier-2",
    None: "tier-2",
    "paste_blob": "tier-3",
    "live_browser": "tier-3",
}

_FALLBACK_TIER = "tier-2"

# Ordered tier metadata: label/subtitle (R11) and default-open state (R2).
# tier-1 opens by default; tier-2/3 stay collapsed.
_TIER_META: tuple[dict[str, Any], ...] = (
    {
        "key": "tier-1",
        "label": "开箱即用",
        "subtitle": "无需任何配置即可发布",
        "open": True,
    },
    {
        "key": "tier-2",
        "label": "填凭证即自动",
        "subtitle": "填入凭证后即可自动发布",
        "open": False,
    },
    {
        "key": "tier-3",
        "label": "需浏览器登录态(半自动)",
        "subtitle": "需在浏览器中完成登录态后发布",
        "open": False,
    },
)


def _tier_for(auth_type: str | None) -> str:
    """Map an ``auth_type`` to its tier key; unknown values default to tier-2 (R4a)."""
    return TIER_BY_AUTH_TYPE.get(auth_type, _FALLBACK_TIER)


def _is_ready(status: dict[str, Any]) -> bool:
    """A channel is "ready" when it needs no binding (anon) or is already bound.

    Single source of truth for both the R3 ready-count and the R5 ready-first
    ordering, so the two can never diverge.
    """
    return status.get("auth_type") == "anon" or bool(status.get("bound"))


def group_channels_by_tier(
    dashboard_channels: list[tuple[str, dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Bucket ``[(name, status), ...]`` into ordered automation tiers.

    Returns a list of tier dicts (tier-1 first), each shaped::

        {key, label, subtitle, open, total, ready, channels}

    where ``channels`` is ``[(name, status, ready), ...]`` with ready channels
    first and each segment preserving input order (R5/R6). Empty tiers are
    omitted (R12). Never cached — recomputed on every call.
    """
    buckets: dict[str, list[tuple[str, dict[str, Any], bool]]] = {
        meta["key"]: [] for meta in _TIER_META
    }
    for name, status in dashboard_channels:
        ready = _is_ready(status)
        buckets[_tier_for(status.get("auth_type"))].append((name, status, ready))

    tiers: list[dict[str, Any]] = []
    for meta in _TIER_META:
        members = buckets[meta["key"]]
        if not members:
            continue  # R12: drop empty tiers
        # R5/R6: ready first; stable sort keeps each segment in input order.
        ordered = sorted(members, key=lambda item: not item[2])
        ready_count = sum(1 for _, _, ready in ordered if ready)
        tiers.append(
            {
                "key": meta["key"],
                "label": meta["label"],
                "subtitle": meta["subtitle"],
                "open": meta["open"],
                "total": len(ordered),
                "ready": ready_count,
                "channels": ordered,
            }
        )
    return tiers


# Plan 2026-06-05-007 — connection-state partition (main / extension area).
# A channel can only reach these two lifecycle states *after* a successful
# bind, so they are the reliable "was once bound" signal that keeps a now-
# failed channel in the main area (R2) instead of folding it away. Only ever
# populated for the browser-binding channels in ``channel_status.CHANNELS``
# (velog / medium / blogger); every other platform has no record.
_RECONNECT_STATES: frozenset[str] = frozenset({"expired", "identity_mismatch"})


def _needs_reconnect(
    name: str, channel_statuses: dict[str, dict[str, Any]]
) -> bool:
    """True when ``name`` was bound before but its login state has failed."""
    rec = channel_statuses.get(name)
    return bool(rec) and rec.get("status") in _RECONNECT_STATES


def _is_usable(status: dict[str, Any], needs_reconnect: bool) -> bool:
    """A channel belongs in the main area when it is publishable now (anon or
    bound) or was bound before and only needs reconnecting (R1/R2/R10).

    Keyed on ``auth_type``/``bound`` (from ``get_channel_status``) plus the
    reconnect flag (from the ``channel_status`` lifecycle store) — never on
    ``bound_at`` truthiness or record existence, which an unbound-but-probed
    channel can also carry.
    """
    return (
        status.get("auth_type") == "anon"
        or bool(status.get("bound"))
        or needs_reconnect
    )


def _group_main_by_tier(
    main_channels: list[tuple[str, dict[str, Any], bool]],
) -> list[dict[str, Any]]:
    """Group main-area ``[(name, status, needs_reconnect), ...]`` by automation tier.

    Returns the same meta shape as ``group_channels_by_tier`` but ``channels``
    entries are ``(name, status, needs_reconnect)`` — empty tiers omitted.
    """
    buckets: dict[str, list[tuple[str, dict[str, Any], bool]]] = {
        meta["key"]: [] for meta in _TIER_META
    }
    for name, status, needs_reconnect in main_channels:
        buckets[_tier_for(status.get("auth_type"))].append((name, status, needs_reconnect))
    result = []
    for meta in _TIER_META:
        members = buckets[meta["key"]]
        if not members:
            continue
        result.append({
            "key": meta["key"],
            "label": meta["label"],
            "subtitle": meta["subtitle"],
            "channels": members,
        })
    return result


def partition_channels_by_connection(
    dashboard_channels: list[tuple[str, dict[str, Any]]],
    channel_statuses: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Split ``[(name, status), ...]`` into main vs extension by connection state.

    Single reusable decision point (R13) shared by the settings overview and
    the publish channel picker. Returns::

        {
          "main":            [(name, status, needs_reconnect), ...],
          "extension_groups": [<tier dict>, ...],   # from group_channels_by_tier
          "main_count": int,
          "extension_count": int,
          "cold_start": bool,
        }

    ``main`` lists usable channels (bound + anon + needs-reconnect), with the
    normal ones first and needs-reconnect ones after, each segment preserving
    input order. The extension area holds never-connected (``unbound``,
    non-anon) channels, sub-grouped by automation tier via
    ``group_channels_by_tier`` (R15). ``cold_start`` is True when the main area
    has no genuinely bound or needs-reconnect channel (anon-only / empty),
    so the UI can surface onboarding instead of burying the bind entry (R14).

    ``channel_statuses`` is the ``channel_status.list_all()`` mapping; ``None``
    or ``{}`` degrades safely to "no reconnect". Never cached.
    """
    statuses = channel_statuses or {}
    main: list[tuple[str, dict[str, Any], bool]] = []
    extension: list[tuple[str, dict[str, Any]]] = []
    for name, status in dashboard_channels:
        reconnect = _needs_reconnect(name, statuses)
        if _is_usable(status, reconnect):
            main.append((name, status, reconnect))
        else:
            extension.append((name, status))

    # Normal-usable first, needs-reconnect after; stable sort keeps input order
    # within each segment (R2 keeps reconnect visible, not buried by re-sorting).
    main.sort(key=lambda item: item[2])

    has_real = any(
        reconnect or bool(status.get("bound")) for _, status, reconnect in main
    )
    # Cold start = there ARE channels but none are genuinely bound / reconnecting
    # (anon-only). An empty partition (degraded / error path) is not cold start,
    # so the onboarding banner never claims "these work" over nothing.
    return {
        "main": main,
        "main_groups": _group_main_by_tier(main),
        "extension_groups": group_channels_by_tier(extension),
        "main_count": len(main),
        "extension_count": len(extension),
        "cold_start": (not has_real) and bool(main or extension),
    }


def merge_verify_health(
    channel_statuses: dict[str, dict[str, Any]],
    expired: frozenset[str] | set[str] | None,
) -> dict[str, dict[str, Any]]:
    """Overlay live-verify credential expiry onto the channel_status map
    (Plan 2026-06-05-008).

    Any channel whose last credential verdict was ``token_expired`` is forced to
    ``status="expired"`` so ``partition_channels_by_connection`` flags it
    ``needs_reconnect`` (keeps it in the main area with the 需重連 marker, and
    non-selectable on the publish picker) — even when its offline ``bound`` reads
    True because the token is present but server-rejected. Returns the input
    unchanged when there is nothing expired. Never mutates the input dict.
    """
    if not expired:
        return channel_statuses
    merged = dict(channel_statuses or {})
    for name in expired:
        merged[name] = {"status": "expired"}
    return merged
