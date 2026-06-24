"""Connection handling mixin for DedupStore."""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from ..events._store_sqlite import _set_backup_exclude_xattr, _tighten_wal_sidecars
from ._dedup_schema import _SCHEMA_DDL


class ConnectionMixin:
    """Provides SQLite connection management methods."""

    path: Path  # provided by the concrete subclass

    def _connect_raw(self) -> sqlite3.Connection:
        """Open a connection, apply PRAGMAs + schema + file hygiene, return it."""
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
        conn.execute(_SCHEMA_DDL)
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
    def connect(self) -> Generator[sqlite3.Connection, None, None]:
        """Open a connection, apply PRAGMAs + schema, yield to caller."""
        conn = self._connect_raw()
        try:
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    @contextmanager
    def connect_immediate(self) -> Generator[sqlite3.Connection, None, None]:
        """Like ``connect`` but opens the transaction with ``BEGIN IMMEDIATE``."""
        conn = self._connect_raw()
        conn.isolation_level = None
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.execute("COMMIT")
        except BaseException:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        finally:
            conn.close()
