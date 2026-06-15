"""SQLite-backed store base for webui.db.

``WebUIDatabase`` owns the connection lifecycle (WAL, 0o600 chmod, WAL-sidecar
tighten, backup-xattr exclusion). ``SqliteStore`` wraps it into a Store-protocol
adapter with a ``threading.RLock`` so both ``save()`` (called directly by
``settings_service.py``) and ``update()`` (which also calls ``save()``) are safe
without re-entrancy deadlock.

Plan: docs/plans/2026-06-03-008-refactor-webui-store-sqlite-unification-plan.md
Unit 1.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import threading
from abc import ABC, abstractmethod
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, ClassVar, Iterator

#: A bare SQL identifier (table name). Enforced on BlobSqliteStore subclasses
#: because the table name is interpolated into DDL/DML (SQLite cannot bind it).
_SQL_IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")

from backlink_publisher.events._store_sqlite import (
    _retry_sqlite,
    _set_backup_exclude_xattr,
    _tighten_wal_sidecars,
)

_log = logging.getLogger(__name__)

#: Filename for the webui operational state database. Kept here rather than
#: importing ``_DB_FILENAME`` from ``_store_sqlite`` (which is "events.db").
_DB_FILENAME: str = "webui.db"


class WebUIDatabase:
    """Connection factory for ``webui.db``.

    Mirrors ``DedupStore._connect_raw``: WAL mode, ``synchronous=NORMAL``,
    ``busy_timeout=5000``, 0o600 on first create, WAL-sidecar tighten, and
    macOS backup-exclusion xattr. Does not own any DDL — each
    ``SqliteStore`` subclass creates its own table on first connect.

    ``_DB_FILENAME`` is a class constant so subclasses or tests can inspect
    it. The path must be derived externally (``_config_dir() / "webui.db"``)
    and passed in; this class must NOT call ``_default_db_path()`` from
    ``_store_sqlite`` (which resolves to ``"events.db"``).
    """

    _DB_FILENAME: str = "webui.db"

    def __init__(self, path: Path) -> None:
        self.path = path

    def _connect_raw(self) -> sqlite3.Connection:
        first_create = not self.path.exists()
        if first_create:
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            try:
                os.chmod(self.path.parent, 0o700)
            except OSError:
                pass

        conn = sqlite3.connect(str(self.path), timeout=5.0)
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.commit()

        if first_create:
            try:
                os.chmod(self.path, 0o600)
            except OSError:
                pass
            _set_backup_exclude_xattr(self.path)

        _tighten_wal_sidecars(self.path)
        return conn

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        """Yield an open WAL-mode connection; commit on success, rollback on error."""
        conn = self._connect_raw()
        try:
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()


class SqliteStore(ABC):
    """Abstract base for ``webui.db``-backed store implementations.

    Satisfies the ``Store`` protocol (``load`` / ``save`` / ``update``).
    Subclasses implement ``load()``, ``save()``, and ``_init_table()``;
    ``update()`` is provided here as ``load → fn → save`` under a
    ``threading.RLock``.

    RLock (reentrant) is required because ``update()`` acquires the lock and
    then delegates to ``save()``, which also acquires the same lock. A plain
    ``Lock`` would deadlock on that call path.

    The ``path`` property exposes ``self._db.path`` for backward compat with
    tests that do ``monkeypatch.setattr(store, "path", tmp_path / "x")``.
    The setter re-runs ``_init_table()`` so the redirected db has its schema.
    """

    def __init__(self, db: WebUIDatabase) -> None:
        self._db = db
        self._lock = threading.RLock()

    @abstractmethod
    def load(self) -> Any:
        """Return the persisted value, or a type-appropriate default if absent."""
        ...

    @abstractmethod
    def save(self, value: Any) -> None:
        """Persist ``value`` atomically under the store lock."""
        ...

    @abstractmethod
    def _init_table(self) -> None:
        """Create the store's table (``CREATE TABLE IF NOT EXISTS …``).

        Called by ``__init__`` and by the ``path`` setter when the backing
        database is redirected (e.g. by test fixtures).
        """
        ...

    def update(self, fn: Callable[[Any], Any]) -> Any:
        """Atomic ``load → fn → save`` under RLock. Returns the new value."""
        with self._lock:
            current = self.load()
            new_value = fn(current)
            self.save(new_value)
            return new_value

    # ── Backward compat: path property mirrors JsonStore ──────────────────

    @property
    def path(self) -> Path:
        """The underlying ``webui.db`` path. Exposed for test fixture compat."""
        return self._db.path

    @path.setter
    def path(self, value: Path) -> None:
        """Redirect the store to a different db file and re-initialise schema."""
        self._db = WebUIDatabase(value)
        self._init_table()


class BaseSqliteStore(SqliteStore):
    """Template base for ``webui.db`` stores — extracts the duplicated skeleton.

    Carries the three pieces every concrete store repeated verbatim:

    1. ``__init__`` — accepts a :class:`WebUIDatabase` *or* a plain
       :class:`~pathlib.Path` (the latter wrapped automatically, preserving the
       backward-compat constructor that ``drafts`` / ``campaign`` exposed for
       file-path callers and tests), then runs ``_init_table()``.
    2. ``_init_table`` — a template method: subclasses supply
       ``_create_table_sql()`` (and optionally ``_indices_sql()``); the
       connect/execute boilerplate lives here.
    3. ``migrate_from_json`` — the byte-identical one-shot JSON import sequence
       (sentinel → crash-recovery → read → save → rename → 0o600 → sentinel),
       parameterised by ``_json_filename`` / ``_sentinel_name`` / ``_value_type``.
       Stores with no JSON predecessor leave ``_json_filename`` ``None`` and the
       method is a no-op.

    ``load`` / ``save`` stay abstract: the row-table (DELETE + bulk-insert, with
    a per-store ``ORDER BY`` and column mirroring) and single-row-blob
    (``INSERT OR REPLACE``) write shapes differ enough that a single canonical
    implementation would need more hooks than it saves. ``BlobSqliteStore``
    below supplies the blob shape; row stores implement their own ``save`` and
    reuse the ``_load_rows`` / ``_get_one_json`` read helpers.
    """

    #: JSON predecessor filename in the config dir (``None`` → no migration).
    _json_filename: ClassVar[str | None] = None
    #: One-shot migration sentinel filename (``None`` → no migration).
    _sentinel_name: ClassVar[str | None] = None
    #: Top-level type of ``load()``'s return value (``list`` or ``dict``). Used
    #: to coerce imported JSON during migration and as the blob default type.
    _value_type: ClassVar[type] = dict

    def __init__(self, db: WebUIDatabase | Path) -> None:
        if not isinstance(db, WebUIDatabase):
            db = WebUIDatabase(Path(db))
        super().__init__(db)
        self._init_table()

    # ── Table creation template ───────────────────────────────────────────

    @abstractmethod
    def _create_table_sql(self) -> str:
        """Return the ``CREATE TABLE IF NOT EXISTS …`` statement for this store."""
        ...

    def _indices_sql(self) -> list[str]:
        """Return ``CREATE INDEX IF NOT EXISTS …`` statements (default: none)."""
        return []

    def _init_table(self) -> None:
        with self._db.connect() as conn:
            conn.execute(self._create_table_sql())
            for index_sql in self._indices_sql():
                conn.execute(index_sql)

    # ── Shared read helpers (row-table stores) ────────────────────────────

    def _load_rows(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        """Run ``sql`` (selecting a single ``data_json`` column per row) and
        parse each into a dict, skipping malformed/non-dict rows.

        The shared body of every row-table ``load()``. The caller owns the
        ``ORDER BY`` (load-bearing and per-store) by passing the full SQL.
        """
        def _op() -> list[tuple[Any, ...]]:
            with self._db.connect() as conn:
                return conn.execute(sql, params).fetchall()

        rows = _retry_sqlite(_op)
        result: list[dict[str, Any]] = []
        for row in rows:
            try:
                item = json.loads(row[0])
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(item, dict):
                result.append(item)
        return result

    def _get_one_json(self, sql: str, params: tuple[Any, ...]) -> dict | None:
        """Run ``sql`` (selecting a single ``data_json`` column for one row) and
        return the parsed dict, or ``None`` if absent/malformed/non-dict.

        The shared body of ``drafts.get_item`` / ``campaign.get``.
        """
        def _op() -> tuple[Any, ...] | None:
            with self._db.connect() as conn:
                return conn.execute(sql, params).fetchone()

        row = _retry_sqlite(_op)
        if row is None:
            return None
        try:
            item = json.loads(row[0])
        except (json.JSONDecodeError, TypeError):
            return None
        return item if isinstance(item, dict) else None

    # ── One-shot JSON → SQLite migration (shared sequence) ─────────────────

    def _coerce_migrated(self, data: Any) -> Any:
        """Coerce imported JSON to ``_value_type`` (preserves the per-store
        ``data if isinstance(data, list/dict) else default`` guard)."""
        return data if isinstance(data, self._value_type) else self._value_type()

    def migrate_from_json(self, config_dir: Path) -> None:
        """One-shot import from the legacy JSON file, if not yet migrated.

        Load-bearing sequence (unchanged from the per-store originals):
        sentinel-skip → crash-recovery (``.migrated`` present, sentinel absent)
        → read JSON (corrupt/absent → silent skip, sentinel NOT written so a
        later-appearing file can still import) → commit to webui.db → rename
        ``.json`` → chmod ``.json.migrated`` 0o600 → write sentinel.

        No-op for stores without a JSON predecessor (``_json_filename`` unset).
        """
        if not self._json_filename or not self._sentinel_name:
            return

        sentinel = config_dir / self._sentinel_name
        json_path = config_dir / self._json_filename
        migrated_path = json_path.with_suffix(".json.migrated")

        if sentinel.exists():
            return

        # Crash-recovery: rename completed but sentinel not written.
        if migrated_path.exists() and not sentinel.exists():
            sentinel.write_text("migrated", encoding="utf-8")
            return

        if not json_path.exists():
            return

        try:
            text = json_path.read_text(encoding="utf-8")
            data = json.loads(text)
        except (json.JSONDecodeError, UnicodeDecodeError, OSError):
            _log.warning(
                "%s migration: skipping corrupt/unreadable %s",
                type(self).__name__, json_path,
            )
            return

        self.save(self._coerce_migrated(data))

        try:
            json_path.rename(migrated_path)
        except OSError as exc:
            _log.warning("%s migration: rename failed: %s", type(self).__name__, exc)
            return

        try:
            os.chmod(migrated_path, 0o600)
        except OSError:
            pass

        sentinel.write_text("migrated", encoding="utf-8")


class BlobSqliteStore(BaseSqliteStore):
    """Single-row blob store: the whole value lives in one ``data_json`` row
    (``id = 1``), replaced wholesale via ``INSERT OR REPLACE``.

    Subclasses set ``_table_name`` and ``_value_type`` (``list`` or ``dict``);
    everything else — table DDL, ``load`` (with default + corrupt fall-through),
    ``save`` — is supplied here. ``migrate_from_json`` is inherited from
    :class:`BaseSqliteStore` (set ``_json_filename`` / ``_sentinel_name`` to
    enable it).
    """

    #: Table name for this blob store. Interpolated into DDL/DML (SQLite cannot
    #: bind identifiers), so it must be a bare SQL identifier — enforced at
    #: subclass-definition time by ``__init_subclass__`` below.
    _table_name: ClassVar[str]

    def __init_subclass__(cls, **kwargs: Any) -> None:
        # Fail fast at class-definition time if a subclass sets a _table_name
        # that is not a safe SQL identifier (defends the f-string DDL/DML below
        # against a future subclass introducing an injection/syntax footgun).
        # Abstract intermediates that do not set _table_name are skipped.
        super().__init_subclass__(**kwargs)
        table = getattr(cls, "_table_name", None)
        if table is not None and not _SQL_IDENTIFIER_RE.match(str(table)):
            raise TypeError(
                f"{cls.__name__}._table_name must be a bare SQL identifier "
                f"(got {table!r}); it is interpolated into DDL/DML."
            )

    def _default(self) -> Any:
        # NOTE: ``_value_type`` must be ``list`` or ``dict`` so the DDL DEFAULT
        # literal below serialises to a quote-free ``[]`` / ``{}``. A custom
        # type whose empty value contains quotes would break ``_create_table_sql``.
        return self._value_type()

    def _create_table_sql(self) -> str:
        default_literal = json.dumps(self._default())
        return (
            f"CREATE TABLE IF NOT EXISTS {self._table_name} "
            f"(id INTEGER PRIMARY KEY, data_json TEXT NOT NULL "
            f"DEFAULT '{default_literal}')"
        )

    def load(self) -> Any:
        def _op() -> Any:
            with self._db.connect() as conn:
                row = conn.execute(
                    f"SELECT data_json FROM {self._table_name} WHERE id = 1"
                ).fetchone()
            if row is None:
                return self._default()
            try:
                result = json.loads(row[0])
            except (json.JSONDecodeError, TypeError):
                return self._default()
            return result if isinstance(result, self._value_type) else self._default()

        return _retry_sqlite(_op)

    def save(self, value: Any) -> None:
        with self._lock:
            def _op() -> None:
                with self._db.connect() as conn:
                    conn.execute(
                        f"INSERT OR REPLACE INTO {self._table_name} "
                        f"(id, data_json) VALUES (1, ?)",
                        (json.dumps(value, ensure_ascii=False),),
                    )

            _retry_sqlite(_op)
