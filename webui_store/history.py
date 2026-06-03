"""HistoryStore — publish-history specialised store (Plan 2026-05-28-007 U6).

U6 replaces the JSON-file store with a no-op shim: reads go through events.db
(``history_query``), writes are no-ops because the events.db equivalents are
handled by ``publish_writer`` / dual-write.  The ``HistoryStore`` class and
its method signatures are preserved so every import site keeps working.
"""

from __future__ import annotations

from typing import Any


class HistoryStore:
    """No-op shim backed by events.db (U6).

    ``load()`` and ``get_item()`` read from events.db via ``history_query``.
    All mutations are no-ops — the canonical data lives in events.db and is
    written by ``publish_writer``.
    """

    def __init__(self, path: Any = None) -> None:
        self._path = path  # kept for backward compat only

    # ── read ────────────────────────────────────────────────────────────────

    def load(self) -> list[dict[str, Any]]:
        from backlink_publisher.events.history_query import list_history  # noqa: PLC0415

        return list_history()

    def get_item(self, item_id: str) -> dict | None:
        from backlink_publisher.events.history_query import get_history_item  # noqa: PLC0415

        return get_history_item(item_id)

    # ── write (all no-op — canonical writes go through publish_writer) ──────

    def save(self, items: list[dict[str, Any]]) -> None:
        pass

    def update(self, fn: Any = None) -> list[dict[str, Any]]:
        return self.load()

    def update_item(self, item_id: str, **fields: Any) -> bool:
        """Update an article's verification fields in events.db.

        Accepts ``verified_at`` and ``verify_error``; other fields are
        silently ignored (no-op).  Returns ``True`` if the article was
        actually updated.
        """
        verified_at = fields.get("verified_at")
        verify_error = fields.get("verify_error")
        if not verified_at and not verify_error:
            return False
        try:
            aid = int(item_id)
        except (ValueError, TypeError):
            return False
        from backlink_publisher.events.store import EventStore  # noqa: PLC0415

        store = EventStore()
        sets: list[str] = []
        params: list[str] = []
        if verified_at is not None:
            sets.append("verified_at = ?")
            params.append(verified_at)
        if verify_error is not None:
            sets.append("verify_error = ?")
            params.append(verify_error)
        if not sets:
            return False
        params.append(str(aid))
        try:
            with store.connect() as conn:
                conn.execute(
                    f"UPDATE articles SET {', '.join(sets)} WHERE article_id = ?",
                    params,
                )
            return True
        except Exception:
            return False

    def delete_item(self, item_id: str) -> bool:
        return False

    def bulk_delete(self, ids: list[str]) -> int:
        return 0

    def bulk_update(self, ids: list[str], **fields: Any) -> int:
        return 0

    def purge_by_status(self, status: str) -> int:
        return 0
