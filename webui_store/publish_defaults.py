"""PublishDefaultsSqliteStore — last-used platforms + targets (Plan 2026-06-09-001 U5).

Single-row blob store in ``webui.db`` table ``publish_defaults``.
Stores ``last_platforms`` (JSON list) and ``last_target_ids`` (JSON list)
so the quick-publish button can bypass the full publish flow when defaults exist.
"""

from __future__ import annotations

import json
from typing import Any

from .sqlite_base import SqliteStore, WebUIDatabase, _retry_sqlite


class PublishDefaultsSqliteStore(SqliteStore):
    """Single-row blob store for last-used publish defaults.

    Table: ``publish_defaults (id INTEGER PRIMARY KEY, data_json TEXT NOT NULL)``

    ``load()`` returns ``{"last_platforms": [...], "last_target_ids": [...]}``
    or ``{}`` if no defaults have been saved yet.
    ``save(value)`` replaces the row atomically.
    ``update(fn)`` is inherited (load → fn → save under RLock).
    """

    def __init__(self, db: WebUIDatabase) -> None:
        super().__init__(db)
        self._init_table()

    def _init_table(self) -> None:
        with self._db.connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS publish_defaults "
                "(id INTEGER PRIMARY KEY, data_json TEXT NOT NULL DEFAULT '{}')"
            )

    def load(self) -> dict[str, Any]:
        def _op() -> dict[str, Any]:
            with self._db.connect() as conn:
                row = conn.execute(
                    "SELECT data_json FROM publish_defaults WHERE id = 1"
                ).fetchone()
            if row is None:
                return {}
            try:
                result = json.loads(row[0])
                return result if isinstance(result, dict) else {}
            except (json.JSONDecodeError, TypeError):
                return {}

        return _retry_sqlite(_op)

    def save(self, value: Any) -> None:
        with self._lock:
            def _op() -> None:
                with self._db.connect() as conn:
                    conn.execute(
                        "INSERT OR REPLACE INTO publish_defaults (id, data_json) "
                        "VALUES (1, ?)",
                        (json.dumps(value, ensure_ascii=False),),
                    )
            _retry_sqlite(_op)
