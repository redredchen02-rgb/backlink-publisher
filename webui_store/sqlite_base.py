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

import os
import sqlite3
import threading
from abc import ABC, abstractmethod
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator

from backlink_publisher.events._store_sqlite import (
    _retry_sqlite,
    _set_backup_exclude_xattr,
    _tighten_wal_sidecars,
)

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
