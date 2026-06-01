"""build_channel_scorecard — per-channel pivot, declared‖measured vector.

Real registry values used: medium=dofollow, blogger=dofollow, devto=nofollow(high).
"""

import json
from datetime import datetime, timedelta

import pytest

from backlink_publisher.events import EventStore, kinds
from backlink_publisher.scorecard import build_channel_scorecard
from backlink_publisher.scorecard.engine import UNATTRIBUTED
from backlink_publisher.scorecard.model import AXIS_INERT, ChannelScoreRow

T = "https://site.com/page"
FRESH = (datetime.now() - timedelta(days=1)).isoformat()


def _article(store, live_url, target=T):
    return store.add_article({"target_urls_json": json.dumps([target]), "live_url": live_url})


@pytest.fixture
def store(tmp_path):
    s = EventStore(path=tmp_path / "events.db")
    _article(s, "https://medium.com/l1")
    _article(s, "https://medium.com/l2")
    _article(s, "https://devto.example/l3")
    return s


def _hist(*, medium_verified=None, devto_error=None):
    return [
        {"id": "h1", "platform": "medium", "target_url": T,
         "article_urls": ["https://medium.com/l1"], "status": "published",
         **({"verified_at": medium_verified} if medium_verified else {})},
        {"id": "h2", "platform": "medium", "target_url": T,
         "article_urls": ["https://medium.com/l2"], "status": "published"},
        {"id": "h3", "platform": "devto", "target_url": T,
         "article_urls": ["https://devto.example/l3"], "status": "published",
         **({"verify_error": devto_error} if devto_error else {})},
    ]


def _row(rows, channel):
    return next(r for r in rows if r.channel == channel)


# ── happy path: declared ‖ measured ─────────────────────────────────────────

def test_declared_half_from_registry(store):
    rows = build_channel_scorecard(store=store, history=_hist())
    medium = _row(rows, "medium")
    assert medium.declared_dofollow == "dofollow"
    assert medium.declared_referral_value is None  # dofollow tier carries no high/low
    devto = _row(rows, "devto")
    assert devto.declared_dofollow == "nofollow"
    assert devto.declared_referral_value == "high"


def test_measured_placements_and_liveness(store):
    rows = build_channel_scorecard(store=store, history=_hist(medium_verified=FRESH))
    medium = _row(rows, "medium")
    assert medium.total_links == 2
    assert medium.live_links == 1            # only l1 verified fresh
    assert medium.live_dofollow == 1         # medium is dofollow + the live link
    assert medium.live_pct == round(1 / 2, 3)
    assert medium.liveness_breakdown["live"] == 1
    assert medium.liveness_breakdown["unverified"] == 1


def test_failed_liveness_counted(store):
    rows = build_channel_scorecard(store=store, history=_hist(devto_error="410 gone"))
    devto = _row(rows, "devto")
    assert devto.liveness_breakdown["failed"] == 1
    assert devto.live_links == 0


# ── every registered channel appears (declared half), even with 0 links ──────

def test_registered_channel_with_no_links_still_present(store):
    rows = build_channel_scorecard(store=store, history=_hist())
    channels = {r.channel for r in rows}
    # telegraph is registered but unused in this fixture → must still appear.
    assert "telegraph" in channels
    tele = _row(rows, "telegraph")
    assert tele.total_links == 0
    assert tele.live_pct is None             # no links → not a misleading 0.0
    assert tele.small_sample is True
    assert tele.sample_note == "insufficient-data"


# ── sample honesty (plan R12) ────────────────────────────────────────────────

def test_small_sample_flag_threshold(store):
    rows = build_channel_scorecard(store=store, history=_hist(), small_sample_max=1)
    medium = _row(rows, "medium")  # 2 links > 1 → not small
    assert medium.small_sample is False
    assert medium.sample_note == "ok"
    devto = _row(rows, "devto")    # 1 link <= 1 → small
    assert devto.small_sample is True


# ── inert axes + no composite (plan D-B / D-G) ───────────────────────────────

def test_deferred_axes_are_inert_not_zero(store):
    rows = build_channel_scorecard(store=store, history=_hist())
    medium = _row(rows, "medium")
    assert medium.referral_traffic == AXIS_INERT
    assert medium.gsc_discovery == AXIS_INERT
    assert medium.ai_retrievability == AXIS_INERT


def test_no_composite_score_field():
    # The row is a signal vector — there must be no single blended "score".
    keys = set(ChannelScoreRow(channel="x").to_jsonl_dict().keys())
    assert not (keys & {"score", "composite", "rank", "index", "value_score"})


# ── declared-vs-measured divergence (advisory) ───────────────────────────────

def test_divergence_dofollow_without_live_dofollow(store):
    # medium is dofollow but nothing is verified-live → divergence flag.
    rows = build_channel_scorecard(store=store, history=_hist())
    medium = _row(rows, "medium")
    assert "declared-dofollow:no-live-dofollow-observed" in medium.divergence


def test_no_divergence_when_no_measured_links(store):
    rows = build_channel_scorecard(store=store, history=_hist())
    tele = _row(rows, "telegraph")  # 0 links → divergence undefined, empty
    assert tele.divergence == []


# ── platform augmentation from confirmed-event payload (sparse history) ───────

def test_platform_resolved_from_confirmed_event_when_history_empty(tmp_path):
    # Real-world case: history_store is empty but publish.confirmed payloads
    # carry the platform (joined to the article by article_id).
    s = EventStore(path=tmp_path / "events.db")
    aid = _article(s, "https://medium.com/x1")
    s.append(
        kinds.PUBLISH_CONFIRMED,
        {"live_url": "https://medium.com/x1", "platform": "medium"},
        target_url=T,
        article_id=aid,
    )
    rows = build_channel_scorecard(store=s, history=[])
    medium = _row(rows, "medium")
    assert medium.total_links == 1            # attributed via the event payload
    # And it is NOT dumped into the unattributed bucket.
    assert all(r.total_links == 0 for r in rows if r.channel == UNATTRIBUTED) or \
        not any(r.channel == UNATTRIBUTED for r in rows)


def test_unresolvable_platform_goes_to_unattributed(tmp_path):
    s = EventStore(path=tmp_path / "events.db")
    _article(s, "https://nowhere.example/z1")  # no history, no confirmed event
    rows = build_channel_scorecard(store=s, history=[])
    una = _row(rows, UNATTRIBUTED)
    assert una.total_links == 1
    assert una.declared_dofollow == "unregistered"


# ── empty stores → only the declared (registered) channels, all 0/0 ──────────

def test_empty_data_lists_registered_channels(tmp_path):
    s = EventStore(path=tmp_path / "empty.db")
    rows = build_channel_scorecard(store=s, history=[])
    assert rows  # registered channels still listed
    assert all(r.total_links == 0 for r in rows)
    assert all(r.referral_traffic == AXIS_INERT for r in rows)
