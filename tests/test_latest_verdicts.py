"""Unit tests for the shared ``recheck.latest_verdicts`` reader.

The latest-verdict-per-link scan is shared by ``overlay.build_discount_map`` and
``scorecard.links.derive_links_by_channel``; these tests pin the contract that both
depend on — keying on canonical ``live_url`` (article_id fallback) and counting
unkeyable rows loudly rather than dropping them silently.
"""
from __future__ import annotations

__tier__ = "unit"

import pytest

from backlink_publisher.events import EventStore
from backlink_publisher.events.kinds import LINK_RECHECKED
from backlink_publisher.recheck import verdicts
from backlink_publisher.recheck.latest_verdicts import latest_link_verdicts


@pytest.fixture
def store(tmp_path):
    return EventStore(path=tmp_path / "events.db")


def test_empty_store_returns_empty_and_zero_unkeyable(store):
    latest, unkeyable = latest_link_verdicts(store)
    assert latest == {}
    assert unkeyable == 0


def test_unkeyable_row_is_counted_not_dropped(store):
    # No live_url in payload AND NULL article_id → unidentifiable. Must surface in
    # the count, never vanish silently (projector-silent-drop lesson).
    store.append(LINK_RECHECKED, {"verdict": verdicts.HOST_GONE}, article_id=None,
                 target_url="https://t/1")
    latest, unkeyable = latest_link_verdicts(store)
    assert latest == {}
    assert unkeyable == 1


def test_article_id_fallback_key_when_no_live_url(store):
    # NULL live_url but a present article_id → keyed on 'aid:<id>', still surfaced.
    store.append(LINK_RECHECKED, {"verdict": verdicts.LINK_STRIPPED}, article_id=7,
                 target_url="https://t/1")
    latest, unkeyable = latest_link_verdicts(store)
    assert unkeyable == 0
    assert "aid:7" in latest
    assert latest["aid:7"].payload["verdict"] == verdicts.LINK_STRIPPED
