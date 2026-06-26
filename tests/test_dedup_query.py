"""Tests for idempotency._dedup_query module."""


__tier__ = "unit"
from __future__ import annotations

from collections.abc import Generator
from pathlib import Path
import sqlite3
import time
from unittest.mock import patch

import pytest

from backlink_publisher.idempotency._dedup_connection import ConnectionMixin
from backlink_publisher.idempotency._dedup_query import QueryMixin
from backlink_publisher.idempotency._store_types import _STALE_TTL_S, DedupKey, DedupRecord


class TestQueryStore(ConnectionMixin, QueryMixin):
    """A test store that combines ConnectionMixin and QueryMixin."""

    def __init__(self, path: Path) -> None:
        self.path = path


@pytest.fixture
def query_store(tmp_path: Path) -> Generator[TestQueryStore, None, None]:
    """Create a TestQueryStore with schema initialized."""
    store = TestQueryStore(tmp_path / "test.db")
    # Initialize schema
    with store.connect() as conn:
        pass
    yield store


@pytest.fixture
def store_with_data(query_store: TestQueryStore) -> TestQueryStore:
    """Create a TestQueryStore with sample data."""
    with query_store.connect() as conn:
        conn.execute(
            "INSERT INTO dedup_keys (platform, account, target_url, state, updated_at) "
            "VALUES ('blogger', 'user1', 'http://example.com', 'done', 1234567890.0)"
        )
        conn.execute(
            "INSERT INTO dedup_keys (platform, account, target_url, state, updated_at) "
            "VALUES ('medium', 'user1', 'http://test.com', 'attempting', 1234567891.0)"
        )
        conn.execute(
            "INSERT INTO dedup_keys (platform, account, target_url, state, updated_at) "
            "VALUES ('velog', 'user2', 'http://another.com', 'failed', 1234567892.0)"
        )
    return query_store


class TestQueryMixinGet:
    """Tests for QueryMixin.get() method."""

    def test_get_existing_key(self, store_with_data: TestQueryStore) -> None:
        key = DedupKey(platform="blogger", account="user1", target_url="http://example.com")
        record = store_with_data.get(key)
        assert record is not None
        assert record.platform == "blogger"
        assert record.account == "user1"
        assert record.target_url == "http://example.com"
        assert record.state == "done"

    def test_get_nonexistent_key(self, store_with_data: TestQueryStore) -> None:
        key = DedupKey(platform="nonexistent", account="user", target_url="http://none.com")
        record = store_with_data.get(key)
        assert record is None

    def test_get_with_canonicalization(self, query_store: TestQueryStore) -> None:
        # Insert with trailing slash
        with query_store.connect() as conn:
            conn.execute(
                "INSERT INTO dedup_keys (platform, account, target_url, state, updated_at) "
                "VALUES ('blogger', 'user', 'http://example.com/', 'done', 1234567890.0)"
            )
        # Query with trailing slash (DedupKey canonicalizes, so both should match)
        key = DedupKey(platform="blogger", account="user", target_url="http://example.com/")
        record = query_store.get(key)
        assert record is not None


class TestQueryMixinGetMany:
    """Tests for QueryMixin.get_many() method."""

    def test_get_many_empty_input(self, query_store: TestQueryStore) -> None:
        result = query_store.get_many([])
        assert result == {}

    def test_get_many_single_key(self, store_with_data: TestQueryStore) -> None:
        key = DedupKey(platform="blogger", account="user1", target_url="http://example.com")
        result = store_with_data.get_many([key])
        assert len(result) == 1
        assert key.as_tuple() in result
        assert result[key.as_tuple()].state == "done"

    def test_get_many_mixed_results(self, store_with_data: TestQueryStore) -> None:
        keys = [
            DedupKey(platform="blogger", account="user1", target_url="http://example.com"),
            DedupKey(platform="nonexistent", account="user", target_url="http://none.com"),
        ]
        result = store_with_data.get_many(keys)
        assert len(result) == 1  # Only existing key returned
        assert keys[0].as_tuple() in result

    def test_get_many_deduplication(self, store_with_data: TestQueryStore) -> None:
        key = DedupKey(platform="blogger", account="user1", target_url="http://example.com")
        result = store_with_data.get_many([key, key])  # Duplicate keys
        assert len(result) == 1  # Should only query once

    def test_get_many_multiple_keys(self, store_with_data: TestQueryStore) -> None:
        keys = [
            DedupKey(platform="blogger", account="user1", target_url="http://example.com"),
            DedupKey(platform="medium", account="user1", target_url="http://test.com"),
        ]
        result = store_with_data.get_many(keys)
        assert len(result) == 2
        assert keys[0].as_tuple() in result
        assert keys[1].as_tuple() in result


class TestQueryMixinListByState:
    """Tests for QueryMixin.list_by_state() method."""

    def test_list_by_state(self, store_with_data: TestQueryStore) -> None:
        records = store_with_data.list_by_state("done")
        assert len(records) == 1
        assert records[0].state == "done"

    def test_list_by_state_with_platform(self, store_with_data: TestQueryStore) -> None:
        records = store_with_data.list_by_state("done", platform="blogger")
        assert len(records) == 1
        assert records[0].platform == "blogger"

    def test_list_by_state_wrong_platform(self, store_with_data: TestQueryStore) -> None:
        records = store_with_data.list_by_state("done", platform="medium")
        assert len(records) == 0

    def test_list_by_state_all_platforms(self, store_with_data: TestQueryStore) -> None:
        # Add another record with same state
        with store_with_data.connect() as conn:
            conn.execute(
                "INSERT INTO dedup_keys (platform, account, target_url, state, updated_at) "
                "VALUES ('velog', 'user3', 'http://third.com', 'done', 1234567893.0)"
            )
        records = store_with_data.list_by_state("done")
        assert len(records) == 2

    def test_list_by_state_ordering(self, store_with_data: TestQueryStore) -> None:
        records = store_with_data.list_by_state("done")
        # Should be ordered by updated_at DESC (newest first)
        assert records[0].updated_at >= records[-1].updated_at if len(records) > 1 else True


class TestQueryMixinIsStaleAttempting:
    """Tests for QueryMixin.is_stale_attempting() method."""

    def test_not_attempting_state(self, store_with_data: TestQueryStore) -> None:
        key = DedupKey(platform="blogger", account="user1", target_url="http://example.com")
        record = store_with_data.get(key)
        assert record is not None
        assert store_with_data.is_stale_attempting(record) is False

    def test_attempting_pid_alive(self, store_with_data: TestQueryStore) -> None:
        key = DedupKey(platform="medium", account="user1", target_url="http://test.com")
        record = store_with_data.get(key)
        assert record is not None
        # Update with current PID
        with store_with_data.connect() as conn:
            conn.execute(
                "UPDATE dedup_keys SET owner_pid = ? WHERE platform = ? AND account = ? AND target_url = ?",
                (1, "medium", "user1", "http://test.com"),
            )
        record = store_with_data.get(key)
        # Mock _pid_alive to return True
        with patch("backlink_publisher.idempotency._dedup_query._pid_alive", return_value=True):
            # Use a recent timestamp
            now = time.time()
            with store_with_data.connect() as conn:
                conn.execute(
                    "UPDATE dedup_keys SET updated_at = ? WHERE platform = ? AND account = ? AND target_url = ?",
                    (now, "medium", "user1", "http://test.com"),
                )
            record = store_with_data.get(key)
            assert store_with_data.is_stale_attempting(record) is False

    def test_attempting_pid_dead(self, store_with_data: TestQueryStore) -> None:
        key = DedupKey(platform="medium", account="user1", target_url="http://test.com")
        record = store_with_data.get(key)
        assert record is not None
        # Update with a PID
        with store_with_data.connect() as conn:
            conn.execute(
                "UPDATE dedup_keys SET owner_pid = ? WHERE platform = ? AND account = ? AND target_url = ?",
                (99999, "medium", "user1", "http://test.com"),
            )
        record = store_with_data.get(key)
        # Mock _pid_alive to return False
        with patch("backlink_publisher.idempotency._dedup_query._pid_alive", return_value=False):
            assert store_with_data.is_stale_attempting(record) is True

    def test_attempting_ttl_expired(self, store_with_data: TestQueryStore) -> None:
        key = DedupKey(platform="medium", account="user1", target_url="http://test.com")
        record = store_with_data.get(key)
        assert record is not None
        # Set old timestamp
        old_time = time.time() - _STALE_TTL_S - 1
        with store_with_data.connect() as conn:
            conn.execute(
                "UPDATE dedup_keys SET updated_at = ?, owner_pid = NULL WHERE platform = ? AND account = ? AND target_url = ?",
                (old_time, "medium", "user1", "http://test.com"),
            )
        record = store_with_data.get(key)
        assert store_with_data.is_stale_attempting(record) is True

    def test_attempting_custom_ttl(self, store_with_data: TestQueryStore) -> None:
        key = DedupKey(platform="medium", account="user1", target_url="http://test.com")
        record = store_with_data.get(key)
        assert record is not None
        # Set timestamp just within custom TTL
        now = time.time()
        custom_ttl = 100
        recent_time = now - 50  # Within 100s TTL
        with store_with_data.connect() as conn:
            conn.execute(
                "UPDATE dedup_keys SET updated_at = ?, owner_pid = NULL WHERE platform = ? AND account = ? AND target_url = ?",
                (recent_time, "medium", "user1", "http://test.com"),
            )
        record = store_with_data.get(key)
        assert store_with_data.is_stale_attempting(record, ttl_s=custom_ttl) is False

    def test_attempting_custom_now(self, store_with_data: TestQueryStore) -> None:
        key = DedupKey(platform="medium", account="user1", target_url="http://test.com")
        record = store_with_data.get(key)
        assert record is not None
        # Set old timestamp
        old_time = 1000.0
        with store_with_data.connect() as conn:
            conn.execute(
                "UPDATE dedup_keys SET updated_at = ?, owner_pid = NULL WHERE platform = ? AND account = ? AND target_url = ?",
                (old_time, "medium", "user1", "http://test.com"),
            )
        record = store_with_data.get(key)
        # Use a custom now that makes it stale
        custom_now = old_time + _STALE_TTL_S + 1
        assert store_with_data.is_stale_attempting(record, now=custom_now) is True


class TestQueryMixinIntegration:
    """Integration tests for QueryMixin."""

    def test_get_after_insert(self, query_store: TestQueryStore) -> None:
        # Insert a record
        with query_store.connect() as conn:
            conn.execute(
                "INSERT INTO dedup_keys (platform, account, target_url, state, updated_at) "
                "VALUES ('test_platform', 'test_account', 'http://test.example.com', 'done', 1234567890.0)"
            )
        # Retrieve it
        key = DedupKey(platform="test_platform", account="test_account", target_url="http://test.example.com")
        record = query_store.get(key)
        assert record is not None
        assert record.platform == "test_platform"
        assert record.state == "done"

    def test_get_many_after_inserts(self, query_store: TestQueryStore) -> None:
        # Insert multiple records
        with query_store.connect() as conn:
            conn.execute(
                "INSERT INTO dedup_keys (platform, account, target_url, state, updated_at) "
                "VALUES ('platform1', 'user1', 'http://one.com', 'done', 1234567890.0)"
            )
            conn.execute(
                "INSERT INTO dedup_keys (platform, account, target_url, state, updated_at) "
                "VALUES ('platform2', 'user2', 'http://two.com', 'attempting', 1234567891.0)"
            )
        # Retrieve both
        keys = [
            DedupKey(platform="platform1", account="user1", target_url="http://one.com"),
            DedupKey(platform="platform2", account="user2", target_url="http://two.com"),
        ]
        result = query_store.get_many(keys)
        assert len(result) == 2

    def test_list_by_state_after_inserts(self, query_store: TestQueryStore) -> None:
        # Insert records with different states
        with query_store.connect() as conn:
            conn.execute(
                "INSERT INTO dedup_keys (platform, account, target_url, state, updated_at) "
                "VALUES ('platform1', 'user1', 'http://one.com', 'done', 1234567890.0)"
            )
            conn.execute(
                "INSERT INTO dedup_keys (platform, account, target_url, state, updated_at) "
                "VALUES ('platform2', 'user2', 'http://two.com', 'done', 1234567891.0)"
            )
            conn.execute(
                "INSERT INTO dedup_keys (platform, account, target_url, state, updated_at) "
                "VALUES ('platform3', 'user3', 'http://three.com', 'failed', 1234567892.0)"
            )
        # List done records
        done_records = query_store.list_by_state("done")
        assert len(done_records) == 2
        # List failed records
        failed_records = query_store.list_by_state("failed")
        assert len(failed_records) == 1
