"""R6: per-target dofollow derivation + verdict-map join in history_query.

The badge value is keyed off the operator link's own latest link.rechecked
verdict, independent of any page-wide nofollow signal. The probe already
cross-checks the channel manifest, so dofollow_lost is always a real alarm and
expected-nofollow channels arrive as alive + expected_nofollow (→ neutral).
"""

from __future__ import annotations

__tier__ = "integration"

import json

import pytest

from backlink_publisher.events import EventStore
from backlink_publisher.events.kinds import LINK_RECHECKED, PUBLISH_CONFIRMED
from backlink_publisher.events.history_query import (
    derive_target_dofollow,
    get_history_item,
    list_history,
)
from backlink_publisher.recheck import verdicts


class TestDeriveTargetDofollow:
    def test_alive_is_dofollow(self):
        assert derive_target_dofollow(verdicts.ALIVE) == "dofollow"

    def test_alive_but_expected_nofollow_is_unverified_not_alarm(self):
        # A nofollow channel (dofollow_status False) → neutral, never dofollow_lost.
        assert derive_target_dofollow(verdicts.ALIVE, expected_nofollow=True) == "unverified"

    def test_dofollow_lost_is_alarm(self):
        assert derive_target_dofollow(verdicts.DOFOLLOW_LOST) == "dofollow_lost"

    def test_link_stripped_is_stripped(self):
        assert derive_target_dofollow(verdicts.LINK_STRIPPED) == "stripped"

    def test_host_gone_is_stripped(self):
        assert derive_target_dofollow(verdicts.HOST_GONE) == "stripped"

    def test_probe_error_is_unverified(self):
        assert derive_target_dofollow(verdicts.PROBE_ERROR) == "unverified"

    def test_none_is_unverified(self):
        assert derive_target_dofollow(None) == "unverified"


@pytest.fixture
def store(tmp_path):
    return EventStore(path=tmp_path / "events.db")


def _article(store, target, live_url, *, platform="medium"):
    return store.add_article(
        {"target_urls_json": json.dumps([target]), "live_url": live_url,
         "platform": platform, "published_at_utc": "2026-05-01T00:00:00+00:00"}
    )


def _recheck(store, aid, verdict, *, expected_nofollow=False, ts="2026-06-01T00:00:00+00:00"):
    store.append(
        LINK_RECHECKED,
        {"verdict": verdict, "expected_nofollow": expected_nofollow},
        article_id=aid, ts_utc=ts,
    )


def test_list_history_joins_latest_verdict(store):
    aid = _article(store, "https://my.site/", "https://medium.com/a")
    _recheck(store, aid, verdicts.DOFOLLOW_LOST)
    items = {i["id"]: i for i in list_history(store)}
    assert items[str(aid)]["target_dofollow"] == "dofollow_lost"


def test_latest_verdict_wins(store):
    aid = _article(store, "https://my.site/", "https://medium.com/a")
    _recheck(store, aid, verdicts.ALIVE, ts="2026-06-01T00:00:00+00:00")
    _recheck(store, aid, verdicts.LINK_STRIPPED, ts="2026-06-02T00:00:00+00:00")
    item = get_history_item(aid, store)
    assert item["target_dofollow"] == "stripped"   # newer verdict wins


def test_no_verdict_defaults_unverified(store):
    aid = _article(store, "https://my.site/", "https://medium.com/a")
    item = get_history_item(aid, store)
    assert item["target_dofollow"] == "unverified"


def test_expected_nofollow_channel_not_alarmed(store):
    aid = _article(store, "https://my.site/", "https://t.me/a", platform="telegraph")
    _recheck(store, aid, verdicts.ALIVE, expected_nofollow=True)
    item = get_history_item(aid, store)
    assert item["target_dofollow"] == "unverified"   # neutral, not dofollow_lost
