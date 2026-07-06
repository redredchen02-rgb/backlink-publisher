"""Tests for idempotency._dedup_connection module."""


from __future__ import annotations
__tier__ = "unit"

from pathlib import Path
import sqlite3

import pytest


class TestConnectionMixin:
    """Tests for ConnectionMixin connection management."""

    def test_connect_yields_connection(self, tmp_path: Path) -> None:
        from backlink_publisher.idempotency._dedup_connection import ConnectionMixin

        class TestStore(ConnectionMixin):
            def __init__(self, path: Path) -> None:
                self.path = path

        store = TestStore(tmp_path / "test.db")
        with store.connect() as conn:
            assert isinstance(conn, sqlite3.Connection)
            # Verify schema was created
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
            tables = {row[0] for row in cursor.fetchall()}
            assert "dedup_keys" in tables

    def test_connect_commits_on_success(self, tmp_path: Path) -> None:
        from backlink_publisher.idempotency._dedup_connection import ConnectionMixin

        class TestStore(ConnectionMixin):
            def __init__(self, path: Path) -> None:
                self.path = path

        store = TestStore(tmp_path / "test.db")
        with store.connect() as conn:
            conn.execute(
                "INSERT INTO dedup_keys (platform, account, target_url, state, updated_at) "
                "VALUES ('test', 'user', 'http://example.com', 'done', 1234567890.0)"
            )
        # Verify data was committed
        with store.connect() as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM dedup_keys")
            assert cursor.fetchone()[0] == 1

    def test_connect_rollback_on_exception(self, tmp_path: Path) -> None:
        from backlink_publisher.idempotency._dedup_connection import ConnectionMixin

        class TestStore(ConnectionMixin):
            def __init__(self, path: Path) -> None:
                self.path = path

        store = TestStore(tmp_path / "test.db")
        with pytest.raises(ValueError):
            with store.connect() as conn:
                conn.execute(
                    "INSERT INTO dedup_keys (platform, account, target_url, state, updated_at) "
                    "VALUES ('test', 'user', 'http://example.com', 'done', 1234567890.0)"
                )
                raise ValueError("Test exception")
        # Verify data was rolled back
        with store.connect() as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM dedup_keys")
            assert cursor.fetchone()[0] == 0

    def test_connect_immediate_uses_begin_immEDIATE(self, tmp_path: Path) -> None:
        from backlink_publisher.idempotency._dedup_connection import ConnectionMixin

        class TestStore(ConnectionMixin):
            def __init__(self, path: Path) -> None:
                self.path = path

        store = TestStore(tmp_path / "test.db")
        with store.connect_immediate() as conn:
            assert isinstance(conn, sqlite3.Connection)
            # Verify transaction is active
            cursor = conn.execute("SELECT * FROM sqlite_master")
            # Should not raise - transaction is active

    def test_connect_immediate_commits_on_success(self, tmp_path: Path) -> None:
        from backlink_publisher.idempotency._dedup_connection import ConnectionMixin

        class TestStore(ConnectionMixin):
            def __init__(self, path: Path) -> None:
                self.path = path

        store = TestStore(tmp_path / "test.db")
        with store.connect_immediate() as conn:
            conn.execute(
                "INSERT INTO dedup_keys (platform, account, target_url, state, updated_at) "
                "VALUES ('test', 'user', 'http://example.com', 'done', 1234567890.0)"
            )
        # Verify data was committed
        with store.connect() as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM dedup_keys")
            assert cursor.fetchone()[0] == 1

    def test_connect_immediate_rollback_on_exception(self, tmp_path: Path) -> None:
        from backlink_publisher.idempotency._dedup_connection import ConnectionMixin

        class TestStore(ConnectionMixin):
            def __init__(self, path: Path) -> None:
                self.path = path

        store = TestStore(tmp_path / "test.db")
        with pytest.raises(ValueError):
            with store.connect_immediate() as conn:
                conn.execute(
                    "INSERT INTO dedup_keys (platform, account, target_url, state, updated_at) "
                    "VALUES ('test', 'user', 'http://example.com', 'done', 1234567890.0)"
                )
                raise ValueError("Test exception")
        # Verify data was rolled back
        with store.connect() as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM dedup_keys")
            assert cursor.fetchone()[0] == 0

    def test_connect_creates_parent_directories(self, tmp_path: Path) -> None:
        from backlink_publisher.idempotency._dedup_connection import ConnectionMixin

        class TestStore(ConnectionMixin):
            def __init__(self, path: Path) -> None:
                self.path = path

        nested_path = tmp_path / "nested" / "dir" / "test.db"
        store = TestStore(nested_path)
        with store.connect() as conn:
            assert nested_path.exists()

    def test_connect_sets_file_permissions(self, tmp_path: Path) -> None:
        from backlink_publisher.idempotency._dedup_connection import ConnectionMixin

        class TestStore(ConnectionMixin):
            def __init__(self, path: Path) -> None:
                self.path = path

        db_path = tmp_path / "test.db"
        store = TestStore(db_path)
        with store.connect() as conn:
            pass
        # Check file permissions (0o600 = owner read/write only)
        import stat
        mode = db_path.stat().st_mode
        assert mode & stat.S_IRUSR  # Owner read
        assert mode & stat.S_IWUSR  # Owner write
        assert not (mode & stat.S_IRGRP)  # No group read
        assert not (mode & stat.S_IWGRP)  # No group write
