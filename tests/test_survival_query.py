"""R5: 30-day survival-rate cohort query.

Verifies the maturity window, the latest-definitive-verdict join, sample-size
honesty (n<2 suppression), the maturing/stale/empty states, and the
example.com exclusion — all derived from the link.rechecked time series.
"""

from __future__ import annotations

__tier__ = "integration"

from datetime import datetime, timedelta, timezone

import pytest

from backlink_publisher.events import EventStore
from backlink_publisher.events.kinds import LINK_RECHECKED, PUBLISH_CONFIRMED
from backlink_publisher.events.survival_query import compute_survival
from backlink_publisher.recheck import verdicts

NOW = datetime(2026, 6, 5, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def store(tmp_path):
    return EventStore(path=tmp_path / "events.db")


def _confirm(store, aid, *, days_ago, host="medium.com", url=None):
    url = url or f"https://{host}/{aid}"
    ts = (NOW - timedelta(days=days_ago)).isoformat()
    store.append(
        PUBLISH_CONFIRMED, {"live_url": url}, host=host, article_id=aid, ts_utc=ts
    )


def _recheck(store, aid, verdict, *, days_ago=1):
    ts = (NOW - timedelta(days=days_ago)).isoformat()
    store.append(LINK_RECHECKED, {"verdict": verdict}, article_id=aid, ts_utc=ts)


def test_happy_rate_and_sample_size(store):
    for i in range(1, 11):
        _confirm(store, i, days_ago=40)
    for i in range(1, 8):       # 7 alive
        _recheck(store, i, verdicts.ALIVE)
    for i in range(8, 11):      # 3 stripped
        _recheck(store, i, verdicts.LINK_STRIPPED)
    v = compute_survival(store, now=NOW)
    assert v["state"] == "ok"
    assert v["survival_rate"] == pytest.approx(0.70)
    assert v["sample_size"] == 10
    assert v["survived"] == 7


def test_immature_link_excluded_from_rate(store):
    for i in range(1, 4):       # 3 mature alive
        _confirm(store, i, days_ago=40)
        _recheck(store, i, verdicts.ALIVE)
    _confirm(store, 99, days_ago=20)   # 20d < 30d → maturing
    v = compute_survival(store, now=NOW)
    assert v["maturing_count"] == 1
    assert v["mature_count"] == 3       # immature not in the rate denominator
    assert v["sample_size"] == 3


def test_insufficient_sample_suppresses_rate(store):
    _confirm(store, 1, days_ago=40)
    _recheck(store, 1, verdicts.ALIVE)
    v = compute_survival(store, now=NOW)
    assert v["state"] == "insufficient"
    assert v["survival_rate"] is None     # suppressed, n < 2
    assert v["sample_size"] == 1          # surfaced honestly


def test_empty_when_no_mature_links(store):
    v = compute_survival(store, now=NOW)
    assert v["state"] == "empty"
    assert v["survival_rate"] is None


def test_stale_mature_link_flags_partial(store):
    for i in range(1, 4):       # 3 judged-alive (definitive)
        _confirm(store, i, days_ago=40)
        _recheck(store, i, verdicts.ALIVE)
    _confirm(store, 50, days_ago=45)       # mature, but never rechecked → stale
    v = compute_survival(store, now=NOW)
    assert v["state"] == "ok"
    assert v["stale"] is True
    assert v["stale_count"] == 1
    assert v["partial"] is True
    assert v["stale_days"] >= 45 - 1       # overdue by ~45 days
    assert v["sample_size"] == 3           # stale link not in denominator


def test_latest_verdict_wins(store):
    _confirm(store, 1, days_ago=40)
    _confirm(store, 2, days_ago=40)
    _recheck(store, 1, verdicts.ALIVE, days_ago=20)
    _recheck(store, 1, verdicts.LINK_STRIPPED, days_ago=2)   # newer → dead
    _recheck(store, 2, verdicts.ALIVE, days_ago=2)
    v = compute_survival(store, now=NOW)
    assert v["sample_size"] == 2
    assert v["survived"] == 1               # link 1 counts as dead now
    assert v["survival_rate"] == pytest.approx(0.5)


def test_probe_error_does_not_clobber_definitive(store):
    _confirm(store, 1, days_ago=40)
    _confirm(store, 2, days_ago=40)
    _recheck(store, 1, verdicts.ALIVE, days_ago=10)
    _recheck(store, 1, verdicts.PROBE_ERROR, days_ago=1)   # indeterminate, skipped
    _recheck(store, 2, verdicts.ALIVE, days_ago=1)
    v = compute_survival(store, now=NOW)
    assert v["sample_size"] == 2            # link 1 still judged (alive stands)
    assert v["survived"] == 2


def test_example_com_never_counted(store):
    _confirm(store, 1, days_ago=40, host="example.com")
    _recheck(store, 1, verdicts.ALIVE)
    _confirm(store, 2, days_ago=40, host="medium.com")
    _recheck(store, 2, verdicts.ALIVE)
    v = compute_survival(store, now=NOW)
    assert v["mature_count"] == 1           # only medium.com
    assert v["sample_size"] == 1
