"""Scheduled-item query surface for the WebUI schedule page."""
from __future__ import annotations

from typing import Any

from backlink_publisher._util.logger import plan_logger
from webui_store import drafts_store as _drafts_store


def list_scheduled() -> dict[str, Any]:
    """Return ``{ok: True, items: [...]}`` for drafts with a future or pending
    ``scheduled_at``/``status == "scheduled"``.
    """
    try:
        items = [
            item for item in _drafts_store.load()
            if item.get("status") == "scheduled"
            or item.get("scheduled_at")
        ]
        return {"ok": True, "items": items}
    except Exception as exc:
        # debt: scheduled-list-read-fail-open
        plan_logger.warn("scheduled_list_read_failed", reason=type(exc).__name__)
        return {"ok": False, "error": type(exc).__name__, "items": []}
