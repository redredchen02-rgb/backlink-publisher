"""Per-channel enforce-readiness reader (Plan 2026-06-15-006, Unit 4).

Verifies the TWO-source join (attempts from publish.*, would-skip from
reliability.decision) and the THREE-state verdict.
"""
from __future__ import annotations

__tier__ = "unit"

from datetime import datetime, timedelta, timezone

import pytest

from backlink_publisher.events import EventStore
from backlink_publisher.events.kinds import (
    PUBLISH_CONFIRMED,
    RELIABILITY_DECISION,
)
from backlink_publisher.scorecard.reliability_readiness import (
    DEFAULT_MIN_ATTEMPTS,
    DEFAULT_MIN_DAYS_OBSERVED,
    VERDICT_INSUFFICIENT,
    VERDICT_POINTLESS,
    VERDICT_WORTHWHILE,
    channel_readiness,
)

_T0 = datetime(2026, 6, 1, tzinfo=timezone.utc)
_T0_ISO = _T0.isoformat()


@pytest.fixture()
def store(tmp_path):
    return EventStore(path=tmp_path / "e.db")


def _seed_attempts(store, channel, n, *, ts=_T0_ISO):
    for _ in range(n):
        store.append(
            PUBLISH_CONFIRMED,
            {"live_url": f"https://x/{channel}", "platform": channel},
            ts_utc=ts,
        )


def _seed_decisions(store, channel, n, *, decision="would_skip_policy", ts=_T0_ISO):
    for _ in range(n):
        store.append(
            RELIABILITY_DECISION,
            {"platform": channel, "decision": decision, "mode": "observe"},
            ts_utc=ts,
        )


def _one(store, now, **kw):
    report = channel_readiness(
        store=store, now=now, min_attempts=5, min_days_observed=3, **kw
    )
    assert len(report.per_channel) == 1
    return report.per_channel[0]


def test_worthwhile_when_would_skip_present_over_sufficient_window(store):
    _seed_attempts(store, "medium", 6)
    _seed_decisions(store, "medium", 2)
    c = _one(store, now=_T0 + timedelta(days=5))
    assert c.verdict == VERDICT_WORTHWHILE
    assert c.observed_attempts == 6
    assert c.would_skip_count == 2
    assert c.would_skip_rate == pytest.approx(0.333, abs=0.001)
    assert c.days_observed == 5


def test_pointless_when_no_would_skip_over_sufficient_window(store):
    _seed_attempts(store, "medium", 6)  # zero would-skip
    c = _one(store, now=_T0 + timedelta(days=5))
    assert c.verdict == VERDICT_POINTLESS
    assert c.would_skip_count == 0


def test_insufficient_when_small_sample(store):
    _seed_attempts(store, "medium", 2)
    _seed_decisions(store, "medium", 1)
    c = _one(store, now=_T0 + timedelta(days=5))
    assert c.verdict == VERDICT_INSUFFICIENT
    assert c.small_sample is True


def test_insufficient_when_window_too_short(store):
    _seed_attempts(store, "medium", 6)
    _seed_decisions(store, "medium", 2)
    c = _one(store, now=_T0 + timedelta(days=1))  # only 1 day observed; min is 3
    assert c.verdict == VERDICT_INSUFFICIENT
    assert c.days_observed == 1


def test_denominator_comes_from_publish_not_reliability_rows(store):
    """Many would-skip rows but only 1 attempt → small sample, NOT a 1000% rate."""
    _seed_attempts(store, "medium", 1)
    _seed_decisions(store, "medium", 10)
    c = _one(store, now=_T0 + timedelta(days=5))
    assert c.observed_attempts == 1  # from publish.*, not the 10 reliability rows
    assert c.verdict == VERDICT_INSUFFICIENT


def test_only_would_skip_no_attempts_is_insufficient_not_infinite_rate(store):
    _seed_decisions(store, "medium", 3)  # no publish.* rows at all
    c = _one(store, now=_T0 + timedelta(days=5))
    assert c.observed_attempts == 0
    assert c.would_skip_rate is None
    assert c.verdict == VERDICT_INSUFFICIENT


def test_enforce_skipped_decisions_are_not_counted_as_would_skip(store):
    """skipped_* (enforce) and degraded must not inflate the would-skip numerator."""
    _seed_attempts(store, "medium", 6)
    _seed_decisions(store, "medium", 3, decision="skipped_circuit_open")
    _seed_decisions(store, "medium", 1, decision="degraded")
    c = _one(store, now=_T0 + timedelta(days=5))
    assert c.would_skip_count == 0
    assert c.verdict == VERDICT_POINTLESS


def test_rows_outside_window_are_excluded(store):
    _seed_attempts(store, "medium", 6)
    _seed_decisions(store, "medium", 2)
    # now is 40 days after the seed; default window is 30 → all excluded.
    report = channel_readiness(
        store=store, now=_T0 + timedelta(days=40), min_attempts=5, min_days_observed=3
    )
    assert report.per_channel == []


def test_default_thresholds_are_provisional_but_present():
    assert DEFAULT_MIN_ATTEMPTS == 30
    assert DEFAULT_MIN_DAYS_OBSERVED == 7
