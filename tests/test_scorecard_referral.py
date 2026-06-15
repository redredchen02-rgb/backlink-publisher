"""Scorecard referral_traffic axis from referral.observed events (Plan 2026-06-15-004 U3)."""
from __future__ import annotations

__tier__ = "integration"

import pytest

from backlink_publisher.events import EventStore
from backlink_publisher.referral.store import append_referral_observed
from backlink_publisher.scorecard import build_channel_scorecard
from backlink_publisher.scorecard.model import AXIS_INERT


@pytest.fixture
def store(tmp_path):
    return EventStore(path=tmp_path / "events.db")


def _row(rows, channel):
    return next(r for r in rows if r.channel == channel)


def _observe(store, channel, sessions):
    append_referral_observed(
        store,
        target_site="site.com",
        channel=channel,
        sessions=sessions,
        window_start="2026-06-01",
        window_end="2026-06-08",
    )


def test_channel_with_referral_shows_real_sessions(store):
    _observe(store, "medium", 42)
    rows = build_channel_scorecard(store=store, history=[])
    assert _row(rows, "medium").referral_traffic == "sessions:42"


def test_channel_without_referral_stays_inert(store):
    _observe(store, "medium", 42)
    rows = build_channel_scorecard(store=store, history=[])
    # blogger is registered but has no referral event → still inert
    assert _row(rows, "blogger").referral_traffic == AXIS_INERT


def test_re_observation_replaces_not_accumulates(store):
    # Re-running referral-attribute must NOT double-count: latest snapshot wins.
    _observe(store, "medium", 10)
    _observe(store, "medium", 5)
    rows = build_channel_scorecard(store=store, history=[])
    assert _row(rows, "medium").referral_traffic == "sessions:5"


def test_observed_zero_is_distinct_from_inert(store):
    # measured zero (sessions:0) must differ from not-measured (AXIS_INERT).
    _observe(store, "zenn", 0)
    rows = build_channel_scorecard(store=store, history=[])
    assert _row(rows, "zenn").referral_traffic == "sessions:0"
    assert _row(rows, "blogger").referral_traffic == AXIS_INERT


def test_referral_only_channel_surfaces_a_row(store):
    # 'unknown' is not a registered platform, but referral data must surface it
    _observe(store, "unknown", 7)
    rows = build_channel_scorecard(store=store, history=[])
    assert _row(rows, "unknown").referral_traffic == "sessions:7"
