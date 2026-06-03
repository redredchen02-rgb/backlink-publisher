"""Unit 1: events.db schema v4 — new columns and event kinds (Plan 2026-05-28-007).

Tests the v4 schema migration: new columns on ``articles`` table (platform,
verified_at, verify_error, migration_dedup_key), the partial UNIQUE index on
migration_dedup_key, and two new event kinds (publish.verified,
publish.verify_failed).
"""

from __future__ import annotations

import sqlite3

import pytest

from backlink_publisher.events import kinds as kinds_module
from backlink_publisher.events import schema as schema_module
from backlink_publisher.events.store import EventStore


@pytest.fixture(autouse=True)
def _isolate_events_db(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
    yield


def test_schema_v3_upgrades_to_v4(tmp_path):
    """Creating a v3 database then connecting with v4 binary upgrades cleanly."""
    store = EventStore()
    with store.connect() as conn:
        version = conn.execute(
            "SELECT MAX(version) FROM schema_version"
        ).fetchone()[0]
    assert version == 4
    with store.connect() as conn:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(articles)")}
    for col in ("platform", "verified_at", "verify_error", "migration_dedup_key"):
        assert col in cols, f"column {col} missing from articles after v4 upgrade"


def test_v4_is_idempotent_on_reconnect(tmp_path):
    """Calling maybe_upgrade_schema twice on a v4 database is a no-op."""
    store = EventStore()
    with store.connect():
        pass
    with store.connect() as conn:
        version = conn.execute(
            "SELECT MAX(version) FROM schema_version"
        ).fetchone()[0]
    assert version == 4


def test_add_article_with_platform_stores_column(tmp_path):
    """add_article() stores platform in the column, not just JSON."""
    store = EventStore()
    article_id = store.add_article({
        "live_url": "https://op.blogspot.com/2026/05/post.html",
        "platform": "blogger",
    })
    rows = store.query(
        "SELECT platform FROM articles WHERE article_id = ?",
        (article_id,),
    )
    assert rows[0]["platform"] == "blogger"


def test_add_article_with_migration_dedup_key(tmp_path):
    """migration_dedup_key can be set and enforces uniqueness."""
    store = EventStore()
    store.add_article({
        "live_url": "https://op.blogspot.com/a.html",
        "migration_dedup_key": "abc123",
    })
    with pytest.raises(sqlite3.IntegrityError):
        store.add_article({
            "live_url": "https://op.blogspot.com/b.html",
            "migration_dedup_key": "abc123",
        })


def test_migration_dedup_partial_index_allows_nulls(tmp_path):
    """Unique index is partial (WHERE NOT NULL), so multiple NULL keys are OK."""
    store = EventStore()
    a1 = store.add_article({"live_url": "https://op.blogspot.com/x.html"})
    a2 = store.add_article({"live_url": "https://op.blogspot.com/y.html"})
    assert a1 > 0 and a2 > 0
    rows = store.query(
        "SELECT article_id FROM articles "
        "WHERE migration_dedup_key IS NULL"
    )
    assert len(rows) >= 2


def test_append_publish_verified(tmp_path):
    """publish.verified event can be appended and requires article_id."""
    store = EventStore()
    event_id = store.append(
        "publish.verified",
        {"article_id": 1},
    )
    assert isinstance(event_id, int) and event_id > 0
    rows = store.query(
        "SELECT kind, payload_json FROM events WHERE id = ?",
        (event_id,),
    )
    assert rows[0]["kind"] == "publish.verified"


def test_append_publish_verify_failed(tmp_path):
    """publish.verify_failed event can be appended."""
    store = EventStore()
    event_id = store.append(
        "publish.verify_failed",
        {"article_id": 1, "error_message": "timeout"},
    )
    assert isinstance(event_id, int) and event_id > 0
    rows = store.query(
        "SELECT kind, payload_json FROM events WHERE id = ?",
        (event_id,),
    )
    assert rows[0]["kind"] == "publish.verify_failed"


def test_publish_verified_missing_article_id_quarantines(tmp_path):
    """publish.verified missing floor field article_id → quarantined."""
    store = EventStore()
    result = store.append("publish.verified", {"live_url": "https://x.com"})
    assert result == -1
    rows = store.query(
        "SELECT reason FROM quarantine_log "
        "WHERE source = 'publish.verified'"
    )
    assert len(rows) >= 1
    assert "missing_field" in rows[0]["reason"]


def test_publish_verify_failed_missing_error_message_quarantines(tmp_path):
    """publish.verify_failed missing error_message → quarantined."""
    store = EventStore()
    result = store.append(
        "publish.verify_failed", {"article_id": 1}
    )
    assert result == -1


def test_new_kinds_are_in_kinds_registry():
    """Both new kinds appear in KINDS set and have REQUIRED_FIELDS entries."""
    assert "publish.verified" in kinds_module.KINDS
    assert "publish.verify_failed" in kinds_module.KINDS
    assert "article_id" in kinds_module.REQUIRED_FIELDS.get(
        "publish.verified", frozenset()
    )
    assert "error_message" in kinds_module.REQUIRED_FIELDS.get(
        "publish.verify_failed", frozenset()
    )
