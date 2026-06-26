"""Channel referral attribution engine — pure transform layer (Plan 2026-06-15-004).

Reuses :func:`backlink_publisher.click_track.engine.query_site` for the GA4 Data
API call (which already returns per-``sessionSource`` sessions — channel-level
granularity needs no extra dimensions), then aggregates those rows into
per-channel referral stats via :mod:`.channel_map`.

Shell layer: :mod:`backlink_publisher.cli.referral_attribute`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import logging

from backlink_publisher.click_track.engine import (
    ClickQueryOptions,
    ClickQueryResult,
    ClickStats,
    handle_site,
)
from backlink_publisher.config import ClickTrackConfig
from backlink_publisher.referral.channel_map import map_source_to_channel

log = logging.getLogger(__name__)


@dataclass
class ChannelReferral:
    """Aggregated referral sessions for one channel within a window."""

    channel: str
    sessions: int
    window_start: str
    window_end: str


@dataclass
class ReferralResult:
    """Result of attributing one target site's GA4 referral to channels."""

    target_site: str
    channels: list[ChannelReferral] = field(default_factory=list)
    error_reason: str | None = None
    error_class: str | None = None


def aggregate_by_channel(stats: list[ClickStats]) -> list[ChannelReferral]:
    """Fold per-source GA4 stats into per-channel referral totals.

    Multiple GA4 sources that normalise to the same channel (e.g.
    ``m.facebook.com`` + ``facebook``) are summed. Unmatched sources roll up
    under :data:`~backlink_publisher.referral.channel_map.UNKNOWN_CHANNEL`
    rather than being dropped. Channels are returned sorted by name for stable
    output.
    """
    totals: dict[str, int] = {}
    window_start = ""
    window_end = ""
    for stat in stats:
        channel = map_source_to_channel(stat.source_domain)
        totals[channel] = totals.get(channel, 0) + int(stat.sessions or 0)
        # All rows in one query share the same window; capture the last seen.
        window_start = stat.window_start or window_start
        window_end = stat.window_end or window_end
    return [
        ChannelReferral(
            channel=channel,
            sessions=sessions,
            window_start=window_start,
            window_end=window_end,
        )
        for channel, sessions in sorted(totals.items())
    ]


def attribute_site(
    target_site: str,
    property_id: str,
    *,
    config: ClickTrackConfig,
    opts: ClickQueryOptions,
) -> ReferralResult:
    """Query one target site's GA4 referral and aggregate it to channels.

    Reuses ``click_track``'s ``handle_site`` for the GA4 call, then maps the
    per-source stats to channels. Errors are passed through verbatim so the CLI
    can surface them without writing events.
    """
    result: ClickQueryResult = handle_site(
        target_site=target_site,
        property_id=property_id,
        config=config,
        opts=opts,
    )
    if result.error_reason:
        return ReferralResult(
            target_site=target_site,
            error_reason=result.error_reason,
            error_class=result.error_class,
        )

    channels = aggregate_by_channel(result.stats)
    log.info(
        "attribute_site(%s) — %d channel(s) from %d source row(s)",
        target_site,
        len(channels),
        len(result.stats),
    )
    return ReferralResult(target_site=target_site, channels=channels)
