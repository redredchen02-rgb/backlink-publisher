"""DraftsStore — draft-queue specialized JsonStore with item helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from .base import JsonStore


class DraftsStore(JsonStore):
    """Stores the draft queue (list of dicts) plus item-level helpers
    that mirror the legacy ``_get_draft_item`` / ``_update_draft_item``
    / ``_delete_draft_item`` semantics from ``webui.py``.

    All item operations go through ``update()`` so the per-store lock
    protects in-process concurrency between scheduler-triggered writes
    (background ``BackgroundScheduler`` jobs) and HTTP-handler writes.
    """

    def __init__(self, path: Path) -> None:
        super().__init__(path, default_factory=list)

    def get_item(self, item_id: str) -> dict | None:
        """Return the matching draft, or ``None``. Read-only; no lock."""
        for item in self.load():
            if item.get("id") == item_id:
                return item
        return None

    def update_item(self, item_id: str, **fields: Any) -> bool:
        """Locate by id, merge ``fields`` in place, save. Returns False
        if no matching id was found (no-op write skipped)."""
        with self._lock:
            items = self.load()
            for it in items:
                if it.get("id") == item_id:
                    it.update(fields)
                    self.save(items)
                    return True
            return False

    def delete_item(self, item_id: str) -> bool:
        """Remove the matching draft. Returns False if absent."""
        with self._lock:
            items = self.load()
            new_items = [it for it in items if it.get("id") != item_id]
            if len(new_items) == len(items):
                return False
            self.save(new_items)
            return True

    def insert_first(self, item: dict) -> list[dict]:
        """Atomic head-insert (legacy ``items.insert(0, item)`` pattern)."""
        return self.update(lambda items: [item, *items])

    def bulk_delete(self, ids: list[str]) -> int:
        """Delete multiple drafts by id. Returns count actually removed."""
        if not ids:
            return 0
        id_set = set(ids)
        with self._lock:
            items = self.load()
            kept = [it for it in items if it.get("id") not in id_set]
            removed = len(items) - len(kept)
            if removed:
                self.save(kept)
            return removed

    def get_by_campaign_id(self, campaign_id: str) -> list[dict]:
        """Return all drafts whose ``campaign_id`` field matches."""
        return [
            it for it in self.load()
            if it.get("campaign_id") == campaign_id
        ]

    def bulk_publish_now(
        self,
        ids: list[str],
        publish_fn: Callable[[dict], dict],
    ) -> dict:
        """Call ``publish_fn`` for each draft id, update status, return summary.

        Unknown ids are silently skipped.  ``publish_fn`` must return a dict
        with at least ``{"ok": bool}``; optionally ``{"error": str}`` on failure.
        Exceptions from ``publish_fn`` are caught and reported as failures.
        """
        published = 0
        failed = 0
        errors: list[str] = []
        for item_id in ids:
            draft = self.get_item(item_id)
            if draft is None:
                continue
            try:
                result = publish_fn(draft)
                if result.get("ok"):
                    self.update_item(item_id, status="published")
                    published += 1
                else:
                    err_msg = result.get("error") or "unknown error"
                    self.update_item(item_id, status="failed", error=err_msg)
                    failed += 1
                    errors.append(f"{item_id}: {err_msg}")
            except Exception as exc:  # noqa: BLE001
                err_msg = str(exc)
                self.update_item(item_id, status="failed", error=err_msg)
                failed += 1
                errors.append(f"{item_id}: {err_msg}")
        return {"published": published, "failed": failed, "errors": errors}

    def bulk_update(self, ids: list[str], **fields: Any) -> int:
        """Merge ``fields`` into every draft whose id is in ``ids``.
        Returns count actually mutated."""
        if not ids or not fields:
            return 0
        id_set = set(ids)
        with self._lock:
            items = self.load()
            n = 0
            for it in items:
                if it.get("id") in id_set:
                    it.update(fields)
                    n += 1
            if n:
                self.save(items)
            return n
