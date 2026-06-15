"""Tests for the shared referral aggregation helper (Plan 2026-06-15-004 review fix).

Latest-per-channel (not sum) defends against double-counting on repeated
referral-attribute runs; negative/malformed sessions clamp to 0.
"""
from __future__ import annotations

__tier__ = "integration"

import pytest

from backlink_publisher.events import EventStore
from backlink_publisher.referral.aggregate import (
    latest_referral_by_channel,
    total_referral_sessions,
)
from backlink_publisher.referral.store import append_referral_observed


@pytest.fixture
def store(tmp_path):
    return EventStore(path=tmp_path / "events.db")


def _observe(store, channel, sessions):
    append_referral_observed(
        store,
        target_site="site.com",
        channel=channel,
        sessions=sessions,
        window_start="2026-06-01",
        window_end="2026-06-08",
    )


def test_latest_wins_no_double_count(store):
    _observe(store, "medium", 10)
    _observe(store, "medium", 5)  # re-run / corrected snapshot
    assert latest_referral_by_channel(store) == {"medium": 5}


def test_distinct_channels_kept(store):
    _observe(store, "medium", 10)
    _observe(store, "zenn", 3)
    assert latest_referral_by_channel(store) == {"medium": 10, "zenn": 3}


def test_negative_sessions_clamped_to_zero(store):
    _observe(store, "medium", -5)
    assert latest_referral_by_channel(store) == {"medium": 0}


def test_total_sums_latest_per_channel(store):
    _observe(store, "medium", 10)
    _observe(store, "medium", 4)  # replaces -> 4
    _observe(store, "zenn", 3)
    assert total_referral_sessions(store) == 7  # 4 + 3, not 10+4+3


def test_total_none_when_empty(store):
    assert total_referral_sessions(store) is None


def test_total_zero_when_observed_zero(store):
    _observe(store, "medium", 0)
    assert total_referral_sessions(store) == 0  # distinct from None
