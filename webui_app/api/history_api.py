"""HistoryAPI — structured CRUD wrapper around ``history_store`` + recheck.

Centralises history operations so routes never touch the store or recheck
service directly.  Every mutating method returns a dict with ``ok`` /
``flash_msg`` for the route's redirect (or JSON) response.

Plan 2026-05-28-007 U5: reads now go through ``events/history_query``
instead of ``_history_store``.  Write CRUD still hits ``_history_store``
until U6 makes it a no-op shim.
"""

from __future__ import annotations

from typing import Any

from flask import abort

from webui_store import history_store as _history_store
from webui_store import queue_store as _queue_store

from ..helpers.history import _REQUIRES_URL_STATUSES
from backlink_publisher.events.history_query import get_history_item, list_history
from backlink_publisher.events.publish_writer import (
    map_history_entry,
    write_event,
)


# ── HistoryAPI ─────────────────────────────────────────────────────────────


class HistoryAPI:
    """Encapsulates publish-history CRUD and recheck operations.

    Usage::

        api = HistoryAPI()
        items = api.list()
        result = api.recheck("item-123")
        # result == {"ok": True, "flash_msg": "已重新核实：状态 → published"}
    """

    # ── list ──────────────────────────────────────────────────────────────

    @staticmethod
    def _normalize_item(item: dict) -> dict:
        """Backfill URL fields for older history rows."""
        normalized = dict(item)
        article_urls = normalized.get("article_urls")
        if not isinstance(article_urls, list) or not article_urls:
            article_urls = [
                u for u in (
                    (normalized.get("published_url") or "").strip(),
                    (normalized.get("draft_url") or "").strip(),
                ) if u
            ]
        if article_urls:
            normalized["article_urls"] = article_urls
        target_url = (normalized.get("target_url") or "").strip()
        if not target_url:
            normalized["target_url"] = article_urls[0] if article_urls else "unknown"
        # Centralised no-signal default: legacy rows with no captured verdict
        # read "unverified" (amber), never a misleading green/red.
        if not normalized.get("target_dofollow"):
            normalized["target_dofollow"] = "unverified"
        return normalized

    @staticmethod
    def _normalize_items(items: list[dict]) -> list[dict]:
        return [HistoryAPI._normalize_item(item) for item in items]

    def list(self) -> list[dict]:
        """Return all history items from events.db, normalised."""
        return self._normalize_items(list_history())

    # ── delete ────────────────────────────────────────────────────────────

    def delete(self, item_id: str) -> dict[str, Any]:
        """Delete a single history entry."""
        if not item_id:
            return {"ok": False, "flash_msg": "参数缺失"}
        history = _history_store.update(
            lambda hist: [h for h in hist if h.get("id") != item_id]
        )
        return {
            "ok": True,
            "history": self._normalize_items(history),
        }

    # ── update-status ─────────────────────────────────────────────────────

    def update_status(
        self,
        item_id: str,
        new_status: str,
    ) -> dict[str, Any]:
        """Update the status of a single history entry.

        Validates the server-side invariant: ``published`` / ``drafted``
        statuses require at least one article URL.
        """
        if not item_id or not new_status:
            return {"ok": False, "flash_msg": "参数缺失"}

        # Server-side invariant guard (F22)
        if new_status in _REQUIRES_URL_STATUSES:
            matched = self._get_item(item_id)
            if matched is not None and not matched.get("article_urls"):
                abort(400, description=(
                    f"invariant_violation: cannot set status={new_status!r} "
                    "on a history row with no article URLs"
                ))

        def _apply(hist):
            for h in hist:
                if h.get("id") == item_id:
                    h["status"] = new_status
                    break
            return hist

        history = _history_store.update(_apply)
        return {
            "ok": True,
            "history": self._normalize_items(history),
        }

    # ── reuse ─────────────────────────────────────────────────────────────

    def reuse(self, target_url: str) -> dict[str, Any]:
        """Prepare state for reusing a history entry's target URL."""
        return {"ok": True, "target_url": target_url}

    # ── bulk operations ──────────────────────────────────────────────────

    def bulk_delete(self, ids: list[str]) -> dict[str, Any]:
        """Delete multiple history entries by id."""
        if not ids:
            return {"ok": False, "flash_msg": "未选择任何项"}
        removed = _history_store.bulk_delete(ids)
        return {"ok": True, "flash_msg": f"已删除 {removed} 条历史记录"}

    def purge_failed(self) -> dict[str, Any]:
        """Delete every history entry whose status is exactly ``failed``.

        Returns ``ok=False`` when no records were removed so callers can
        set ``flash_type=info`` instead of ``flash_type=success``.
        """
        removed = _history_store.purge_by_status("failed")
        if removed == 0:
            return {"ok": False, "flash_msg": "没有失败记录可清除"}
        return {"ok": True, "flash_msg": f"已清除 {removed} 条失败记录"}

    # ── item lookup (events.db with fallback to JSON store) ───────────────

    def _get_item(self, item_id: str) -> dict[str, Any] | None:
        """Look up one history item from events.db, falling back to history_store.

        events.db uses integer article_id; history_store uses UUID8 strings.
        During the transitional dual-write period both stores may hold the
        authoritative copy for a given item, so we check both.
        """
        item = get_history_item(item_id)
        if item is None:
            item = _history_store.get_item(item_id)
        return item

    def _all_items_by_id(self, ids: list[str]) -> list[dict[str, Any]]:
        """Return history items matching ``ids``, checking events.db then history_store."""
        id_set = set(ids)
        found: dict[str, dict] = {
            str(it.get("id", "")): it
            for it in list_history()
            if str(it.get("id", "")) in id_set
        }
        missing = id_set - set(found)
        if missing:
            for it in _history_store.load():
                key = str(it.get("id", ""))
                if key in missing:
                    found[key] = it
        return list(found.values())

    # ── recheck ───────────────────────────────────────────────────────────

    def recheck(self, item_id: str) -> dict[str, Any]:
        """Re-verify a single history item."""
        if not item_id:
            return {"ok": False, "flash_msg": "参数缺失"}
        item = self._get_item(item_id)
        if not item:
            return {"ok": False, "flash_msg": "记录不存在"}

        from ..services.recheck import recheck_one
        mutation = recheck_one(self._normalize_item(item))
        mutation.pop("_outcome", None)
        _history_store.update_item(item_id, **mutation)
        status = mutation.get("status", "")
        updated = {**item, **mutation}
        mapped = map_history_entry(updated)
        if mapped is not None:
            try:
                aid: int | None = int(item_id)
            except (ValueError, TypeError):
                aid = None
            write_event(
                mapped[0], mapped[1],
                target_url=updated.get("target_url"),
                article_id=aid,
            )
        return {"ok": True, "flash_msg": f"已重新核实：状态 → {status}"}

    def bulk_recheck(self, ids: list[str]) -> dict[str, Any]:
        """Re-verify multiple history entries."""
        if not ids:
            return {"ok": False, "flash_msg": "未选择任何项"}
        items = self._all_items_by_id(ids)
        if not items:
            return {"ok": False, "flash_msg": "未匹配到记录"}

        from ..services.recheck import recheck_many
        by_id, summary = recheck_many(self._normalize_items(items))
        for item_id, mutation in by_id.items():
            _history_store.update_item(item_id, **mutation)
        for item_id, mutation in by_id.items():
            updated = dict(
                next(it for it in items if str(it.get("id", "")) == item_id),
                **mutation,
            )
            mapped = map_history_entry(updated)
            try:
                aid = int(item_id)
            except (ValueError, TypeError):
                aid = None
            if mapped is not None and aid is not None:
                write_event(
                    mapped[0], mapped[1],
                    target_url=updated.get("target_url"),
                    article_id=aid,
                )
        return {"ok": True, "flash_msg": summary.as_flash()}

    # ── retry-task (queue) ───────────────────────────────────────────────

    def retry_task(self, task_id: str) -> dict[str, Any]:
        """Reset a queue task to pending for retry."""
        if not task_id:
            return {"ok": False, "error": "Missing task_id"}
        _queue_store.update_task(task_id, {"status": "pending", "error": None})
        return {"ok": True, "message": "任务已重置为待发布状态"}
