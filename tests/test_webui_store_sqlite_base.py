"""Tests for webui_store.sqlite_base — Unit 1.

Verifies WebUIDatabase connection lifecycle and SqliteStore protocol
compliance: WAL pragma, 0o600 perms, sidecar tighten, lock safety.

Plan: docs/plans/2026-06-03-008-refactor-webui-store-sqlite-unification-plan.md
"""

from __future__ import annotations

import os
import sqlite3
import threading
import time
from pathlib import Path

import pytest

from webui_store.sqlite_base import SqliteStore, WebUIDatabase, _DB_FILENAME
from webui_store.base import Store


# ── Minimal concrete subclass used throughout these tests ─────────────────────

class _BlobStore(SqliteStore):
    """Single-row blob store (id=1, data TEXT) for testing SqliteStore base."""

    def __init__(self, db: WebUIDatabase) -> None:
        super().__init__(db)
        self._init_table()

    def _init_table(self) -> None:
        with self._db.connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS _test_blob "
                "(id INTEGER PRIMARY KEY, data TEXT NOT NULL DEFAULT '')"
            )

    def load(self) -> str:
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT data FROM _test_blob WHERE id = 1"
            ).fetchone()
        return row[0] if row else ""

    def save(self, value: str) -> None:
        with self._lock:
            with self._db.connect() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO _test_blob (id, data) VALUES (1, ?)",
                    (value,),
                )


# ── WebUIDatabase — connection and file hygiene ────────────────────────────────

class TestWebUIDatabase:
    def test_creates_db_file_on_first_connect(self, tmp_path):
        db_path = tmp_path / "webui.db"
        assert not db_path.exists()
        db = WebUIDatabase(db_path)
        with db.connect() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS t (x TEXT)")
        assert db_path.exists()

    def test_wal_mode_enabled(self, tmp_path):
        db = WebUIDatabase(tmp_path / "webui.db")
        with db.connect() as conn:
            mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode == "wal"

    def test_db_file_created_0o600(self, tmp_path):
        db = WebUIDatabase(tmp_path / "webui.db")
        with db.connect() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS t (x TEXT)")
        stat = (tmp_path / "webui.db").stat()
        assert oct(stat.st_mode & 0o777) == oct(0o600)

    def test_wal_sidecars_tightened_after_write(self, tmp_path):
        db = WebUIDatabase(tmp_path / "webui.db")
        # Force a real write so SQLite creates WAL/SHM sidecars.
        with db.connect() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS t (x TEXT)")
            conn.execute("INSERT INTO t VALUES ('a')")
        # Second connect triggers _tighten_wal_sidecars.
        with db.connect():
            pass
        for suffix in ("-wal", "-shm"):
            side = tmp_path / ("webui.db" + suffix)
            if side.exists():
                mode = side.stat().st_mode & 0o777
                assert mode == 0o600, f"{side.name} perm {oct(mode)} != 0o600"

    def test_missing_db_created_on_first_access(self, tmp_path):
        deep = tmp_path / "sub" / "nested"
        db = WebUIDatabase(deep / "webui.db")
        with db.connect() as conn:
            conn.execute("SELECT 1")
        assert (deep / "webui.db").exists()

    def test_db_filename_constant_is_webui_db(self):
        assert _DB_FILENAME == "webui.db"
        assert WebUIDatabase._DB_FILENAME == "webui.db"

    def test_commit_on_success(self, tmp_path):
        db = WebUIDatabase(tmp_path / "webui.db")
        with db.connect() as conn:
            conn.execute("CREATE TABLE t (x TEXT)")
            conn.execute("INSERT INTO t VALUES ('hello')")
        # Open a fresh connection to verify commit persisted.
        db2 = WebUIDatabase(tmp_path / "webui.db")
        with db2.connect() as conn:
            row = conn.execute("SELECT x FROM t").fetchone()
        assert row is not None and row[0] == "hello"

    def test_rollback_on_exception(self, tmp_path):
        db = WebUIDatabase(tmp_path / "webui.db")
        with db.connect() as conn:
            conn.execute("CREATE TABLE t (x TEXT)")
        with pytest.raises(ValueError):
            with db.connect() as conn:
                conn.execute("INSERT INTO t VALUES ('boom')")
                raise ValueError("intentional")
        db2 = WebUIDatabase(tmp_path / "webui.db")
        with db2.connect() as conn:
            rows = conn.execute("SELECT * FROM t").fetchall()
        assert rows == []


# ── SqliteStore — protocol and lock safety ────────────────────────────────────

class TestSqliteStoreProtocol:
    def test_isinstance_store_protocol(self, tmp_path):
        db = WebUIDatabase(tmp_path / "webui.db")
        store = _BlobStore(db)
        assert isinstance(store, Store)

    def test_load_returns_default_when_absent(self, tmp_path):
        db = WebUIDatabase(tmp_path / "webui.db")
        store = _BlobStore(db)
        assert store.load() == ""

    def test_save_and_load_roundtrip(self, tmp_path):
        db = WebUIDatabase(tmp_path / "webui.db")
        store = _BlobStore(db)
        store.save("hello")
        assert store.load() == "hello"

    def test_update_fn_applied(self, tmp_path):
        db = WebUIDatabase(tmp_path / "webui.db")
        store = _BlobStore(db)
        store.save("foo")
        result = store.update(lambda v: v + "_bar")
        assert result == "foo_bar"
        assert store.load() == "foo_bar"

    def test_save_callable_directly_no_deadlock(self, tmp_path):
        """save() acquires the RLock; calling it outside update() must not hang."""
        db = WebUIDatabase(tmp_path / "webui.db")
        store = _BlobStore(db)
        # If save() used a plain Lock and update() already held it, this would
        # deadlock. RLock allows re-entry from the same thread.
        store.update(lambda v: "via_update")
        store.save("direct_save")
        assert store.load() == "direct_save"

    def test_update_is_atomic_under_concurrent_writers(self, tmp_path):
        """Concurrent threads each increment a counter; final value must equal
        the number of threads (no lost update)."""
        db = WebUIDatabase(tmp_path / "webui.db")
        store = _BlobStore(db)
        store.save("0")

        errors: list[Exception] = []
        n_threads = 10

        def increment():
            try:
                store.update(lambda v: str(int(v) + 1))
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=increment) for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert store.load() == str(n_threads)


# ── Integration: path resolves from env var (lazy init) ───────────────────────

class TestPathCompat:
    def test_path_property_returns_db_path(self, tmp_path):
        db = WebUIDatabase(tmp_path / "webui.db")
        store = _BlobStore(db)
        assert store.path == tmp_path / "webui.db"

    def test_path_setter_redirects_store(self, tmp_path):
        """Backward compat: monkeypatch.setattr(store, 'path', new_path) redirects IO."""
        db = WebUIDatabase(tmp_path / "webui.db")
        store = _BlobStore(db)
        store.save("original")

        new_path = tmp_path / "redirected.db"
        store.path = new_path
        assert store.path == new_path
        # New db starts empty
        assert store.load() == ""
        store.save("redirected")
        assert store.load() == "redirected"
        # Original db is untouched
        db2 = WebUIDatabase(tmp_path / "webui.db")
        orig_store = _BlobStore(db2)
        assert orig_store.load() == "original"


class TestLazyPathResolution:
    def test_path_resolves_from_config_dir_env(self, tmp_path, monkeypatch):
        """Store created with a path derived from BACKLINK_PUBLISHER_CONFIG_DIR
        at factory call time — not at import time."""
        new_dir = tmp_path / "cfg"
        new_dir.mkdir()
        monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(new_dir))

        from backlink_publisher.config.loader import _config_dir
        db = WebUIDatabase(_config_dir() / "webui.db")
        store = _BlobStore(db)
        store.save("lazy_value")

        assert (new_dir / "webui.db").exists()
        assert store.load() == "lazy_value"
