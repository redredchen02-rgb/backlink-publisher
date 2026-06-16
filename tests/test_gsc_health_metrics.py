"""Tests for indexation_status() and ranking_trend() in health_metrics
(Plan 2026-06-16-003 Unit 6)."""

from __future__ import annotations

__tier__ = "integration"

import json

import pytest

from backlink_publisher.events import EventStore
from backlink_publisher.events.kinds import GSC_PAGE_SIGNAL, RANKING_SNAPSHOT
from webui_app import health_metrics as hm


@pytest.fixture(autouse=True)
def _isolate_db(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
    yield


def _store() -> EventStore:
    return EventStore()


def _seed_page_signal(
    store: EventStore,
    *,
    target_url: str,
    page_url: str,
    has_impressions: bool,
    ts_utc: str = "2026-06-01T10:00:00+00:00",
) -> None:
    store.append(
        GSC_PAGE_SIGNAL,
        {"page_url": page_url, "has_impressions": has_impressions, "coverage_state": "x", "checked_at": "2026-06-01"},
        target_url=target_url,
        ts_utc=ts_utc,
    )


def _seed_ranking(
    store: EventStore,
    *,
    keyword: str,
    avg_position: float | None,
    date_range_start: str,
    date_range_end: str,
    ts_utc: str,
) -> None:
    store.append(
        RANKING_SNAPSHOT,
        {
            "keyword": keyword,
            "avg_position": avg_position,
            "impressions": 10,
            "clicks": 1,
            "date_range_start": date_range_start,
            "date_range_end": date_range_end,
        },
        target_url="sc-domain:example.com",
        ts_utc=ts_utc,
    )


# ---------------------------------------------------------------------------
# indexation_status
# ---------------------------------------------------------------------------


def test_indexation_status_empty_returns_empty_list() -> None:
    store = _store()
    result = hm.indexation_status(store)
    assert result == []


def test_indexation_status_counts_correctly() -> None:
    store = _store()
    for i in range(3):
        _seed_page_signal(store, target_url="https://t.com", page_url=f"https://ext.com/p{i}", has_impressions=True)
    for i in range(2):
        _seed_page_signal(store, target_url="https://t.com", page_url=f"https://ext.com/q{i}", has_impressions=False)

    result = hm.indexation_status(store)
    assert len(result) == 1
    row = result[0]
    assert row["target_url"] == "https://t.com"
    assert row["total"] == 5
    assert row["appeared_count"] == 3
    assert row["absent_count"] == 2


def test_indexation_status_multiple_targets() -> None:
    store = _store()
    _seed_page_signal(store, target_url="https://a.com", page_url="https://x.com/p1", has_impressions=True)
    _seed_page_signal(store, target_url="https://b.com", page_url="https://y.com/p2", has_impressions=False)

    result = hm.indexation_status(store)
    assert len(result) == 2
    urls = {r["target_url"] for r in result}
    assert urls == {"https://a.com", "https://b.com"}


# ---------------------------------------------------------------------------
# ranking_trend
# ---------------------------------------------------------------------------


def test_ranking_trend_empty_returns_empty_list() -> None:
    store = _store()
    result = hm.ranking_trend(store)
    assert result == []


def test_ranking_trend_improvement() -> None:
    store = _store()
    # Baseline: position 18 (older)
    _seed_ranking(store, keyword="seo tips", avg_position=18.0,
                  date_range_start="2026-04-17", date_range_end="2026-05-17",
                  ts_utc="2026-05-17T00:00:00+00:00")
    # Latest: position 11 (newer)
    _seed_ranking(store, keyword="seo tips", avg_position=11.0,
                  date_range_start="2026-05-17", date_range_end="2026-06-16",
                  ts_utc="2026-06-16T00:00:00+00:00")

    result = hm.ranking_trend(store)
    assert len(result) == 1
    kw = result[0]
    assert kw["keyword"] == "seo tips"
    assert kw["baseline_position"] == 18.0
    assert kw["latest_position"] == 11.0
    assert kw["delta"] == 7.0
    assert kw["trend"] == "↑"


def test_ranking_trend_decline() -> None:
    store = _store()
    _seed_ranking(store, keyword="link building", avg_position=5.0,
                  date_range_start="2026-04-17", date_range_end="2026-05-17",
                  ts_utc="2026-05-17T00:00:00+00:00")
    _seed_ranking(store, keyword="link building", avg_position=9.0,
                  date_range_start="2026-05-17", date_range_end="2026-06-16",
                  ts_utc="2026-06-16T00:00:00+00:00")

    result = hm.ranking_trend(store)
    kw = result[0]
    assert kw["delta"] == -4.0
    assert kw["trend"] == "↓"


def test_ranking_trend_single_snapshot_shows_dash() -> None:
    store = _store()
    # Only one snapshot: baseline and latest are the same row
    _seed_ranking(store, keyword="seo", avg_position=15.0,
                  date_range_start="2026-05-17", date_range_end="2026-06-16",
                  ts_utc="2026-06-16T00:00:00+00:00")

    result = hm.ranking_trend(store)
    # With only one row, baseline == latest, delta == 0, trend == →
    kw = result[0]
    assert kw["delta"] == 0.0
    assert kw["trend"] == "→"


def test_ranking_trend_none_position_shows_dash() -> None:
    store = _store()
    # keyword absent from GSC in both snapshots: avg_position stored as None
    _seed_ranking(store, keyword="unknown kw", avg_position=None,
                  date_range_start="2026-04-17", date_range_end="2026-05-17",
                  ts_utc="2026-05-17T00:00:00+00:00")
    _seed_ranking(store, keyword="unknown kw", avg_position=None,
                  date_range_start="2026-05-17", date_range_end="2026-06-16",
                  ts_utc="2026-06-16T00:00:00+00:00")

    result = hm.ranking_trend(store)
    assert len(result) == 1
    kw = result[0]
    assert kw["keyword"] == "unknown kw"
    assert kw["delta"] is None
    assert kw["trend"] == "—"
