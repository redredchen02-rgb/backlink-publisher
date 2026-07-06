"""HistoryStore — publish-history specialised store (Plan 2026-05-28-007 U6).

Hybrid mode:
- When ``path`` is given (tests and production singleton): JSON-file backed,
  identical to the pre-U6 JsonStore behaviour.  All bulk helpers (bulk_delete,
  bulk_update, purge_by_status, delete_item) operate on the JSON file.
- When ``path`` is None (legacy no-op shim): reads delegate to events.db via
  ``history_query``; writes are no-ops.  Kept for compatibility with callers
  that construct ``HistoryStore()`` without a path; not used by the singleton.
"""

from __future__ import annotations

from collections.abc import Callable
import json
from pathlib import Path
import threading
from typing import Any


class HistoryStore:
    """Publish-history store.

    With a path: full JSON-file store (used by tests and production singleton).
    Without a path: read-only events.db shim (legacy no-op mode, kept for
    compatibility with any caller that constructs HistoryStore() without a path).
    """

    def __init__(self, path: Any = None) -> None:
        self._path: Path | None = Path(path) if path is not None else None
        self._lock = threading.Lock()

    @property
    def path(self) -> Path | None:
        """Legacy path property (``_LazyStore`` proxy accesses this)."""
        return self._path

    @path.setter
    def path(self, new_path: Any) -> None:
        self._path = Path(new_path) if new_path is not None else None

    # ── read ────────────────────────────────────────────────────────────────

    def load(self) -> list[dict[str, Any]]:
        if self._path is None:
            from backlink_publisher.events.history_query import list_history
            return list_history()
        if not self._path.exists():
            return []
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return []

    def save(self, items: list[dict[str, Any]]) -> None:
        if self._path is None:
            return  # no-op in events.db mode
        from backlink_publisher.persistence.safe_write import atomic_write
        atomic_write(self._path, json.dumps(items, ensure_ascii=False, indent=2))

    def update(self, fn: Callable[[Any], Any]) -> list[dict[str, Any]]:
        if self._path is None:
            return self.load()
        with self._lock:
            current = self.load()
            new_value = fn(current)
            self.save(new_value)
            return new_value

    # ── Item helpers ──────────────────────────────────────────────────

    def get_item(self, item_id: str) -> dict | None:
        if self._path is None:
            from backlink_publisher.events.history_query import get_history_item
            return get_history_item(item_id)
        items = self.load()
        return next((it for it in items if str(it.get("id", "")) == str(item_id)), None)

    def update_item(self, item_id: str, **fields: Any) -> bool:
        if self._path is None:
            return self._update_item_events_db(item_id, **fields)
        if not fields:
            return False
        def _fn(items: list) -> list:
            for it in items:
                if str(it.get("id", "")) == str(item_id):
                    it.update(fields)
            return items
        with self._lock:
            items = self.load()
            matched = any(str(it.get("id", "")) == str(item_id) for it in items)
            if not matched:
                # Item may be in events.db (post-U2 integer article_id).
                return self._update_item_events_db(item_id, **fields)
            self.save(_fn(items))
            return True

    def delete_item(self, item_id: str) -> bool:
        if self._path is None:
            return False
        with self._lock:
            items = self.load()
            new_items = [it for it in items if str(it.get("id", "")) != str(item_id)]
            if len(new_items) == len(items):
                return False
            self.save(new_items)
            return True

    def bulk_delete(self, ids: list[str]) -> int:
        if self._path is None or not ids:
            return 0
        id_set = {str(i) for i in ids}
        with self._lock:
            items = self.load()
            new_items = [it for it in items if str(it.get("id", "")) not in id_set]
            removed = len(items) - len(new_items)
            if removed:
                self.save(new_items)
            return removed

    def bulk_update(self, ids: list[str], **fields: Any) -> int:
        if self._path is None or not ids or not fields:
            return 0
        id_set = {str(i) for i in ids}
        with self._lock:
            items = self.load()
            count = 0
            for it in items:
                if str(it.get("id", "")) in id_set:
                    it.update(fields)
                    count += 1
            if count:
                self.save(items)
            return count

    def purge_by_status(self, status: str) -> int:
        if self._path is None or not status:
            return 0
        with self._lock:
            items = self.load()
            new_items = [it for it in items if it.get("status") != status]
            removed = len(items) - len(new_items)
            if removed:
                self.save(new_items)
            return removed

    # ── events.db update_item (path=None mode) ────────────────────────

    def _update_item_events_db(self, item_id: str, **fields: Any) -> bool:
        verified_at = fields.get("verified_at")
        verify_error = fields.get("verify_error")
        if not verified_at and not verify_error:
            return False
        try:
            aid = int(item_id)
        except (ValueError, TypeError):
            return False
        from backlink_publisher.events.store import EventStore
        store = EventStore()
        sets: list[str] = []
        params: list[Any] = []
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
