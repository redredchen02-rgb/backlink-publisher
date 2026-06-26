"""BatchOpsSqliteStore — per-site batch operation queue (Plan 2026-06-09-001 U6).

Table: batch_ops (id, site_url, operation, status, created_at, updated_at)
Operations: keep_alive | recheck | channel_health
Status:     pending | processing | done | failed
"""

from __future__ import annotations

from datetime import datetime, UTC
from typing import Any
import uuid

from .sqlite_base import _retry_sqlite, SqliteStore, WebUIDatabase

VALID_OPERATIONS = frozenset({"keep_alive", "recheck", "channel_health"})


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


class BatchOpsSqliteStore(SqliteStore):
    """Queue of batch operations keyed by (site_url, operation).

    ``enqueue_many`` writes one row per site URL.
    ``get_pending_one`` returns the oldest pending row (FIFO).
    ``update_row`` patches status + updated_at atomically.
    ``list_status`` returns all rows ordered by created_at desc.
    """

    def __init__(self, db: WebUIDatabase) -> None:
        super().__init__(db)
        self._init_table()

    def _init_table(self) -> None:
        with self._db.connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS batch_ops ("
                " id TEXT PRIMARY KEY,"
                " site_url TEXT NOT NULL,"
                " operation TEXT NOT NULL,"
                " status TEXT NOT NULL DEFAULT 'pending',"
                " created_at TEXT NOT NULL,"
                " updated_at TEXT NOT NULL,"
                " error TEXT"
                ")"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS batch_ops_status_idx "
                "ON batch_ops (status, created_at)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS batch_ops_created_idx "
                "ON batch_ops (created_at DESC)"
            )

    def enqueue_many(self, site_urls: list[str], operation: str) -> list[str]:
        """Insert one pending row per site URL; return list of row IDs."""
        now = _now_iso()
        ids: list[str] = []
        with self._lock:
            def _op() -> None:
                with self._db.connect() as conn:
                    for url in site_urls:
                        row_id = str(uuid.uuid4())
                        conn.execute(
                            "INSERT INTO batch_ops "
                            "(id, site_url, operation, status, created_at, updated_at) "
                            "VALUES (?, ?, ?, 'pending', ?, ?)",
                            (row_id, url, operation, now, now),
                        )
                        ids.append(row_id)
            _retry_sqlite(_op)
        return ids

    def get_pending_one(self) -> dict[str, Any] | None:
        """Return the oldest pending row, or None."""
        def _op() -> dict[str, Any] | None:
            with self._db.connect() as conn:
                row = conn.execute(
                    "SELECT id, site_url, operation, status, created_at, updated_at, error "
                    "FROM batch_ops WHERE status = 'pending' "
                    "ORDER BY created_at ASC LIMIT 1"
                ).fetchone()
            if row is None:
                return None
            return {
                "id": row[0], "site_url": row[1], "operation": row[2],
                "status": row[3], "created_at": row[4], "updated_at": row[5],
                "error": row[6],
            }
        return _retry_sqlite(_op)

    def update_row(self, row_id: str, status: str, error: str | None = None) -> None:
        """Patch status (and optional error) for one row."""
        now = _now_iso()
        with self._lock:
            def _op() -> None:
                with self._db.connect() as conn:
                    conn.execute(
                        "UPDATE batch_ops SET status = ?, updated_at = ?, error = ? "
                        "WHERE id = ?",
                        (status, now, error, row_id),
                    )
            _retry_sqlite(_op)

    def list_status(self, limit: int = 200) -> list[dict[str, Any]]:
        """Return rows ordered by created_at desc."""
        def _op() -> list[dict[str, Any]]:
            with self._db.connect() as conn:
                rows = conn.execute(
                    "SELECT id, site_url, operation, status, created_at, updated_at, error "
                    "FROM batch_ops ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [
                {
                    "id": r[0], "site_url": r[1], "operation": r[2],
                    "status": r[3], "created_at": r[4], "updated_at": r[5],
                    "error": r[6],
                }
                for r in rows
            ]
        return _retry_sqlite(_op)

    # Required by SqliteStore ABC but not used (no blob value)
    def load(self) -> list[dict[str, Any]]:
        return self.list_status()

    def save(self, value: Any) -> None:
        raise NotImplementedError("Use enqueue_many / update_row instead")
