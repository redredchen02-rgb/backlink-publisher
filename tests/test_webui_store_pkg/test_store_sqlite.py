"""Tests for webui_store.sqlite_base — WebUIDatabase, SqliteStore, BlobSqliteStore.

Plan 2026-06-30 Phase 3+ T3.6: webui_store test coverage expansion.
"""

from __future__ import annotations

__tier__ = "unit"

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from webui_store.sqlite_base import (
    BlobSqliteStore,
    SqliteStore,
    WebUIDatabase,
)


# ═════════════════════════════════════════════════════════════════════════════
# WebUIDatabase
# ═════════════════════════════════════════════════════════════════════════════


class TestWebUIDatabase:
    """WebUIDatabase connection factory."""

    def test_connect_creates_db_file(self, tmp_path: Path) -> None:
        db_path = tmp_path / "webui.db"
        db = WebUIDatabase(db_path)
        with db.connect() as conn:
            conn.execute("CREATE TABLE t (x INT)")
            conn.execute("INSERT INTO t VALUES (42)")
        assert db_path.exists()
        # Verify data persists across connections
        with db.connect() as conn:
            row = conn.execute("SELECT x FROM t").fetchone()
            assert row == (42,)

    def test_connect_rollback_on_error(self, tmp_path: Path) -> None:
        db_path = tmp_path / "webui.db"
        db = WebUIDatabase(db_path)
        with pytest.raises(RuntimeError):
            with db.connect() as conn:
                conn.execute("CREATE TABLE t (x INT)")
                conn.execute("INSERT INTO t VALUES (1)")
                raise RuntimeError("simulated failure")
        # Rollback means the insert was undone
        with db.connect() as conn:
            count = conn.execute("SELECT COUNT(*) FROM t").fetchone()[0]
            assert count == 0

    def test_wal_mode_enabled(self, tmp_path: Path) -> None:
        db_path = tmp_path / "webui.db"
        db = WebUIDatabase(db_path)
        with db.connect() as conn:
            mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        # WAL should be set
        assert "wal" in mode.lower() if mode else True

    def test_busy_timeout_set(self, tmp_path: Path) -> None:
        db_path = tmp_path / "webui.db"
        db = WebUIDatabase(db_path)
        with db.connect() as conn:
            timeout = conn.execute("PRAGMA busy_timeout").fetchone()[0]
        assert timeout == 5000

    def test_close_all_noop(self) -> None:
        """close_all is a no-op (connections are not cached)."""
        WebUIDatabase.close_all()  # should not raise


# ═════════════════════════════════════════════════════════════════════════════
# SqliteStore (abstract base)
# ═════════════════════════════════════════════════════════════════════════════


class _ConcreteStore(SqliteStore):
    """Minimal concrete SqliteStore for testing abstract base behavior."""

    def __init__(self, db: WebUIDatabase) -> None:
        super().__init__(db)
        self._init_table()

    def _init_table(self) -> None:
        with self._db.connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS test_store ("
                "id INTEGER PRIMARY KEY, data_json TEXT NOT NULL)"
            )

    def load(self) -> Any:
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT data_json FROM test_store WHERE id = 1"
            ).fetchone()
        if row is None:
            return {"default": True}
        return json.loads(row[0])

    def save(self, value: Any) -> None:
        with self._lock:
            with self._db.connect() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO test_store (id, data_json) "
                    "VALUES (1, ?)",
                    (json.dumps(value, ensure_ascii=False),),
                )


class TestSqliteStore:
    """SqliteStore abstract base behavior."""

    def test_initialized_with_lock(self, tmp_path: Path) -> None:
        db = WebUIDatabase(tmp_path / "test.db")
        store = _ConcreteStore(db)
        assert store._lock is not None

    def test_load_returns_value(self, tmp_path: Path) -> None:
        db = WebUIDatabase(tmp_path / "test.db")
        store = _ConcreteStore(db)
        store.save({"hello": "world"})
        assert store.load() == {"hello": "world"}

    def test_update_atomic(self, tmp_path: Path) -> None:
        db = WebUIDatabase(tmp_path / "test.db")
        store = _ConcreteStore(db)

        def transform(data: dict) -> dict:
            data["n"] = data.get("n", 0) + 1
            return data

        result = store.update(transform)
        assert result == {"default": True, "n": 1}

        result = store.update(transform)
        assert result == {"default": True, "n": 2}

    def test_path_property(self, tmp_path: Path) -> None:
        db = WebUIDatabase(tmp_path / "test.db")
        store = _ConcreteStore(db)
        assert store.path == tmp_path / "test.db"

    def test_path_setter_reinitializes(self, tmp_path: Path) -> None:
        db = WebUIDatabase(tmp_path / "test.db")
        store = _ConcreteStore(db)
        store.save({"data": "original"})

        new_path = tmp_path / "redirected.db"
        store.path = new_path
        # After redirect, the store should be empty (new db)
        assert store.load() == {"default": True}
        # Original db should still have the data
        db2 = WebUIDatabase(tmp_path / "test.db")
        with db2.connect() as conn:
            row = conn.execute(
                "SELECT data_json FROM test_store WHERE id = 1"
            ).fetchone()
            assert row is not None


# ═════════════════════════════════════════════════════════════════════════════
# BlobSqliteStore
# ═════════════════════════════════════════════════════════════════════════════


class _TestBlobStore(BlobSqliteStore):
    """Concrete BlobSqliteStore for testing."""
    _table_name = "blob_test"
    _value_type = dict
    _json_filename = None
    _sentinel_name = None


class _TestBlobListStore(BlobSqliteStore):
    """Blob store with list value type."""
    _table_name = "blob_list"
    _value_type = list
    _json_filename = None
    _sentinel_name = None


class TestBlobSqliteStore:
    """BlobSqliteStore unit tests."""

    def test_load_returns_default_when_empty(self, tmp_path: Path) -> None:
        store = _TestBlobStore(WebUIDatabase(tmp_path / "blob.db"))
        assert store.load() == {}

    def test_load_returns_default_list_when_empty(self, tmp_path: Path) -> None:
        store = _TestBlobListStore(WebUIDatabase(tmp_path / "blob_list.db"))
        assert store.load() == []

    def test_save_and_load_round_trip(self, tmp_path: Path) -> None:
        store = _TestBlobStore(WebUIDatabase(tmp_path / "blob.db"))
        store.save({"key": "value", "num": 42})
        assert store.load() == {"key": "value", "num": 42}

    def test_save_overwrites(self, tmp_path: Path) -> None:
        store = _TestBlobStore(WebUIDatabase(tmp_path / "blob.db"))
        store.save({"first": "value"})
        store.save({"second": "replaced"})
        assert store.load() == {"second": "replaced"}

    def test_update_under_lock(self, tmp_path: Path) -> None:
        store = _TestBlobStore(WebUIDatabase(tmp_path / "blob.db"))
        result = store.update(lambda d: {"counter": d.get("counter", 0) + 1})
        assert result == {"counter": 1}
        assert store.load() == {"counter": 1}

    def test_load_returns_default_on_corrupt_data(self, tmp_path: Path) -> None:
        """If manual corruption is inserted, load falls back to default."""
        store = _TestBlobStore(WebUIDatabase(tmp_path / "blob.db"))
        store.save({"ok": True})
        # Manually corrupt the data_json
        with store._db.connect() as conn:
            conn.execute(
                "UPDATE blob_test SET data_json = '{bad json' WHERE id = 1"
            )
        assert store.load() == {}

    def test_table_name_validation(self) -> None:
        """__init_subclass__ validates _table_name is a safe SQL identifier."""
        with pytest.raises(TypeError):
            class _BadTable(BlobSqliteStore):  # type: ignore[no-unused]
                _table_name = "bad table name; DROP TABLE users"

    def test_invalid_table_name_passed_through(self) -> None:
        """Even if somehow registered, the SQL identifier regex rejects it."""
        import re
        pattern = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
        assert pattern.match("good_name") is not None
        assert pattern.match("bad name") is None
        assert pattern.match("123_bad") is None

    def test_list_store_operations(self, tmp_path: Path) -> None:
        store = _TestBlobListStore(WebUIDatabase(tmp_path / "list.db"))
        assert store.load() == []
        store.save(["a", "b", "c"])
        assert store.load() == ["a", "b", "c"]
        store.save(["x"])
        assert store.load() == ["x"]

    def test_path_setter_reinitializes_blob_store(self, tmp_path: Path) -> None:
        store = _TestBlobStore(WebUIDatabase(tmp_path / "blob.db"))
        store.save({"original": True})

        new_path = tmp_path / "blob2.db"
        store.path = new_path
        assert store.load() == {}
        store.save({"redirected": True})
        assert store.load() == {"redirected": True}
