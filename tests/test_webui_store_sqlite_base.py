"""Tests for webui_store.sqlite_base — Unit 1.

Verifies WebUIDatabase connection lifecycle and SqliteStore protocol
compliance: WAL pragma, 0o600 perms, sidecar tighten, lock safety.

Plan: docs/plans/2026-06-03-008-refactor-webui-store-sqlite-unification-plan.md
"""


from __future__ import annotations
__tier__ = "integration"

import json
import os
from pathlib import Path
import sqlite3
import threading
import time

import pytest

from _mode_assertions import assert_file_mode
from webui_store.base import Store
from webui_store.sqlite_base import (
    _DB_FILENAME,
    _retry_sqlite,
    BaseSqliteStore,
    BlobSqliteStore,
    SqliteStore,
    WebUIDatabase,
)

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
        assert_file_mode(tmp_path / "webui.db", 0o600)

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
                assert_file_mode(side, 0o600)

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


# ── BaseSqliteStore template (Unit 2) ─────────────────────────────────────────

class _FakeRowStore(BaseSqliteStore):
    """Minimal row-table store exercising BaseSqliteStore's template + helpers."""

    _json_filename = "fake-rows.json"
    _sentinel_name = ".fake-rows-migrated-v1"
    _value_type = list

    def _create_table_sql(self) -> str:
        return (
            "CREATE TABLE IF NOT EXISTS fake_rows "
            "(id TEXT PRIMARY KEY, data_json TEXT NOT NULL)"
        )

    def _indices_sql(self) -> list[str]:
        return ["CREATE INDEX IF NOT EXISTS fake_rows_id ON fake_rows(id)"]

    def load(self) -> list[dict]:
        return self._load_rows("SELECT data_json FROM fake_rows ORDER BY rowid")

    def save(self, value) -> None:
        rows = [
            (i.get("id"), json.dumps(i, ensure_ascii=False))
            for i in value
            if isinstance(i, dict)
        ]
        self._replace_all_rows("fake_rows", ("id", "data_json"), rows)

    def get_one(self, item_id: str):
        return self._get_one_json(
            "SELECT data_json FROM fake_rows WHERE id = ?", (item_id,)
        )


class _FakeBlobStore(BlobSqliteStore):
    _table_name = "fake_blob"
    _value_type = dict
    _json_filename = "fake-blob.json"
    _sentinel_name = ".fake-blob-migrated-v1"


class _FakeListBlobStore(BlobSqliteStore):
    _table_name = "fake_list_blob"
    _value_type = list
    # no migration (no JSON predecessor) — _json_filename left None


class TestBaseSqliteStoreTemplate:
    def test_is_abstract_cannot_instantiate(self, tmp_path):
        with pytest.raises(TypeError):
            BaseSqliteStore(WebUIDatabase(tmp_path / "webui.db"))  # type: ignore[abstract]

    def test_init_table_creates_table_and_index(self, tmp_path):
        store = _FakeRowStore(WebUIDatabase(tmp_path / "webui.db"))
        with store._db.connect() as conn:
            tbl = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='fake_rows'"
            ).fetchone()
            idx = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name='fake_rows_id'"
            ).fetchone()
        assert tbl is not None
        assert idx is not None

    def test_accepts_path_not_just_webuidatabase(self, tmp_path):
        # Backward-compat: constructor wraps a bare Path.
        store = _FakeRowStore(tmp_path / "webui.db")
        assert store.path == tmp_path / "webui.db"
        store.save([{"id": "a"}])
        assert store.load() == [{"id": "a"}]

    def test_load_rows_skips_malformed_and_non_dict(self, tmp_path):
        store = _FakeRowStore(WebUIDatabase(tmp_path / "webui.db"))
        with store._db.connect() as conn:
            conn.executemany(
                "INSERT INTO fake_rows (id, data_json) VALUES (?, ?)",
                [("a", '{"id": "a"}'), ("b", "not-json{"), ("c", "[1,2]")],
            )
        # 'a' is a valid dict; 'b' malformed (skipped); 'c' is a list (skipped).
        assert store.load() == [{"id": "a"}]

    def test_get_one_json_hits_and_misses(self, tmp_path):
        store = _FakeRowStore(WebUIDatabase(tmp_path / "webui.db"))
        store.save([{"id": "a", "v": 1}])
        assert store.get_one("a") == {"id": "a", "v": 1}
        assert store.get_one("missing") is None

    def test_migrate_happy_path(self, tmp_path):
        json_path = tmp_path / "fake-rows.json"
        json_path.write_text('[{"id": "x"}]', encoding="utf-8")
        store = _FakeRowStore(WebUIDatabase(tmp_path / "webui.db"))
        store.migrate_from_json(tmp_path)
        assert store.load() == [{"id": "x"}]
        migrated = tmp_path / "fake-rows.json.migrated"
        assert migrated.exists()
        assert_file_mode(migrated, 0o600)
        assert (tmp_path / ".fake-rows-migrated-v1").exists()

    def test_migrate_corrupt_skips_no_sentinel(self, tmp_path):
        (tmp_path / "fake-rows.json").write_bytes(b"\xff\xfe not json")
        store = _FakeRowStore(WebUIDatabase(tmp_path / "webui.db"))
        store.migrate_from_json(tmp_path)
        assert not (tmp_path / ".fake-rows-migrated-v1").exists()
        assert store.load() == []

    def test_migrate_crash_recovery_writes_sentinel(self, tmp_path):
        (tmp_path / "fake-rows.json.migrated").write_text("[]", encoding="utf-8")
        store = _FakeRowStore(WebUIDatabase(tmp_path / "webui.db"))
        store.migrate_from_json(tmp_path)
        assert (tmp_path / ".fake-rows-migrated-v1").exists()

    def test_migrate_coerces_wrong_type_to_default(self, tmp_path):
        # JSON top-level is a dict but _value_type is list → coerce to [].
        (tmp_path / "fake-rows.json").write_text('{"not": "a list"}', encoding="utf-8")
        store = _FakeRowStore(WebUIDatabase(tmp_path / "webui.db"))
        store.migrate_from_json(tmp_path)
        assert store.load() == []
        assert (tmp_path / ".fake-rows-migrated-v1").exists()

    def test_migrate_noop_without_json_filename(self, tmp_path):
        # _FakeListBlobStore has no _json_filename → migrate is a no-op.
        store = _FakeListBlobStore(WebUIDatabase(tmp_path / "webui.db"))
        store.migrate_from_json(tmp_path)  # must not raise
        assert store.load() == []

    def test_migrate_save_failure_is_soft_no_sentinel(self, tmp_path, monkeypatch):
        # Consistency with read/rename error handling: a save() failure during
        # migration must not crash startup; sentinel stays unwritten so the next
        # boot retries, and the source JSON is not renamed.
        (tmp_path / "fake-rows.json").write_text('[{"id": "x"}]', encoding="utf-8")
        store = _FakeRowStore(WebUIDatabase(tmp_path / "webui.db"))

        def _boom(_value):
            raise OSError("disk full")

        monkeypatch.setattr(store, "save", _boom)
        store.migrate_from_json(tmp_path)  # must not raise

        assert not (tmp_path / ".fake-rows-migrated-v1").exists()
        assert (tmp_path / "fake-rows.json").exists()
        assert not (tmp_path / "fake-rows.json.migrated").exists()

    def test_replace_all_rows_roundtrip_and_clear(self, tmp_path):
        store = _FakeRowStore(WebUIDatabase(tmp_path / "webui.db"))
        store.save([{"id": "a"}, {"id": "b"}])
        assert {r["id"] for r in store.load()} == {"a", "b"}
        # whole-table rewrite: saving fewer rows deletes the rest
        store.save([{"id": "c"}])
        assert [r["id"] for r in store.load()] == ["c"]
        # empty save clears the table
        store.save([])
        assert store.load() == []


class TestBlobSqliteStore:
    def test_default_when_absent_dict(self, tmp_path):
        store = _FakeBlobStore(WebUIDatabase(tmp_path / "webui.db"))
        assert store.load() == {}

    def test_default_when_absent_list(self, tmp_path):
        store = _FakeListBlobStore(WebUIDatabase(tmp_path / "webui.db"))
        assert store.load() == []

    def test_save_load_roundtrip(self, tmp_path):
        store = _FakeBlobStore(WebUIDatabase(tmp_path / "webui.db"))
        store.save({"a": 1, "b": [2, 3]})
        assert store.load() == {"a": 1, "b": [2, 3]}

    def test_save_overwrites(self, tmp_path):
        store = _FakeBlobStore(WebUIDatabase(tmp_path / "webui.db"))
        store.save({"a": 1})
        store.save({"b": 2})
        assert store.load() == {"b": 2}

    def test_corrupt_json_falls_to_default(self, tmp_path):
        store = _FakeBlobStore(WebUIDatabase(tmp_path / "webui.db"))
        with store._db.connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO fake_blob (id, data_json) VALUES (1, ?)",
                ("not-json{{{",),
            )
        assert store.load() == {}

    def test_type_mismatch_falls_to_default(self, tmp_path):
        store = _FakeBlobStore(WebUIDatabase(tmp_path / "webui.db"))
        with store._db.connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO fake_blob (id, data_json) VALUES (1, ?)",
                ("[1, 2, 3]",),  # a list, but _value_type is dict
            )
        assert store.load() == {}

    def test_update_atomic(self, tmp_path):
        store = _FakeBlobStore(WebUIDatabase(tmp_path / "webui.db"))
        store.save({"n": 0})
        store.update(lambda v: {**v, "n": v["n"] + 1})
        assert store.load() == {"n": 1}

    def test_blob_migrate_roundtrip(self, tmp_path):
        (tmp_path / "fake-blob.json").write_text('{"k": "v"}', encoding="utf-8")
        store = _FakeBlobStore(WebUIDatabase(tmp_path / "webui.db"))
        store.migrate_from_json(tmp_path)
        assert store.load() == {"k": "v"}
        assert (tmp_path / "fake-blob.json.migrated").exists()

    def test_invalid_table_name_rejected_at_class_definition(self):
        # Defense-in-depth: _table_name is interpolated into DDL/DML, so a
        # non-identifier must fail at class-definition time, not as a cryptic
        # SQL error at runtime.
        with pytest.raises(TypeError, match="bare SQL identifier"):
            class _BadBlob(BlobSqliteStore):  # noqa: F811
                _table_name = "bad; DROP TABLE x"
                _value_type = dict

    def test_valid_table_name_accepted(self):
        class _OkBlob(BlobSqliteStore):
            _table_name = "ok_table_1"
            _value_type = dict

        assert _OkBlob._table_name == "ok_table_1"
