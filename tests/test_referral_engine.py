"""Unit tests for the channel referral aggregation engine (Plan 2026-06-15-004 U2)."""
from __future__ import annotations

__tier__ = "unit"

from backlink_publisher.click_track.engine import ClickStats
from backlink_publisher.referral.engine import aggregate_by_channel


def _stat(source: str, sessions: int) -> ClickStats:
    return ClickStats(
        target_site="t.example",
        source_domain=source,
        sessions=sessions,
        users=0,
        pageviews=0,
        window_start="2026-06-01",
        window_end="2026-06-08",
    )


def test_aggregate_maps_source_to_channel():
    out = aggregate_by_channel([_stat("medium.com", 42)])
    assert len(out) == 1
    assert out[0].channel == "medium"
    assert out[0].sessions == 42
    assert out[0].window_start == "2026-06-01"
    assert out[0].window_end == "2026-06-08"


def test_multiple_sources_same_channel_are_summed():
    out = aggregate_by_channel([_stat("medium.com", 10), _stat("m.medium.com", 5)])
    by_channel = {c.channel: c.sessions for c in out}
    assert by_channel["medium"] == 15


def test_unknown_source_kept_not_dropped():
    out = aggregate_by_channel([_stat("randomsite.com", 7)])
    by_channel = {c.channel: c.sessions for c in out}
    assert by_channel["unknown"] == 7


def test_empty_stats_yields_no_channels():
    assert aggregate_by_channel([]) == []


def test_channels_sorted_by_name():
    out = aggregate_by_channel([_stat("zenn.dev", 1), _stat("blogspot.com", 2)])
    assert [c.channel for c in out] == ["blogger", "zenn"]
