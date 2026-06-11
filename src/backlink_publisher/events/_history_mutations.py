"""Write-path mutations for publish history in events.db.

Extracted from ``history_query.py`` (Wave 3 Unit 2). Contains all functions
that mutate the ``events`` and ``articles`` tables:
``purge_failed_from_db``, ``delete_from_db``, ``bulk_delete_from_db``,
``update_status_in_db``, and the ``_STATUS_TO_KIND`` mapping they share.

``history_query.py`` re-exports these names for backward compatibility.
"""

from __future__ import annotations

import json

from . import kinds as _kinds
from .store import EventStore as _EventStore

KIND_CONFIRMED = _kinds.PUBLISH_CONFIRMED
KIND_UNVERIFIED = _kinds.PUBLISH_UNVERIFIED
KIND_FAILED = _kinds.PUBLISH_FAILED

# Maps UI status strings to the event kind stored in events.db.
_STATUS_TO_KIND: dict[str, str] = {
    "published": KIND_CONFIRMED,
    "published_unverified": KIND_UNVERIFIED,
    "drafted_unverified": KIND_UNVERIFIED,
    "failed": KIND_FAILED,
}


def purge_failed_from_db(store: _EventStore | None = None) -> int:
    """Delete all 'failed' history rows from events.db.

    Removes:
    1. Articles whose latest event is KIND_FAILED, plus their linked events.
    2. Orphan events (no article row) of kind KIND_FAILED.

    Returns the total number of rows removed (articles + orphan events).
    """
    s = store or _EventStore()
    removed = 0
    with s.connect_immediate() as conn:
        # 1. Find articles whose latest event is a publish.failed event.
        failed_article_ids = [
            row[0]
            for row in conn.execute("""
                SELECT a.article_id
                FROM articles a
                JOIN events e
                  ON e.article_id = a.article_id
                 AND e.id = (
                   SELECT MAX(e2.id) FROM events e2
                   WHERE e2.article_id = a.article_id
                 )
                WHERE e.kind = ?
            """, (KIND_FAILED,)).fetchall()
        ]
        if failed_article_ids:
            placeholders = ",".join("?" * len(failed_article_ids))
            conn.execute(
                f"DELETE FROM events WHERE article_id IN ({placeholders})",
                failed_article_ids,
            )
            cur = conn.execute(
                f"DELETE FROM articles WHERE article_id IN ({placeholders})",
                failed_article_ids,
            )
            removed += cur.rowcount

        # 2. Orphan KIND_FAILED events (no article row).
        # article_id IS NULL must be explicit — NULL NOT IN (...) is UNKNOWN in SQL.
        cur = conn.execute("""
            DELETE FROM events
            WHERE kind = ?
              AND (article_id IS NULL
                   OR article_id NOT IN (SELECT article_id FROM articles))
        """, (KIND_FAILED,))
        removed += cur.rowcount

    return removed


def delete_from_db(article_id: int | str, store: _EventStore | None = None) -> bool:
    """Delete one history item (article + linked events) from events.db.

    Handles orphan-event IDs of the form ``'evt-<int>'`` (no article row).
    Returns True when at least one row was removed.
    """
    aid_str = str(article_id)
    s = store or _EventStore()
    # Orphan event — no article row, only an event row (id="evt-<n>" in UI)
    if aid_str.startswith("evt-"):
        try:
            evt_id = int(aid_str[4:])
        except (ValueError, TypeError):
            return False
        with s.connect_immediate() as conn:
            cur = conn.execute("DELETE FROM events WHERE id = ?", (evt_id,))
            return cur.rowcount > 0
    try:
        aid = int(article_id)
    except (ValueError, TypeError):
        return False
    with s.connect_immediate() as conn:
        conn.execute("DELETE FROM events WHERE article_id = ?", (aid,))
        cur = conn.execute("DELETE FROM articles WHERE article_id = ?", (aid,))
        return cur.rowcount > 0


def bulk_delete_from_db(ids: list[str | int], store: _EventStore | None = None) -> int:
    """Delete multiple history items from events.db. Returns row count removed."""
    if not ids:
        return 0
    article_ids: list[int] = []
    event_ids: list[int] = []
    for item_id in ids:
        s = str(item_id)
        if s.startswith("evt-"):
            try:
                event_ids.append(int(s[4:]))
            except (ValueError, TypeError):
                pass
        else:
            try:
                article_ids.append(int(item_id))
            except (ValueError, TypeError):
                pass
    if not article_ids and not event_ids:
        return 0
    st = store or _EventStore()
    removed = 0
    with st.connect_immediate() as conn:
        if article_ids:
            ph = ",".join("?" * len(article_ids))
            conn.execute(f"DELETE FROM events WHERE article_id IN ({ph})", article_ids)
            cur = conn.execute(f"DELETE FROM articles WHERE article_id IN ({ph})", article_ids)
            removed += cur.rowcount
        if event_ids:
            ph = ",".join("?" * len(event_ids))
            cur = conn.execute(f"DELETE FROM events WHERE id IN ({ph})", event_ids)
            removed += cur.rowcount
    return removed


def update_status_in_db(
    article_id: int | str,
    new_status: str,
    store: _EventStore | None = None,
) -> bool:
    """Update the displayed status for one history item by mutating its latest event.

    For KIND_UNVERIFIED rows the ``ui_status`` field in ``payload_json`` carries
    the exact UI label (e.g. ``'drafted_unverified'``), so we update it together
    with ``kind``.  Returns True if the event was found and updated.
    """
    try:
        aid = int(article_id)
    except (ValueError, TypeError):
        return False
    new_kind = _STATUS_TO_KIND.get(new_status, KIND_UNVERIFIED)
    s = store or _EventStore()
    with s.connect_immediate() as conn:
        row = conn.execute(
            "SELECT id, payload_json FROM events WHERE article_id = ? ORDER BY id DESC LIMIT 1",
            (aid,),
        ).fetchone()
        if row is None:
            return False
        evt_id, payload_json = row
        payload = json.loads(payload_json) if payload_json else {}
        if new_kind == KIND_UNVERIFIED:
            payload["ui_status"] = new_status
        else:
            payload.pop("ui_status", None)
        conn.execute(
            "UPDATE events SET kind = ?, payload_json = ? WHERE id = ?",
            (new_kind, json.dumps(payload) if payload else None, evt_id),
        )
        return True
