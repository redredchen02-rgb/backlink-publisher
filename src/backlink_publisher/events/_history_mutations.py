"""Write-path mutations for publish history in events.db.

Extracted from ``history_query.py`` (Wave 3 Unit 2). Contains all functions
that mutate the ``events`` and ``articles`` tables:
``purge_failed_from_db``, ``delete_from_db``, ``bulk_delete_from_db``,
``update_status_in_db``, and the ``_STATUS_TO_KIND`` mapping they share.

W4 (soft-delete, 2026-07-06): ``delete_from_db``/``bulk_delete_from_db`` now
set ``deleted_at`` instead of physically removing rows -- the read path
(``history_query.list_history``/``get_history_item``) filters them out by
default. ``undelete_from_db`` clears ``deleted_at`` within the purge window.
Both mutators opportunistically purge rows whose ``deleted_at`` has aged past
``PURGE_WINDOW_SECONDS`` (lazy cleanup on next write -- no scheduler needed).

``history_query.py`` re-exports these names for backward compatibility.
"""

from __future__ import annotations

import json
import sqlite3

from . import kinds as _kinds
from ._store_sqlite import _now_iso_utc
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

#: How long a soft-deleted row stays visible to the WebUI's
#: ``include_deleted=window`` read path (D18) for an undo affordance. The
#: frontend's undo-toast duration (see ``frontend/src/pages/History``) is a
#: UI constant that MUST stay strictly smaller than this value.
CLIENT_UNDO_WINDOW_SECONDS = 15

#: Purge eligibility = deleted_at older than this many seconds. Deliberately
#: 2x the client's undo window: the server purge window must strictly exceed
#: the client undo window (plus network/render latency margin), or a user's
#: still-visible "撤銷" (undo) button can lose the race against the purge
#: sweep and return a 404 for a click made well within the window they were
#: shown. Named here (not inlined) so the invariant is one obvious edit, not
#: two numbers a future change could accidentally desync.
PURGE_WINDOW_SECONDS = CLIENT_UNDO_WINDOW_SECONDS * 2


def _purge_expired_rows(conn: sqlite3.Connection) -> int:
    """Physically remove rows past ``PURGE_WINDOW_SECONDS`` since soft-delete.

    Called opportunistically from the soft-delete write paths (lazy cleanup
    on next write) rather than via a scheduled job -- simplest mechanism that
    satisfies the purge-eligibility invariant. Returns rows removed.
    """
    cutoff = _cutoff_iso()
    removed = 0
    aids = [
        row[0]
        for row in conn.execute(
            "SELECT article_id FROM articles WHERE deleted_at IS NOT NULL AND deleted_at < ?",
            (cutoff,),
        ).fetchall()
    ]
    if aids:
        ph = ",".join("?" * len(aids))
        conn.execute(f"DELETE FROM events WHERE article_id IN ({ph})", aids)
        cur = conn.execute(f"DELETE FROM articles WHERE article_id IN ({ph})", aids)
        removed += cur.rowcount
    cur = conn.execute(
        "DELETE FROM events WHERE deleted_at IS NOT NULL AND deleted_at < ? "
        "AND article_id IS NULL",
        (cutoff,),
    )
    removed += cur.rowcount
    return removed


def _cutoff_iso() -> str:
    """ISO-8601 UTC timestamp ``PURGE_WINDOW_SECONDS`` in the past.

    Deleted-at values are ISO-8601 with a fixed-width ``+00:00`` offset
    (``_now_iso_utc``), so plain string comparison sorts correctly.
    """
    from datetime import datetime, timedelta, UTC

    return (datetime.now(UTC) - timedelta(seconds=PURGE_WINDOW_SECONDS)).isoformat()


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
    """Soft-delete one history item (article + linked events) in events.db.

    Sets ``deleted_at`` instead of physically removing rows -- the row stays
    undo-able until it ages past ``PURGE_WINDOW_SECONDS``, at which point it
    becomes eligible for opportunistic purge (this call also sweeps any other
    rows already past that window). Handles orphan-event IDs of the form
    ``'evt-<int>'`` (no article row). Returns True when at least one row was
    matched and marked deleted.
    """
    aid_str = str(article_id)
    s = store or _EventStore()
    now = _now_iso_utc()
    # Orphan event — no article row, only an event row (id="evt-<n>" in UI)
    if aid_str.startswith("evt-"):
        try:
            evt_id = int(aid_str[4:])
        except (ValueError, TypeError):
            return False
        with s.connect_immediate() as conn:
            cur = conn.execute(
                "UPDATE events SET deleted_at = ? WHERE id = ? AND deleted_at IS NULL",
                (now, evt_id),
            )
            _purge_expired_rows(conn)
            return cur.rowcount > 0
    try:
        aid = int(article_id)
    except (ValueError, TypeError):
        return False
    with s.connect_immediate() as conn:
        conn.execute(
            "UPDATE events SET deleted_at = ? WHERE article_id = ? AND deleted_at IS NULL",
            (now, aid),
        )
        cur = conn.execute(
            "UPDATE articles SET deleted_at = ? WHERE article_id = ? AND deleted_at IS NULL",
            (now, aid),
        )
        matched = cur.rowcount > 0
        _purge_expired_rows(conn)
        return matched


def bulk_delete_from_db(
    ids: list[str | int], store: _EventStore | None = None
) -> dict[str, int]:
    """Soft-delete multiple history items from events.db.

    Returns ``{"deleted": n, "skipped": n}`` -- ``skipped`` counts ids that
    don't parse or don't match any live (not-already-deleted) row, so a
    partially-stale bulk selection reports honestly instead of an
    all-or-nothing result.
    """
    result = {"deleted": 0, "skipped": 0}
    if not ids:
        return result
    article_ids: list[int] = []
    event_ids: list[int] = []
    for item_id in ids:
        s = str(item_id)
        if s.startswith("evt-"):
            try:
                event_ids.append(int(s[4:]))
            except (ValueError, TypeError):
                result["skipped"] += 1
        else:
            try:
                article_ids.append(int(item_id))
            except (ValueError, TypeError):
                result["skipped"] += 1
    if not article_ids and not event_ids:
        return result
    st = store or _EventStore()
    now = _now_iso_utc()
    with st.connect_immediate() as conn:
        if article_ids:
            ph = ",".join("?" * len(article_ids))
            conn.execute(
                f"UPDATE events SET deleted_at = ? WHERE article_id IN ({ph}) "
                "AND deleted_at IS NULL",
                [now, *article_ids],
            )
            cur = conn.execute(
                f"UPDATE articles SET deleted_at = ? WHERE article_id IN ({ph}) "
                "AND deleted_at IS NULL",
                [now, *article_ids],
            )
            result["deleted"] += cur.rowcount
            result["skipped"] += len(article_ids) - cur.rowcount
        if event_ids:
            ph = ",".join("?" * len(event_ids))
            cur = conn.execute(
                f"UPDATE events SET deleted_at = ? WHERE id IN ({ph}) "
                "AND deleted_at IS NULL",
                [now, *event_ids],
            )
            result["deleted"] += cur.rowcount
            result["skipped"] += len(event_ids) - cur.rowcount
        _purge_expired_rows(conn)
    return result


def undelete_from_db(article_id: int | str, store: _EventStore | None = None) -> bool:
    """Clear ``deleted_at`` for one soft-deleted history item.

    Returns True only when a currently-soft-deleted row was found and
    restored -- an id that never existed, was never deleted, or has already
    aged past the purge window (physically gone) returns False so the
    caller can surface a real 404 instead of a false success.
    """
    aid_str = str(article_id)
    s = store or _EventStore()
    if aid_str.startswith("evt-"):
        try:
            evt_id = int(aid_str[4:])
        except (ValueError, TypeError):
            return False
        with s.connect_immediate() as conn:
            _purge_expired_rows(conn)
            cur = conn.execute(
                "UPDATE events SET deleted_at = NULL WHERE id = ? AND deleted_at IS NOT NULL",
                (evt_id,),
            )
            return cur.rowcount > 0
    try:
        aid = int(article_id)
    except (ValueError, TypeError):
        return False
    with s.connect_immediate() as conn:
        _purge_expired_rows(conn)
        cur = conn.execute(
            "UPDATE articles SET deleted_at = NULL WHERE article_id = ? "
            "AND deleted_at IS NOT NULL",
            (aid,),
        )
        restored = cur.rowcount > 0
        conn.execute(
            "UPDATE events SET deleted_at = NULL WHERE article_id = ? AND deleted_at IS NOT NULL",
            (aid,),
        )
        return restored


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
