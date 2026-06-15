"""Shared read-side aggregation of ``referral.observed`` events (Plan 2026-06-15-004).

Both the channel scorecard and the g3 gate consume per-channel referral totals.
This is the single source of that aggregation so the two can never diverge.

**Latest-wins, not sum.** A ``referral.observed`` event is a *snapshot* of a
channel's referral level for a query window. Re-running ``referral-attribute``
(same window, a corrected run, or a wider window) appends a fresh snapshot;
summing every snapshot would double-count. So we keep the newest observation per
channel (by event ``id``, the monotonic insert order) — re-running REPLACES.

Negative/malformed ``sessions`` are clamped to 0: GA4 session counts are never
negative, and a stray negative would otherwise invert the g3 verdict (``<=0`` →
KILL). Unparseable values count as 0 rather than raising — a read-side
aggregation must not crash a gate probe on one bad row.
"""

from __future__ import annotations

from backlink_publisher.events import EventStore
from backlink_publisher.events.kinds import REFERRAL_OBSERVED

_LATEST_SQL = (
    "SELECT json_extract(payload_json, '$.channel') AS channel, "
    "json_extract(payload_json, '$.sessions') AS sessions "
    "FROM events WHERE kind = ? ORDER BY id"
)


def latest_referral_by_channel(store: EventStore) -> dict[str, int]:
    """``channel → newest referral sessions`` from ``referral.observed`` events.

    Ascending ``id`` order means the last row written for a channel overwrites
    earlier ones, so repeated ``referral-attribute`` runs replace rather than
    accumulate. A channel with no event is absent from the map (callers render
    the "not measured" sentinel). Sessions are clamped to ``>= 0``.
    """
    latest: dict[str, int] = {}
    for row in store.query(_LATEST_SQL, (REFERRAL_OBSERVED,)):
        channel = row["channel"]
        if not channel:
            continue
        try:
            sessions = int(row["sessions"] or 0)
        except (TypeError, ValueError):
            sessions = 0
        latest[channel] = max(0, sessions)  # newest wins (ORDER BY id); clamp
    return latest


def total_referral_sessions(store: EventStore) -> int | None:
    """Sum of the latest per-channel referral sessions, or ``None`` if no events.

    ``None`` (no ``referral.observed`` rows yet) preserves g3's original
    INCONCLUSIVE semantics; ``0`` means observed-but-zero (→ KILL).
    """
    by_channel = latest_referral_by_channel(store)
    if not by_channel:
        return None
    return sum(by_channel.values())
