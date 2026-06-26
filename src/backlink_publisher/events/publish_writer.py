"""Write publish results to events.db as single authoritative store (Plan 2026-05-28-007 U2).

All publish write paths call ``write_publish_result`` (or ``write_event``).
No longer writes to ``history_store`` — events.db is the sole write target.
Errors are logged but never raised so a DB failure can't break a publish run.
"""

from __future__ import annotations

import logging
import sqlite3
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
        except ValueError:
            pass
    try:
        return _get_store().append(
            kind=kind,
            payload=payload,
            target_url=target_url,
            host=host,
            article_id=article_id,
        )
    except Exception:  # noqa: BLE001 — events.db failure must never break the caller
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
        payload: dict = {
            "live_url": live_url,
            "target_url": entry.get("target_url", ""),
            "platform": entry.get("platform", ""),
            "title": entry.get("title", ""),
        }
        if entry.get("adapter"):
            payload["adapter"] = entry["adapter"]
        return (kinds.PUBLISH_CONFIRMED, payload)

    if status.endswith("_unverified"):
        live_url = (entry.get("article_urls") or [None])[0]
        payload = {
            "live_url": live_url,
            "target_url": entry.get("target_url", ""),
            "platform": entry.get("platform", ""),
            "title": entry.get("title", ""),
            "ui_status": status,
        }
        if entry.get("adapter"):
            payload["adapter"] = entry["adapter"]
        return (kinds.PUBLISH_UNVERIFIED, payload)

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


def write_publish_result(item: dict, store: EventStore | None = None) -> int | None:
    """Write one publish-result history item to events.db atomically.

    For ``published`` and ``*_unverified`` items: inserts an ``articles`` row
    and the corresponding event in a single ``BEGIN IMMEDIATE`` transaction so
    the two rows are always consistent.

    For ``failed`` items: appends a ``publish.failed`` orphan event only (no
    article row — the publish never produced a live URL).

    Returns the ``article_id`` for published/unverified items, the event row_id
    for failed orphans, or ``None`` on any error (logged, never re-raised).

    Callers must not pass ``drafted`` / ``scheduled`` items — those are NO_EMIT
    and return ``None`` without writing anything.
    """
    mapped = map_history_entry(item)
    if mapped is None:
        return None  # drafted/scheduled/etc — intentional no-op

    kind, payload = mapped
    target_url = item.get("target_url")
    if target_url is None and payload.get("target_url"):
        target_url = payload["target_url"]

    try:
        s = store or _get_store()

        if kind == kinds.PUBLISH_FAILED:
            # Failure: orphan event, no articles row.
            return s.append(
                kind,
                payload,
                run_id=item.get("run_id"),
                target_url=target_url,
            )

        # published / *_unverified — create articles row + event atomically.
        live_url = (item.get("article_urls") or [None])[0]
        article: dict = {
            "live_url": live_url,
            "platform": item.get("platform") or "",
            "lang": item.get("language") or "",
            "run_id": item.get("run_id") or "",
            "published_at_raw": item.get("created_at") or "",
            "published_at_utc": item.get("created_at") or "",
        }

        pending: list[dict] = []
        with s.connect_immediate() as conn:
            try:
                article_id = s.add_article(article, conn=conn)
            except sqlite3.IntegrityError:
                # live_url collision — article row already exists; reuse it.
                row = conn.execute(
                    "SELECT article_id FROM articles WHERE live_url = ?",
                    (live_url,),
                ).fetchone()
                if row is None:
                    raise
                article_id = int(row[0])

            payload_with_id = {**payload, "article_id": article_id}
            s.append(
                kind,
                payload_with_id,
                run_id=item.get("run_id"),
                target_url=target_url,
                article_id=article_id,
                conn=conn,
                pending_quarantines=pending,
            )

        # Flush any quarantined records after the transaction committed.
        for qr in pending:
            try:
                s.quarantine(**qr)
            except Exception:  # noqa: BLE001
                log.debug("publish_writer: quarantine flush failed: %r", qr)

        return article_id

    except Exception:  # noqa: BLE001 — events.db failure must never break publishing
        log.warning(
            "publish_writer: failed to write result kind=%s target_url=%s",
            kind,
            target_url,
            exc_info=True,
        )
        return None
