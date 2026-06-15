"""Event-store helper for ``referral.observed`` events (Plan 2026-06-15-004).

Builds the channel-keyed referral payload and calls ``store.append``. The floor
field is ``channel`` (see ``events.kinds.REQUIRED_FIELDS``); ``sessions`` and
``window`` are enrichment.
"""

from __future__ import annotations

from datetime import datetime, timezone

from backlink_publisher.events.store import EventStore
from backlink_publisher.events.kinds import REFERRAL_OBSERVED


def append_referral_observed(
    store: EventStore,
    *,
    target_site: str,
    channel: str,
    sessions: int,
    window_start: str,
    window_end: str,
) -> int:
    """Record a ``referral.observed`` event for one channel's referral total.

    Returns the new event id, or ``-1`` if the payload was quarantined (missing
    floor field — should not happen since ``channel`` is always supplied).
    """
    return store.append(
        REFERRAL_OBSERVED,
        {
            "target_site": target_site,
            "channel": channel,
            "sessions": sessions,
            "window_start": window_start,
            "window_end": window_end,
            "ts": datetime.now(timezone.utc).isoformat(),
        },
    )
