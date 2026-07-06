"""Tests for purge_failed_from_db in history_query."""
from __future__ import annotations

__tier__ = "integration"

import pytest

from backlink_publisher.events import kinds as _kinds
from backlink_publisher.events.history_query import purge_failed_from_db
from backlink_publisher.events.store import EventStore


@pytest.fixture(autouse=True)
def _isolate_events_db(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))


_FAILED_PAYLOAD = {"error_class": "RuntimeError", "error_message_clean": "boom"}
_CONFIRMED_PAYLOAD = {"live_url": "https://example.com/ok", "platform": "blogger"}
_UNVERIFIED_PAYLOAD = {"live_url": "https://example.com/unverified", "platform": "blogger"}


def _add_article_with_event(store: EventStore, kind: str, url: str) -> int:
    article_id = store.add_article({"live_url": url})
    if kind == _kinds.PUBLISH_FAILED:
        payload = _FAILED_PAYLOAD
    elif kind == _kinds.PUBLISH_CONFIRMED:
        payload = {**_CONFIRMED_PAYLOAD, "live_url": url}
    else:
        payload = {**_UNVERIFIED_PAYLOAD, "live_url": url}
    eid = store.append(
        kind=kind,
        payload=payload,
        ts_raw="2026-06-05T00:00:00Z",
        ts_utc="2026-06-05T00:00:00+00:00",
        article_id=article_id,
        target_url=url,
        host="example.com",
    )
    assert eid > 0, f"append returned {eid} — payload quarantined?"
    return article_id


def _add_orphan_event(store: EventStore, kind: str, url: str) -> int:
    if kind == _kinds.PUBLISH_FAILED:
        payload = _FAILED_PAYLOAD
    elif kind == _kinds.PUBLISH_CONFIRMED:
        payload = {**_CONFIRMED_PAYLOAD, "live_url": url}
    else:
        payload = {**_UNVERIFIED_PAYLOAD, "live_url": url}
    eid = store.append(
        kind=kind,
        payload=payload,
        ts_raw="2026-06-05T00:00:00Z",
        ts_utc="2026-06-05T00:00:00+00:00",
        article_id=None,
        target_url=url,
        host="example.com",
    )
    assert eid > 0, f"append returned {eid} — payload quarantined?"
    return eid


def test_purge_removes_failed_articles_and_events():
    store = EventStore()
    _add_article_with_event(store, _kinds.PUBLISH_FAILED, "https://a.com/1")
    _add_article_with_event(store, _kinds.PUBLISH_FAILED, "https://a.com/2")
    _add_article_with_event(store, _kinds.PUBLISH_CONFIRMED, "https://a.com/3")

    removed = purge_failed_from_db(store)

    assert removed == 2
    with store.connect() as conn:
        remaining = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
        assert remaining == 1  # confirmed article survives


def test_purge_removes_orphan_failed_events():
    store = EventStore()
    _add_orphan_event(store, _kinds.PUBLISH_FAILED, "https://b.com/orphan1")
    _add_orphan_event(store, _kinds.PUBLISH_FAILED, "https://b.com/orphan2")
    _add_orphan_event(store, _kinds.PUBLISH_UNVERIFIED, "https://b.com/ok")

    removed = purge_failed_from_db(store)

    assert removed == 2
    with store.connect() as conn:
        remaining = conn.execute(
            "SELECT COUNT(*) FROM events WHERE kind = ?",
            (_kinds.PUBLISH_FAILED,),
        ).fetchone()[0]
        assert remaining == 0


def test_purge_returns_zero_when_nothing_to_remove():
    store = EventStore()
    _add_article_with_event(store, _kinds.PUBLISH_CONFIRMED, "https://c.com/ok")

    removed = purge_failed_from_db(store)

    assert removed == 0


def test_purge_handles_empty_db():
    store = EventStore()
    assert purge_failed_from_db(store) == 0
