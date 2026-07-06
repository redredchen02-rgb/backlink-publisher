"""Emit helpers shared by checkpoint, history, and drafts reducers.

Extracted from ``_project_reducers.py`` (Plan 2026-06-11) to reduce that
module's SLOC from 714 to ~560 lines.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from . import kinds
from ._project_helpers import article_payload, host_of, split_local_naive
from .store import EventStore


def _parse_row_timestamps(created_at: str) -> tuple[str | None, str | None]:
    """Return *(ts_raw, ts_utc)* for *created_at*; ``(None, None)`` on blank/bad input."""
    if not created_at:
        return None, None
    try:
        return split_local_naive(created_at)
    except ValueError:
        return created_at or None, None


def _emit_confirmed_history_row(
    row: dict[str, Any],
    article_urls: object,
    target_url: str | None,
    host: str | None,
    language: str | None,
    ts_raw: str | None,
    ts_utc: str | None,
    store: EventStore,
    conn: sqlite3.Connection | None,
    pending_quarantines: list[dict[str, Any]],
) -> tuple[int, int, int, bool]:
    """Emit PUBLISH_CONFIRMED event(s) for one history row.

    Returns *(events_delta, articles_delta, skipped_delta, always_mark)*.
    ``always_mark=True`` means the row must be added to seen_ids regardless of
    the running skipped_due_to_dedup total (i.e. no-article-URL path).
    """
    if not isinstance(article_urls, list) or not article_urls:
        store.append(
            kinds.PUBLISH_CONFIRMED,
            {
                "live_url": None,
                "target_url": target_url,
                "platform": row.get("platform"),
            },
            target_url=target_url,
            host=host,
            ts_raw=ts_raw,
            ts_utc=ts_utc,
            conn=conn,
            pending_quarantines=pending_quarantines,
        )
        return 1, 0, 0, True

    events = 0
    articles = 0
    skipped = 0
    for live_url in article_urls:
        if not isinstance(live_url, str) or not live_url:
            continue
        article = article_payload(
            live_url=live_url,
            target_url=target_url,
            host=host_of(live_url),
            lang=language,
            published_at_raw=ts_raw,
            published_at_utc=ts_utc,
        )
        try:
            article_id = store.add_article(article, conn=conn)
        except sqlite3.IntegrityError:
            skipped += 1
            store.append(
                kinds.PUBLISH_INTENT_DEDUPED,
                {"live_url": live_url, "target_url": target_url,
                 "platform": row.get("platform")},
                target_url=target_url,
                host=host_of(live_url),
                ts_raw=ts_raw,
                ts_utc=ts_utc,
                conn=conn,
                pending_quarantines=pending_quarantines,
            )
            continue
        articles += 1
        store.append(
            kinds.PUBLISH_CONFIRMED,
            {
                "live_url": live_url,
                "target_url": target_url,
                "platform": row.get("platform"),
            },
            target_url=target_url,
            host=host_of(live_url),
            article_id=article_id,
            ts_raw=ts_raw,
            ts_utc=ts_utc,
            conn=conn,
            pending_quarantines=pending_quarantines,
        )
        events += 1
    return events, articles, skipped, False


def _emit_drafts_confirmed(
    draft_id: str,
    article_urls: list,
    language: str | None,
    target_url: str | None,
    host: str | None,
    ts_raw: str | None,
    ts_utc: str | None,
    store: EventStore,
    conn: sqlite3.Connection,
    pending_quarantines: list[dict[str, Any]],
) -> tuple[int, int, int]:
    """Emit PUBLISH_CONFIRMED event(s) for one drafts row.

    Returns (events_inserted, articles_inserted, skipped_due_to_dedup).
    """
    if not isinstance(article_urls, list) or not article_urls:
        store.append(
            kinds.PUBLISH_CONFIRMED,
            {"live_url": None, "draft_id": draft_id},
            target_url=target_url,
            host=host,
            ts_raw=ts_raw,
            ts_utc=ts_utc,
            conn=conn,
            pending_quarantines=pending_quarantines,
        )
        return 1, 0, 0

    events_inserted = 0
    articles_inserted = 0
    skipped = 0
    for live_url in article_urls:
        if not isinstance(live_url, str) or not live_url:
            continue
        article = article_payload(
            live_url=live_url,
            target_url=target_url,
            host=host_of(live_url),
            lang=language if isinstance(language, str) and language else None,
            published_at_raw=ts_raw,
            published_at_utc=ts_utc,
        )
        try:
            article_id = store.add_article(article, conn=conn)
        except sqlite3.IntegrityError:
            skipped += 1
            continue
        articles_inserted += 1
        store.append(
            kinds.PUBLISH_CONFIRMED,
            {"live_url": live_url, "draft_id": draft_id},
            target_url=target_url,
            host=host_of(live_url),
            article_id=article_id,
            ts_raw=ts_raw,
            ts_utc=ts_utc,
            conn=conn,
            pending_quarantines=pending_quarantines,
        )
        events_inserted += 1
    return events_inserted, articles_inserted, skipped
