"""R2c.a — per-platform recheck-strip aggregation (plan 2026-06-05-010 Unit 1).

The channel scorecard surfaces, per platform, how many links' *latest*
``link.rechecked`` verdict is a strip/dead state (``link_stripped`` /
``host_gone`` / ``dofollow_lost``) — so "telegraph strips most of its links" is
visible without opening the per-link drawer.

Two invariants this guards:
1. Strip counts come from ``link.rechecked`` events (recheck provenance), NOT
   from the ledger ``liveness_breakdown`` (verify-signal provenance). They live
   in a SEPARATE ``strip_breakdown`` field and are never summed.
2. A link re-probed twice is counted once (latest verdict wins).
"""
__tier__ = "integration"

from datetime import datetime, timedelta
import json

import pytest

from backlink_publisher.events import EventStore
from backlink_publisher.events.kinds import LINK_RECHECKED
from backlink_publisher.recheck.events_io import (
    derive_strip_counts_by_platform,
    STRIP_VERDICTS,
)
from backlink_publisher.scorecard.engine import build_channel_scorecard, UNATTRIBUTED

NOW = datetime(2026, 6, 5, 12, 0, 0)
RECENT = (NOW - timedelta(days=1)).isoformat(timespec="seconds")
OLD = (NOW - timedelta(days=10)).isoformat(timespec="seconds")


def _article(store, live_url, target):
    return store.add_article(
        {"target_urls_json": json.dumps([target]), "live_url": live_url}
    )


def _recheck(store, *, target, article_id, verdict, ts, platform="telegraph"):
    store.append(
        LINK_RECHECKED,
        {"verdict": verdict, "live_url": "x", "platform": platform},
        target_url=target,
        article_id=article_id,
        ts_utc=ts,
    )


@pytest.fixture
def store(tmp_path):
    return EventStore(path=tmp_path / "events.db")


# ── derive_strip_counts_by_platform (unit) ─────────────────────────────────


def test_happy_path_counts_strip_verdicts_per_platform(store):
    t1 = "https://t.example/1"
    t2 = "https://t.example/2"
    t3 = "https://b.example/3"
    a1, a2, a3 = (
        _article(store, "https://telegra.ph/a1", t1),
        _article(store, "https://telegra.ph/a2", t2),
        _article(store, "https://x.blogspot.com/a3", t3),
    )
    _recheck(store, target=t1, article_id=a1, verdict="link_stripped", ts=RECENT)
    _recheck(store, target=t2, article_id=a2, verdict="dofollow_lost", ts=RECENT)
    _recheck(store, target=t3, article_id=a3, verdict="host_gone", ts=RECENT,
             platform="blogger")

    out = derive_strip_counts_by_platform(store)

    assert out["telegraph"] == {"link_stripped": 1, "host_gone": 0, "dofollow_lost": 1}
    assert out["blogger"] == {"link_stripped": 0, "host_gone": 1, "dofollow_lost": 0}


def test_alive_links_produce_no_strip_entry(store):
    t = "https://t.example/alive"
    a = _article(store, "https://telegra.ph/alive", t)
    _recheck(store, target=t, article_id=a, verdict="alive", ts=RECENT)

    out = derive_strip_counts_by_platform(store)

    # A platform with only-alive links has no strip bucket at all.
    assert "telegraph" not in out


def test_latest_verdict_wins_no_double_count(store):
    """alive(old) → stripped(new): counted once as stripped."""
    t = "https://t.example/flip"
    a = _article(store, "https://telegra.ph/flip", t)
    _recheck(store, target=t, article_id=a, verdict="alive", ts=OLD)
    _recheck(store, target=t, article_id=a, verdict="link_stripped", ts=RECENT)

    out = derive_strip_counts_by_platform(store)

    assert out["telegraph"]["link_stripped"] == 1


def test_recovered_link_not_counted_as_stripped(store):
    """stripped(old) → alive(new): latest is alive, so NOT a strip."""
    t = "https://t.example/recovered"
    a = _article(store, "https://telegra.ph/recovered", t)
    _recheck(store, target=t, article_id=a, verdict="link_stripped", ts=OLD)
    _recheck(store, target=t, article_id=a, verdict="alive", ts=RECENT)

    out = derive_strip_counts_by_platform(store)

    assert "telegraph" not in out


def test_missing_platform_folds_into_none_key(store):
    t = "https://t.example/orphan"
    a = _article(store, "https://telegra.ph/orphan", t)
    _recheck(store, target=t, article_id=a, verdict="link_stripped", ts=RECENT,
             platform=None)

    out = derive_strip_counts_by_platform(store)

    assert out[None]["link_stripped"] == 1


def test_empty_store_returns_empty(store):
    assert derive_strip_counts_by_platform(store) == {}


# ── build_channel_scorecard integration ────────────────────────────────────


def test_scorecard_row_carries_strip_breakdown(store):
    t = "https://t.example/s"
    a = _article(store, "https://telegra.ph/s", t)
    _recheck(store, target=t, article_id=a, verdict="link_stripped", ts=RECENT,
             platform="telegraph")

    rows = build_channel_scorecard(store=store, history=[])
    tele = next(r for r in rows if r.channel == "telegraph")

    assert tele.strip_breakdown == {"link_stripped": 1, "host_gone": 0,
                                    "dofollow_lost": 0}


def test_unattributed_recheck_lands_in_unattributed_row(store):
    t = "https://t.example/u"
    a = _article(store, "https://telegra.ph/u", t)
    _recheck(store, target=t, article_id=a, verdict="host_gone", ts=RECENT,
             platform=None)

    rows = build_channel_scorecard(store=store, history=[])
    row = next(r for r in rows if r.channel == UNATTRIBUTED)

    assert row.strip_breakdown["host_gone"] == 1


def test_strip_breakdown_is_separate_from_liveness_breakdown(store):
    """Characterization: strip_breakdown is a NEW field; the existing four-key
    liveness_breakdown and live_pct/live_dofollow are untouched provenance."""
    rows = build_channel_scorecard(store=store, history=[])
    row = rows[0]

    # Existing ledger field keeps its four-key shape (R2b unchanged).
    assert set(row.liveness_breakdown) == {"failed", "stale", "live", "unverified"}
    # New field is independent, three recheck-verdict keys.
    assert set(row.strip_breakdown) == set(STRIP_VERDICTS)
    # Serialization round-trips the new field for the CLI consumer.
    assert "strip_breakdown" in row.to_jsonl_dict()


def test_registered_channel_without_rechecks_has_zero_strip(store):
    rows = build_channel_scorecard(store=store, history=[])
    # Every row defaults to all-zero strip counts, never None/missing.
    for r in rows:
        assert r.strip_breakdown == {k: 0 for k in STRIP_VERDICTS}
