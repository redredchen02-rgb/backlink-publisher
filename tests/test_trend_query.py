"""Unit tests for compute_target_trends (R13 sparkline data).

Covers: bucket assignment, alive-rate calculation, indeterminate exclusion,
excluded hosts, empty/missing-data sentinels, and multi-target isolation.
"""

from __future__ import annotations

__tier__ = "integration"

from datetime import datetime, timedelta, timezone, UTC

import pytest

from backlink_publisher.events import EventStore
from backlink_publisher.events.kinds import LINK_RECHECKED
from backlink_publisher.events.trend_query import compute_target_trends, TREND_WEEKS
from backlink_publisher.recheck import verdicts

NOW = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)
TARGET = "https://blog.example.org/page"
TARGET2 = "https://news.example.org/article"


@pytest.fixture
def store(tmp_path):
    return EventStore(path=tmp_path / "events.db")


def _recheck(store, target, verdict, *, days_ago):
    ts = (NOW - timedelta(days=days_ago)).isoformat()
    host = target.split("//")[1].split("/")[0]
    store.append(
        LINK_RECHECKED, {"verdict": verdict},
        target_url=target, host=host, ts_utc=ts,
    )


def test_empty_store(store):
    result = compute_target_trends(store=store, now=NOW)
    assert result == {}


def test_single_alive_most_recent_week(store):
    _recheck(store, TARGET, verdicts.ALIVE, days_ago=3)
    result = compute_target_trends(store=store, now=NOW)
    assert TARGET in result
    trend = result[TARGET]
    assert len(trend) == TREND_WEEKS
    # week 0 = oldest (22-28 days ago) → None; week 3 = newest (0-6 days) → 1.0
    assert trend[3] == 1.0
    assert trend[0] is None
    assert trend[1] is None
    assert trend[2] is None


def test_stripped_reduces_rate(store):
    _recheck(store, TARGET, verdicts.ALIVE, days_ago=5)
    _recheck(store, TARGET, verdicts.LINK_STRIPPED, days_ago=4)
    result = compute_target_trends(store=store, now=NOW)
    trend = result[TARGET]
    assert trend[3] == pytest.approx(0.5)


def test_probe_error_excluded_from_denominator(store):
    # probe_error is indeterminate — should not affect the rate
    _recheck(store, TARGET, verdicts.ALIVE, days_ago=5)
    _recheck(store, TARGET, verdicts.PROBE_ERROR, days_ago=4)
    result = compute_target_trends(store=store, now=NOW)
    trend = result[TARGET]
    assert trend[3] == pytest.approx(1.0)


def test_example_com_excluded(store):
    _recheck(store, "https://example.com/page", verdicts.ALIVE, days_ago=3)
    result = compute_target_trends(store=store, now=NOW)
    assert not any("example.com" in k for k in result)


def test_multiple_targets_isolated(store):
    _recheck(store, TARGET, verdicts.ALIVE, days_ago=3)
    _recheck(store, TARGET2, verdicts.LINK_STRIPPED, days_ago=3)
    result = compute_target_trends(store=store, now=NOW)
    assert result[TARGET][3] == pytest.approx(1.0)
    assert result[TARGET2][3] == pytest.approx(0.0)


def test_bucket_assignment_week_boundaries(store):
    # days_ago=7 → week_idx = min(3 - 7//7, 3) = min(3-1, 3) = 2
    _recheck(store, TARGET, verdicts.ALIVE, days_ago=7)
    # days_ago=14 → week_idx = min(3 - 14//7, 3) = min(3-2, 3) = 1
    _recheck(store, TARGET, verdicts.LINK_STRIPPED, days_ago=14)
    result = compute_target_trends(store=store, now=NOW)
    trend = result[TARGET]
    assert trend[2] == pytest.approx(1.0)  # week 2: only alive
    assert trend[1] == pytest.approx(0.0)  # week 1: only stripped
    assert trend[3] is None                 # week 3: nothing
    assert trend[0] is None                 # week 0: nothing


def test_events_older_than_28_days_ignored(store):
    _recheck(store, TARGET, verdicts.ALIVE, days_ago=30)
    result = compute_target_trends(store=store, now=NOW)
    assert TARGET not in result


def test_returns_exactly_trend_weeks_entries(store):
    _recheck(store, TARGET, verdicts.ALIVE, days_ago=1)
    result = compute_target_trends(store=store, now=NOW)
    assert len(result[TARGET]) == TREND_WEEKS
