"""Regression: keep-alive rechecks must not corrupt a link's publish status.

Audit findings [19] and [20]: several "latest event per article" queries had no
``kind`` filter, so a ``link.rechecked`` event appended by the keep-alive/recheck
worker (same article_id) became the newest event and hijacked the publish view.

[19] list_history / get_history_item then derived display status from the recheck
     event -> _status_from_kind('link.rechecked') -> 'unknown', so every monitored
     backlink eventually mislabelled as 'unknown'.
[20] update_status_in_db selected+rewrote that newest event's kind, silently
     destroying the recheck verdict (dropped from every reader that filters
     kind='link.rechecked') AND leaving the real publish event unchanged.

Both are fixed by scoping the "latest event" lookup to publish-status kinds.
"""
from __future__ import annotations

__tier__ = "unit"

import json

import pytest

from backlink_publisher.events import EventStore
from backlink_publisher.events._history_mutations import update_status_in_db
from backlink_publisher.events.history_query import get_history_item, list_history
from backlink_publisher.events.kinds import (
    LINK_RECHECKED,
    PUBLISH_CONFIRMED,
    PUBLISH_UNVERIFIED,
)
from backlink_publisher.recheck.verdicts import ALIVE


@pytest.fixture
def store(tmp_path):
    return EventStore(path=tmp_path / "events.db")


def _article(store, target="https://my.site/", live_url="https://medium.com/a"):
    return store.add_article(
        {
            "target_urls_json": json.dumps([target]),
            "live_url": live_url,
            "platform": "medium",
            "published_at_utc": "2026-05-01T00:00:00+00:00",
        }
    )


# ── [19] display status must survive a recheck ───────────────────────────────


def test_list_history_status_survives_recheck(store):
    aid = _article(store)
    store.append(PUBLISH_CONFIRMED, {"live_url": "https://medium.com/a"}, article_id=aid)
    # Precondition: a confirmed publish reads as 'published'.
    items = {i["id"]: i for i in list_history(store)}
    assert items[str(aid)]["status"] == "published"

    # Keep-alive worker rechecks the (still-alive) link — SAME article_id.
    store.append(LINK_RECHECKED, {"verdict": ALIVE}, article_id=aid)

    items = {i["id"]: i for i in list_history(store)}
    assert items[str(aid)]["status"] == "published", (
        "recheck event hijacked list_history status -> 'unknown'"
    )


def test_get_history_item_status_survives_recheck(store):
    aid = _article(store)
    store.append(PUBLISH_CONFIRMED, {"live_url": "https://medium.com/a"}, article_id=aid)
    store.append(LINK_RECHECKED, {"verdict": ALIVE}, article_id=aid)

    item = get_history_item(aid, store)
    assert item["status"] == "published", (
        "recheck event hijacked get_history_item status -> 'unknown'"
    )


# ── [20] status update must target the publish event, not the recheck ────────


def test_update_status_targets_publish_event_not_recheck(store):
    aid = _article(store)
    store.append(PUBLISH_UNVERIFIED, {"live_url": "https://medium.com/a"}, article_id=aid)
    store.append(LINK_RECHECKED, {"verdict": ALIVE}, article_id=aid)

    assert update_status_in_db(aid, "published", store=store) is True

    with store.connect() as conn:
        n_recheck = conn.execute(
            "SELECT COUNT(*) FROM events WHERE kind = ?", (LINK_RECHECKED,)
        ).fetchone()[0]
        n_unverified = conn.execute(
            "SELECT COUNT(*) FROM events WHERE kind = ?", (PUBLISH_UNVERIFIED,)
        ).fetchone()[0]

    assert n_recheck == 1, "recheck verdict destroyed - its kind was rewritten"
    assert n_unverified == 0, "the publish event was not the one updated to confirmed"
