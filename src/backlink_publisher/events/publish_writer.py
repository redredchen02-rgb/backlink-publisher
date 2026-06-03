"""Dual-write publish results to events.db (Plan 2026-05-28-007 U2).

Writes publish-result events to events.db alongside legacy ``history_store``
writes.  All history write paths should call ``write_event`` here instead of
writing directly to ``history_store``; the legacy store is maintained for
backward compat until U5 switches reads to events.db.

Dual-write errors are logged but never raised — the primary write path
(legacy ``history_store``) must never be disrupted by a failing events.db.
"""

from __future__ import annotations

import logging
from urllib.parse import urlparse

from . import kinds
from .store import EventStore

log = logging.getLogger(__name__)

_STORE: EventStore | None = None


def _get_store() -> EventStore:
    global _STORE
    if _STORE is not None:
        # If BACKLINK_PUBLISHER_CONFIG_DIR changed since the cached
        # EventStore was created, re-resolve (same defensive pattern as
        # _LazyStore._real()).  Without this, tests that monkeypatch
        # config dir per fixture cannot isolate events.db.
        import os
        current_env = os.environ.get("BACKLINK_PUBLISHER_CONFIG_DIR")
        fresh = EventStore()
        if fresh.path != _STORE.path:
            _STORE = None
    if _STORE is None:
        _STORE = EventStore()
    return _STORE


def write_event(
    kind: str,
    payload: dict,
    *,
    target_url: str | None = None,
    host: str | None = None,
    article_id: int | None = None,
) -> int | None:
    """Append one publish-related event to events.db.

    Returns the row_id on success, ``None`` on failure (logged, never raises).
    Dual-write must never break the primary write path.

    If ``host`` is not provided but ``target_url`` is, the hostname is
    extracted automatically via ``urllib.parse.urlparse``.
    """
    if host is None and target_url:
        try:
            parsed = urlparse(target_url)
            host = parsed.hostname or None
        except Exception:
            pass
    try:
        return _get_store().append(
            kind=kind,
            payload=payload,
            target_url=target_url,
            host=host,
            article_id=article_id,
        )
    except Exception:
        log.warning(
            "publish_writer: failed to write event kind=%s target_url=%s",
            kind, target_url,
            exc_info=True,
        )
        return None


def map_history_entry(
    entry: dict,
) -> tuple[str, dict] | None:
    """Map a single history entry dict to ``(kind, payload)``.

    Mirrors ``kinds.STATUS_MAP["history"]`` — ``drafted`` returns ``None``
    (NO_EMIT per kinds contract; drafts source owns that status).
    Statuses ending in ``_unverified`` map to ``publish.unverified``.
    """
    status = entry.get("status", "")
    error = entry.get("error", "")

    if status == "published":
        live_url = (entry.get("article_urls") or [None])[0]
        return (
            kinds.PUBLISH_CONFIRMED,
            {
                "live_url": live_url,
                "target_url": entry.get("target_url", ""),
                "platform": entry.get("platform", ""),
                "title": entry.get("title", ""),
            },
        )

    if status.endswith("_unverified"):
        live_url = (entry.get("article_urls") or [None])[0]
        return (
            kinds.PUBLISH_UNVERIFIED,
            {
                "live_url": live_url,
                "target_url": entry.get("target_url", ""),
                "platform": entry.get("platform", ""),
            },
        )

    if status == "failed" or error:
        return (
            kinds.PUBLISH_FAILED,
            {
                "error_class": "publish_failed",
                "error_message_clean": error or "unknown error",
                "target_url": entry.get("target_url", ""),
                "platform": entry.get("platform", ""),
            },
        )

    # drafted, scheduled, etc → NO_EMIT
    return None
