"""publish_success_rate — per-channel publish success metric (Plan 2026-06-15-001 B2).

Derives from the persisted publish.confirmed/unverified (success) and
publish.failed (failure) event kinds; distinct from liveness.
"""

__tier__ = "integration"

from datetime import datetime, timedelta, timezone, UTC

import pytest

from backlink_publisher.events import EventStore, kinds
from backlink_publisher.scorecard.success_rate import publish_success_rate

NOW = datetime(2026, 6, 15, tzinfo=UTC)


def _iso(days_ago: int) -> str:
    return (NOW - timedelta(days=days_ago)).isoformat()


@pytest.fixture
def store(tmp_path):
    return EventStore(path=tmp_path / "events.db")


_counter = iter(range(1, 100000))


def _emit(store, kind, platform, *, days_ago=1):
    payload = {"platform": platform}
    if kind in (kinds.PUBLISH_CONFIRMED, kinds.PUBLISH_UNVERIFIED):
        payload["live_url"] = f"https://{platform}.example/p{next(_counter)}"
    else:  # publish.failed
        payload["error_class"] = "ExternalServiceError"
        payload["error_message_clean"] = "boom"
    rid = store.append(kind, payload, ts_utc=_iso(days_ago))
    assert rid != -1, f"event quarantined: {kind} {payload}"


def test_success_pct_basic(store):
    for _ in range(8):
        _emit(store, kinds.PUBLISH_CONFIRMED, "medium")
    for _ in range(2):
        _emit(store, kinds.PUBLISH_FAILED, "medium")
    report = publish_success_rate(store=store, now=NOW)
    medium = next(c for c in report.per_channel if c.channel == "medium")
    assert medium.attempts == 10
    assert medium.successes == 8
    assert medium.failures == 2
    assert medium.success_pct == 0.8


def test_unverified_counts_as_success(store):
    _emit(store, kinds.PUBLISH_UNVERIFIED, "velog")
    _emit(store, kinds.PUBLISH_FAILED, "velog")
    report = publish_success_rate(store=store, now=NOW, small_sample_max=0)
    velog = next(c for c in report.per_channel if c.channel == "velog")
    assert velog.successes == 1 and velog.failures == 1
    assert velog.success_pct == 0.5


def test_window_excludes_old_events(store):
    _emit(store, kinds.PUBLISH_CONFIRMED, "medium", days_ago=1)
    _emit(store, kinds.PUBLISH_FAILED, "medium", days_ago=90)  # outside 30d window
    report = publish_success_rate(store=store, window_days=30, now=NOW)
    medium = next(c for c in report.per_channel if c.channel == "medium")
    assert medium.attempts == 1
    assert medium.success_pct == 1.0


def test_zero_attempts_channel_absent(store):
    _emit(store, kinds.PUBLISH_CONFIRMED, "medium")
    report = publish_success_rate(store=store, now=NOW)
    assert all(c.channel != "devto" for c in report.per_channel)


def test_small_sample_flag(store):
    _emit(store, kinds.PUBLISH_CONFIRMED, "rentry")
    report = publish_success_rate(store=store, now=NOW, small_sample_max=4)
    rentry = next(c for c in report.per_channel if c.channel == "rentry")
    assert rentry.small_sample is True


def test_tripped_channel_shows_low_rate_not_high(store):
    # A channel that only fails shows 0%, never a misleadingly-high/undefined rate.
    for _ in range(5):
        _emit(store, kinds.PUBLISH_FAILED, "telegraph")
    report = publish_success_rate(store=store, now=NOW)
    telegraph = next(c for c in report.per_channel if c.channel == "telegraph")
    assert telegraph.success_pct == 0.0


def test_weakest_channel_sorts_first(store):
    for _ in range(9):
        _emit(store, kinds.PUBLISH_CONFIRMED, "good")
    _emit(store, kinds.PUBLISH_FAILED, "good")  # 0.9
    for _ in range(5):
        _emit(store, kinds.PUBLISH_FAILED, "bad")  # 0.0
    report = publish_success_rate(store=store, now=NOW)
    channels = [c.channel for c in report.per_channel]
    assert channels.index("bad") < channels.index("good")


def test_overall_aggregate(store):
    for _ in range(3):
        _emit(store, kinds.PUBLISH_CONFIRMED, "a")
    _emit(store, kinds.PUBLISH_FAILED, "b")
    report = publish_success_rate(store=store, now=NOW)
    assert report.overall_attempts == 4
    assert report.overall_successes == 3
    assert report.overall_success_pct == round(3 / 4, 3)
