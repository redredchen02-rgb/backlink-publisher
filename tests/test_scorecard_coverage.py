"""recheck_coverage — within-window coverage measurement (Plan 2026-06-15-001 B1).

Mirrors the build_channel_scorecard fixture pattern; coverage reuses that engine
so "covered" (live|failed) and "uncovered" (stale|unverified) match the scorecard.
"""

__tier__ = "integration"

from datetime import datetime, timedelta
import json

import pytest

from backlink_publisher.events import EventStore
from backlink_publisher.scorecard.coverage import recheck_coverage

T = "https://site.com/page"
FRESH = (datetime.now() - timedelta(days=1)).isoformat()
STALE = (datetime.now() - timedelta(days=90)).isoformat()


def _article(store, live_url, target=T):
    return store.add_article(
        {"target_urls_json": json.dumps([target]), "live_url": live_url}
    )


@pytest.fixture
def store(tmp_path):
    s = EventStore(path=tmp_path / "events.db")
    _article(s, "https://medium.com/l1")
    _article(s, "https://medium.com/l2")
    _article(s, "https://devto.example/l3")
    return s


def _hist(*, l1_verified=None, l2_verified=None, l3_error=None):
    return [
        {"id": "h1", "platform": "medium", "target_url": T,
         "article_urls": ["https://medium.com/l1"], "status": "published",
         **({"verified_at": l1_verified} if l1_verified else {})},
        {"id": "h2", "platform": "medium", "target_url": T,
         "article_urls": ["https://medium.com/l2"], "status": "published",
         **({"verified_at": l2_verified} if l2_verified else {})},
        {"id": "h3", "platform": "devto", "target_url": T,
         "article_urls": ["https://devto.example/l3"], "status": "published",
         **({"verify_error": l3_error} if l3_error else {})},
    ]


def test_live_and_failed_count_as_covered(store):
    # l1 fresh-verified (live), l3 verify_error (failed) -> covered; l2 unverified.
    report = recheck_coverage(store=store, history=_hist(l1_verified=FRESH, l3_error="dead"))
    assert report.total_links == 3
    assert report.covered == 2  # l1 live + l3 failed
    assert report.coverage_pct == round(2 / 3, 3)
    assert report.meets_target is True  # 0.667 >= 0.5


def test_stale_and_unverified_are_uncovered(store):
    # l1 stale (verified long ago), l2 unverified, l3 unverified -> 0 covered.
    report = recheck_coverage(store=store, history=_hist(l1_verified=STALE))
    assert report.covered == 0
    assert report.coverage_pct == 0.0
    assert report.meets_target is False


def test_meets_target_boundary(store):
    # All three fresh -> 100% covered, target met.
    report = recheck_coverage(
        store=store, history=_hist(l1_verified=FRESH, l2_verified=FRESH, l3_error="x")
    )
    assert report.coverage_pct == 1.0
    assert report.meets_target is True


def test_custom_target_pct(store):
    report = recheck_coverage(
        store=store, history=_hist(l1_verified=FRESH), target_pct=0.5
    )
    # only l1 covered -> 1/3 = 0.333 < 0.5
    assert report.coverage_pct == round(1 / 3, 3)
    assert report.meets_target is False


def test_per_channel_lowest_coverage_first(store):
    report = recheck_coverage(store=store, history=_hist(l1_verified=FRESH))
    # medium: 1/2 covered = 0.5 ; devto: 0/1 = 0.0 -> devto sorts first
    channels = [c.channel for c in report.per_channel]
    assert channels.index("devto") < channels.index("medium")
    devto = next(c for c in report.per_channel if c.channel == "devto")
    assert devto.coverage_pct == 0.0


def test_declared_only_channels_excluded_from_denominator(store):
    # Registered channels with zero links must not dilute the denominator.
    report = recheck_coverage(store=store, history=_hist(l1_verified=FRESH))
    assert report.total_links == 3  # only the 3 real links, not all registered platforms
