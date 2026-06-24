"""Query methods mixin for DedupStore."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Iterator, cast

from ..events._store_sqlite import _pid_alive, _retry_sqlite
from ._dedup_schema import _COLS, _row_to_record
from ._store_types import DedupKey, DedupRecord, State, _STALE_TTL_S, _now


class QueryMixin:
    """Provides read-only query operations."""

    def get(self, key: DedupKey) -> DedupRecord | None:
        """Get a single dedup record by key."""
        def _op() -> DedupRecord | None:
            with self.connect() as conn:  # type: ignore[attr-defined]
                row = conn.execute(
                    f"SELECT {_COLS} FROM dedup_keys "
                    "WHERE platform = ? AND account = ? AND target_url = ?",
                    key.as_tuple(),
                ).fetchone()
            return _row_to_record(row) if row is not None else None

        return cast("DedupRecord | None", _retry_sqlite(_op))

    def get_many(
        self, keys: Iterable[DedupKey]
    ) -> dict[tuple[str, str, str], DedupRecord]:
        """Batch point-read: look up every key in ``keys`` over a SINGLE connection."""
        wanted = {k.as_tuple() for k in keys}
        if not wanted:
            return {}

        def _op() -> dict[tuple[str, str, str], DedupRecord]:
            out: dict[tuple[str, str, str], DedupRecord] = {}
            with self.connect() as conn:  # type: ignore[attr-defined]
                for tup in wanted:
                    row = conn.execute(
                        f"SELECT {_COLS} FROM dedup_keys "
                        "WHERE platform = ? AND account = ? AND target_url = ?",
                        tup,
                    ).fetchone()
                    if row is not None:
                        out[tup] = _row_to_record(row)
            return out

        return cast("dict[tuple[str, str, str], DedupRecord]", _retry_sqlite(_op))

    def list_by_state(
        self, state: State, *, platform: str | None = None
    ) -> list[DedupRecord]:
        """All rows in ``state`` (optionally one ``platform``), newest-first."""
        def _op() -> list[DedupRecord]:
            sql = f"SELECT {_COLS} FROM dedup_keys WHERE state = ?"
            params: list[object] = [state]
            if platform:
                sql += " AND platform = ?"
                params.append(platform)
            sql += " ORDER BY updated_at DESC"
            with self.connect() as conn:  # type: ignore[attr-defined]
                rows = conn.execute(sql, params).fetchall()
            return [_row_to_record(r) for r in rows]

        return cast("list[DedupRecord]", _retry_sqlite(_op))

    def is_stale_attempting(
        self, record: DedupRecord, *, now: float | None = None, ttl_s: int = _STALE_TTL_S
    ) -> bool:
        """An ``attempting`` row is stale (its owning run died mid-dispatch) when
        the owner PID is gone, OR the row has aged past ``ttl_s``.
        """
        if record.state != "attempting":
            return False
        now = _now() if now is None else now
        if record.owner_pid is not None and not _pid_alive(record.owner_pid):
            return True
        if (now - record.updated_at) > ttl_s:
            return True
        return False
