"""Query layer for publish-related events in events.db (Plan 2026-05-28-007 U5).

Building blocks for reading publish history from events.db.  Used by the
history_store no-op shim (U6) and by direct query callers.

``list_history`` and ``get_history_item`` are the main entry points — they
reconstruct history-shaped dicts from ``events`` + ``articles`` tables.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from . import kinds as _kinds
from .store import EventStore as _EventStore

# Expose public aliases for convenience.
EventStore = _EventStore
KIND_CONFIRMED = _kinds.PUBLISH_CONFIRMED
KIND_UNVERIFIED = _kinds.PUBLISH_UNVERIFIED
KIND_FAILED = _kinds.PUBLISH_FAILED


# ── helpers ────────────────────────────────────────────────────────────────


KIND_RECHECKED = _kinds.LINK_RECHECKED

#: The closed set of per-target dofollow badge values. Distinct from the
#: page-wide publish status: this is the *operator's own required link* truth.
TARGET_DOFOLLOW = "dofollow"
TARGET_DOFOLLOW_LOST = "dofollow_lost"
TARGET_STRIPPED = "stripped"
TARGET_UNVERIFIED = "unverified"


def _status_from_kind(kind: str | None) -> str:
    """Derive a ``history_store``-style status string from an event kind."""
    if kind in (KIND_CONFIRMED, KIND_UNVERIFIED):
        return "published"
    if kind == KIND_FAILED:
        return "failed"
    return "unknown"


def derive_target_dofollow(verdict: str | None, expected_nofollow: bool = False) -> str:
    """Map a latest ``link.rechecked`` verdict to the per-target dofollow badge.

    The probe already cross-checks the channel manifest (``dofollow_lost`` is
    only emitted when ``dofollow_status(platform) is True``), so an
    expected-nofollow channel arrives here as ``alive`` + ``expected_nofollow``
    — which must read **neutral "unverified"**, never a ``dofollow_lost`` alarm.
    No signal (legacy rows / probe_error) is "unverified", never green/red.
    """
    from backlink_publisher.recheck import verdicts

    if verdict is None:
        return TARGET_UNVERIFIED
    if verdict == verdicts.ALIVE:
        return TARGET_UNVERIFIED if expected_nofollow else TARGET_DOFOLLOW
    if verdict == verdicts.DOFOLLOW_LOST:
        return TARGET_DOFOLLOW_LOST
    if verdict in (verdicts.LINK_STRIPPED, verdicts.HOST_GONE):
        return TARGET_STRIPPED
    # probe_error and anything indeterminate → no confident truth.
    return TARGET_UNVERIFIED


# Private alias used by tests (verdict-only, no expected_nofollow path).
_verdict_to_target_dofollow = derive_target_dofollow


def _latest_verdicts(conn: sqlite3.Connection) -> dict[int, tuple[str | None, bool]]:
    """Return ``{article_id: (latest_verdict, expected_nofollow)}`` from the
    ``link.rechecked`` time series (latest id wins per article).

    Uses SQL GROUP BY to deduplicate in-database instead of loading all events.
    """
    rows = conn.execute(
        "SELECT article_id, payload_json FROM events "
        "WHERE kind = ? AND article_id IS NOT NULL "
        "AND id IN (SELECT MAX(id) FROM events WHERE kind = ? AND article_id IS NOT NULL GROUP BY article_id)",
        (KIND_RECHECKED, KIND_RECHECKED),
    ).fetchall()
    out: dict[int, tuple[str | None, bool]] = {}
    for aid, payload_json in rows:
        try:
            payload = json.loads(payload_json) if payload_json else {}
        except (ValueError, TypeError):
            payload = {}
        out[aid] = (payload.get("verdict"), bool(payload.get("expected_nofollow")))
    return out


# ── history-shaped read API ────────────────────────────────────────────────


def _apply_target_dofollow(
    item: dict[str, Any],
    article_id: int,
    verdict_map: dict[int, tuple[str | None, bool]] | None,
) -> None:
    """Set ``item['target_dofollow']`` from the latest verdict for *article_id*
    (no-op when no verdict map / no entry — the default stays 'unverified')."""
    if not verdict_map or article_id not in verdict_map:
        return
    verdict, expected_nofollow = verdict_map[article_id]
    item["target_dofollow"] = derive_target_dofollow(verdict, expected_nofollow)


def _apply_article_fields(
    item: dict[str, Any],
    article_row: tuple,
    verdict_map: dict[int, tuple[str | None, bool]] | None,
) -> None:
    """Populate ``item`` from an article row (see ``_build_history_item``)."""
    (
        art_id,
        _body,
        _anchors,
        _tgt_urls_json,
        lang,
        _host,
        live_url,
        _pub_raw,
        pub_utc,
        run_id,
        platform,
        verified_at,
        verify_error,
        _dedup_key,
    ) = article_row
    item["id"] = str(art_id)
    _apply_target_dofollow(item, art_id, verdict_map)
    item["created_at"] = pub_utc or ""
    item["platform"] = platform or ""
    item["language"] = lang or ""
    item["run_id"] = run_id or ""
    item["verified_at"] = verified_at
    item["verify_error"] = verify_error or ""
    if live_url:
        item["article_urls"] = [live_url]


def _apply_event_fields(item: dict[str, Any], event_row: tuple) -> None:
    """Populate ``item`` from an event row (see ``_build_history_item``)."""
    (
        evt_id,
        ts_utc,
        _ts_raw,
        evt_run_id,
        kind,
        target_url,
        _host_evt,
        _art_id_evt,
        payload_json,
    ) = event_row
    item["id"] = item["id"] or f"evt-{evt_id}"
    item["target_url"] = target_url or item["target_url"]
    item["status"] = _status_from_kind(kind)
    if not item["created_at"] and ts_utc:
        item["created_at"] = ts_utc
    if not item["run_id"] and evt_run_id:
        item["run_id"] = evt_run_id
    if kind == KIND_FAILED:
        payload = json.loads(payload_json) if payload_json else {}
        error_msg = (
            payload.get("error_message_clean")
            or payload.get("error_class")
            or ""
        )
        item["error"] = error_msg
        if payload.get("error_class"):
            item["error_class"] = payload["error_class"]
        if not item["platform"]:
            item["platform"] = payload.get("platform", "")
    elif kind in (KIND_CONFIRMED, KIND_UNVERIFIED):
        payload = json.loads(payload_json) if payload_json else {}
        live = payload.get("live_url")
        if live:
            item["article_urls"] = [live]
        if not item["platform"]:
            item["platform"] = payload.get("platform", "")
        title = payload.get("title") or ""
        if title:
            item["title"] = title
        if kind == KIND_UNVERIFIED:
            item["status"] = payload.get("ui_status") or "published_unverified"
        else:
            item["status"] = "published"
        if payload.get("adapter"):
            item["adapter"] = payload["adapter"]


def _build_history_item(
    article_row: tuple | None,
    event_row: tuple | None,
    verdict_map: dict[int, tuple[str | None, bool]] | None = None,
) -> dict[str, Any]:
    """Reconstruct a history-shaped dict from optional article + event rows.

    Returns a dict with keys compatible with the WebUI templates
    (``_tab_history.html``) and ``HistoryAPI._normalize_item``.

    ``verdict_map`` (``{article_id: (verdict, expected_nofollow)}``) joins the
    latest per-target ``link.rechecked`` verdict into ``item['target_dofollow']``.
    """
    item: dict[str, Any] = {
        "id": "",
        "target_url": "",
        "created_at": "",
        "platform": "",
        "status": "unknown",
        "article_urls": [],
        "run_id": "",
        "language": "",
        "error": "",
        "verified_at": None,
        "publish_mode": "draft",
        # Operator-link dofollow truth (distinct from page-wide status). The
        # no-signal default is centralised in HistoryAPI._normalize_item too.
        "target_dofollow": TARGET_UNVERIFIED,
    }

    # ── article fields ────────────────────────────────────────────────
    if article_row is not None:
        _apply_article_fields(item, article_row, verdict_map)

    # ── event fields ──────────────────────────────────────────────────
    if event_row is not None:
        _apply_event_fields(item, event_row)

    return item


# ── public query functions ─────────────────────────────────────────────────


def _deleted_at_cutoff_iso() -> str:
    """ISO-8601 UTC cutoff for the ``include_deleted=window`` read path (D18).

    Shares the purge-window constant with the write path so a row that's
    still returned here is, by construction, not yet purge-eligible.
    """
    from datetime import datetime, timedelta, UTC

    from ._history_mutations import PURGE_WINDOW_SECONDS

    return (datetime.now(UTC) - timedelta(seconds=PURGE_WINDOW_SECONDS)).isoformat()


def list_history(
    store: _EventStore | None = None,
    limit: int = 500,
    include_deleted: str | None = None,
) -> list[dict[str, Any]]:
    """Return history-shaped dicts from events.db, newest-first.

    Combines articles (with their latest event for status) and orphan
    events (failed-only items that never created an article).

    Each dict has the same keys that ``_tab_history.html`` expects:
    ``id``, ``target_url``, ``created_at``, ``platform``, ``status``,
    ``article_urls``, ``run_id``, ``language``, ``error``, ``verified_at``,
    ``publish_mode``.

    ``include_deleted`` (W4/D18): ``None`` (default) filters out
    soft-deleted rows -- this is the invariant every CLI read path relies
    on implicitly by never passing the parameter. The only other
    recognised value is ``"window"``, which flips the query to return
    *only* rows soft-deleted within the undo window (``deleted_at``
    populated on each item, for the WebUI's undo affordance). Any other
    value is a caller bug, not a value to silently ignore.
    """
    if include_deleted not in (None, "window"):
        raise ValueError(f"include_deleted must be None or 'window', got {include_deleted!r}")
    window_only = include_deleted == "window"
    s = store or _EventStore()
    out: list[dict[str, Any]] = []

    if window_only:
        article_filter = "a.deleted_at IS NOT NULL AND a.deleted_at >= ?"
        article_params: tuple[Any, ...] = (_deleted_at_cutoff_iso(),)
    else:
        article_filter = "a.deleted_at IS NULL"
        article_params = ()

    with s.connect() as conn:
        # 1. Articles with their latest event (for status derivation).
        # Use a subquery to find the latest event ID per article upfront,
        # avoiding the correlated subquery that ran O(N*M) on large datasets.
        rows = conn.execute(f"""
            SELECT
              a.article_id, a.body, a.anchors_json, a.target_urls_json,
              a.lang, a.host, a.live_url, a.published_at_raw,
              a.published_at_utc, a.run_id, a.platform,
              a.verified_at, a.verify_error, a.migration_dedup_key,
              e.id, e.ts_utc, e.ts_raw, e.run_id, e.kind,
              e.target_url, e.host, e.article_id, e.payload_json,
              a.deleted_at
            FROM articles a
            LEFT JOIN events e
              ON e.id = (
                SELECT e2.id FROM events e2
                WHERE e2.article_id = a.article_id
                  -- Display status derives from the latest PUBLISH event, not the
                  -- latest event of any kind: a keep-alive link.rechecked shares the
                  -- article_id and would otherwise become 'newest' and flip status to
                  -- 'unknown' (audit finding [19]). Recheck verdicts are joined
                  -- separately via _latest_verdicts for the dofollow badge.
                  AND e2.kind IN (?, ?, ?)
                ORDER BY e2.id DESC LIMIT 1
              )
            WHERE {article_filter}
            ORDER BY a.published_at_utc DESC
            LIMIT ?
        """, (KIND_CONFIRMED, KIND_UNVERIFIED, KIND_FAILED, *article_params, limit)).fetchall()
        verdict_map = _latest_verdicts(conn)

    for row in rows:
        # Split the wide row into article (cols 0-13), event (cols 14-22),
        # and the trailing deleted_at column.
        article_cols = row[:14]
        event_cols = row[14:23]
        deleted_at = row[23]
        # If there's no matching event, event_cols will be all-None.
        has_event = event_cols[0] is not None
        item = _build_history_item(
            article_cols,
            event_cols if has_event else None,
            verdict_map,
        )
        if window_only:
            item["deleted_at"] = deleted_at
        out.append(item)

    # 2. Orphan events — publish failed before an article row was created.
    if window_only:
        orphan_filter = "e.deleted_at IS NOT NULL AND e.deleted_at >= ?"
        orphan_params: tuple[Any, ...] = (_deleted_at_cutoff_iso(),)
    else:
        orphan_filter = "e.deleted_at IS NULL"
        orphan_params = ()

    with s.connect() as conn:
        orphans = conn.execute(f"""
            SELECT e.id, e.ts_utc, e.ts_raw, e.run_id, e.kind,
                   e.target_url, e.host, e.article_id, e.payload_json,
                   e.deleted_at
            FROM events e
            LEFT JOIN articles a ON a.article_id = e.article_id
            WHERE a.article_id IS NULL
              AND e.kind IN (?, ?, ?)
              AND {orphan_filter}
            ORDER BY e.id DESC
            LIMIT ?
        """, (KIND_CONFIRMED, KIND_UNVERIFIED, KIND_FAILED, *orphan_params, limit)).fetchall()

    for orow in orphans:
        item = _build_history_item(None, orow[:9])
        if window_only:
            item["deleted_at"] = orow[9]
        out.append(item)

    # Sort combined list by created_at desc, then id desc.
    out.sort(key=lambda i: (i.get("created_at") or "", str(i.get("id", ""))), reverse=True)
    return out[:limit]


def get_history_item(
    article_id: int | str,
    store: _EventStore | None = None,
) -> dict[str, Any] | None:
    """Look up a single history-shaped dict by ``article_id``.

    Accepts both ``int`` and ``str`` (parsed to int).
    Returns ``None`` if the article does not exist.
    """
    try:
        aid = int(article_id)
    except (ValueError, TypeError):
        return None

    s = store or _EventStore()
    with s.connect() as conn:
        row = conn.execute("""
            SELECT
              a.article_id, a.body, a.anchors_json, a.target_urls_json,
              a.lang, a.host, a.live_url, a.published_at_raw,
              a.published_at_utc, a.run_id, a.platform,
              a.verified_at, a.verify_error, a.migration_dedup_key,
              e.id, e.ts_utc, e.ts_raw, e.run_id, e.kind,
              e.target_url, e.host, e.article_id, e.payload_json
            FROM articles a
            LEFT JOIN events e
              ON e.article_id = a.article_id
             AND e.id = (
               SELECT MAX(e2.id) FROM events e2
               WHERE e2.article_id = a.article_id
                 -- Latest PUBLISH event only; a link.rechecked must not hijack the
                 -- displayed status to 'unknown' (audit finding [19]).
                 AND e2.kind IN (?, ?, ?)
             )
            WHERE a.article_id = ? AND a.deleted_at IS NULL
        """, (KIND_CONFIRMED, KIND_UNVERIFIED, KIND_FAILED, aid)).fetchone()
        verdict_map = _latest_verdicts(conn) if row is not None else None

    if row is None:
        return None

    article_cols = row[:14]
    event_cols = row[14:]
    has_event = event_cols[0] is not None
    return _build_history_item(article_cols, event_cols if has_event else None, verdict_map)


# ── write-path mutations (re-exported for backward compatibility) ───────────
# Actual implementations live in _history_mutations.py.

from ._history_mutations import (  # noqa: E402
    _STATUS_TO_KIND,
    bulk_delete_from_db,
    CLIENT_UNDO_WINDOW_SECONDS,
    delete_from_db,
    purge_failed_from_db,
    PURGE_WINDOW_SECONDS,
    undelete_from_db,
    update_status_in_db,
)

__all__ = [
    "purge_failed_from_db",
    "delete_from_db",
    "bulk_delete_from_db",
    "undelete_from_db",
    "_STATUS_TO_KIND",
    "update_status_in_db",
    "CLIENT_UNDO_WINDOW_SECONDS",
    "PURGE_WINDOW_SECONDS",
]


def get_article_by_live_url(live_url: str) -> dict[str, Any] | None:
    """Look up an article row by its ``live_url``."""
    store = _EventStore()
    with store.connect() as conn:
        row = conn.execute(
            "SELECT article_id, body, anchors_json, target_urls_json, "
            "lang, host, live_url, published_at_raw, published_at_utc, "
            "run_id, platform, verified_at, verify_error, "
            "migration_dedup_key "
            "FROM articles WHERE live_url = ?",
            (live_url,),
        ).fetchone()
    if row is None:
        return None
    return {
        "article_id": row[0],
        "body": row[1],
        "anchors_json": row[2],
        "target_urls_json": row[3],
        "lang": row[4],
        "host": row[5],
        "live_url": row[6],
        "published_at_raw": row[7],
        "published_at_utc": row[8],
        "run_id": row[9],
        "platform": row[10],
        "verified_at": row[11],
        "verify_error": row[12],
        "migration_dedup_key": row[13],
    }


def latest_publish_timestamp(
    store: _EventStore | None = None,
) -> str | None:
    """Return the most recent ``created_at`` timestamp from published/drafted articles.

    Uses SQL ``MAX()`` instead of loading all rows — O(1) vs O(N).
    Returns ``None`` when no published/drafted articles exist.
    """
    s = store or _EventStore()
    with s.connect() as conn:
        row = conn.execute(
            "SELECT MAX(published_at_utc) FROM articles "
            "WHERE published_at_utc IS NOT NULL AND published_at_utc != ''"
        ).fetchone()
    return row[0] if row and row[0] else None
