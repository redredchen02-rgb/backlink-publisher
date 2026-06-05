"""Query layer for publish-related events in events.db (Plan 2026-05-28-007 U5).

Building blocks for reading publish history from events.db.  Used by the
history_store no-op shim (U6) and by direct query callers.

``list_history`` and ``get_history_item`` are the main entry points — they
reconstruct history-shaped dicts from ``events`` + ``articles`` tables.
"""

from __future__ import annotations

import json
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


def _latest_verdicts(conn) -> dict[int, tuple[str | None, bool]]:
    """Return ``{article_id: (latest_verdict, expected_nofollow)}`` from the
    ``link.rechecked`` time series (latest id wins per article)."""
    rows = conn.execute(
        "SELECT article_id, payload_json FROM events "
        "WHERE kind = ? AND article_id IS NOT NULL ORDER BY id",
        (KIND_RECHECKED,),
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

    # ── event fields ──────────────────────────────────────────────────
    if event_row is not None:
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
            # If there's no article, use payload for platform
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
                # Prefer the original ui_status from the payload to distinguish
                # "drafted_unverified" from "published_unverified" — older rows
                # without this key fall back to "published_unverified".
                item["status"] = payload.get("ui_status") or "published_unverified"
            else:
                item["status"] = "published"

    return item


# ── public query functions ─────────────────────────────────────────────────


def list_history(
    store: _EventStore | None = None,
    limit: int = 500,
) -> list[dict[str, Any]]:
    """Return history-shaped dicts from events.db, newest-first.

    Combines articles (with their latest event for status) and orphan
    events (failed-only items that never created an article).

    Each dict has the same keys that ``_tab_history.html`` expects:
    ``id``, ``target_url``, ``created_at``, ``platform``, ``status``,
    ``article_urls``, ``run_id``, ``language``, ``error``, ``verified_at``,
    ``publish_mode``.
    """
    s = store or _EventStore()
    out: list[dict[str, Any]] = []

    with s.connect() as conn:
        # 1. Articles with their latest event (for status derivation).
        rows = conn.execute("""
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
             )
            ORDER BY a.published_at_utc DESC
            LIMIT ?
        """, (limit,)).fetchall()
        verdict_map = _latest_verdicts(conn)

    for row in rows:
        # Split the wide row into article (cols 0-13) and event (cols 14-22) halves.
        article_cols = row[:14]
        event_cols = row[14:]
        # If there's no matching event, event_cols will be all-None.
        has_event = event_cols[0] is not None
        out.append(_build_history_item(
            article_cols,
            event_cols if has_event else None,
            verdict_map,
        ))

    # 2. Orphan events — publish failed before an article row was created.
    with s.connect() as conn:
        orphans = conn.execute("""
            SELECT e.id, e.ts_utc, e.ts_raw, e.run_id, e.kind,
                   e.target_url, e.host, e.article_id, e.payload_json
            FROM events e
            LEFT JOIN articles a ON a.article_id = e.article_id
            WHERE a.article_id IS NULL
              AND e.kind IN (?, ?, ?)
            ORDER BY e.id DESC
            LIMIT ?
        """, (KIND_CONFIRMED, KIND_UNVERIFIED, KIND_FAILED, limit)).fetchall()

    for orow in orphans:
        out.append(_build_history_item(None, orow))

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
             )
            WHERE a.article_id = ?
        """, (aid,)).fetchone()
        verdict_map = _latest_verdicts(conn) if row is not None else None

    if row is None:
        return None

    article_cols = row[:14]
    event_cols = row[14:]
    has_event = event_cols[0] is not None
    return _build_history_item(article_cols, event_cols if has_event else None, verdict_map)


# ── low-level event query helpers ──────────────────────────────────────────


def _event_row_to_dict(row: tuple) -> dict[str, Any]:
    """Convert a raw events row tuple to a dict with parsed payload."""
    return {
        "id": row[0],
        "ts_raw": row[1],
        "ts_utc": row[2],
        "run_id": row[3],
        "kind": row[4],
        "target_url": row[5],
        "host": row[6],
        "article_id": row[7],
        "payload": json.loads(row[8]) if row[8] else {},
    }


def list_events(
    *,
    kind: str | None = None,
    target_url: str | None = None,
    host: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """List raw events, optionally filtered by kind / target_url / host.

    Results are newest-first, capped at ``limit``.
    """
    store = _EventStore()
    clauses: list[str] = []
    params: list[Any] = []
    if kind is not None:
        clauses.append("kind = ?")
        params.append(kind)
    if target_url is not None:
        clauses.append("target_url = ?")
        params.append(target_url)
    if host is not None:
        clauses.append("host = ?")
        params.append(host)
    where = " AND ".join(clauses) if clauses else "1"
    sql = (
        f"SELECT id, ts_raw, ts_utc, run_id, kind, target_url, host, "
        f"article_id, payload_json FROM events WHERE {where} "
        f"ORDER BY id DESC LIMIT ?"
    )
    params.append(limit)
    with store.connect() as conn:
        return [_event_row_to_dict(r) for r in conn.execute(sql, params).fetchall()]


def list_publish_events(
    *,
    target_url: str | None = None,
    host: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """List publish-related events only (confirmed / unverified / failed)."""
    store = _EventStore()
    clauses: list[str] = [
        "kind IN (?, ?, ?)",
    ]
    params: list[Any] = [
        KIND_CONFIRMED,
        KIND_UNVERIFIED,
        KIND_FAILED,
    ]
    if target_url is not None:
        clauses.append("target_url = ?")
        params.append(target_url)
    if host is not None:
        clauses.append("host = ?")
        params.append(host)
    where = " AND ".join(clauses)
    sql = (
        f"SELECT id, ts_raw, ts_utc, run_id, kind, target_url, host, "
        f"article_id, payload_json FROM events WHERE {where} "
        f"ORDER BY id DESC LIMIT ?"
    )
    params.append(limit)
    with store.connect() as conn:
        return [_event_row_to_dict(r) for r in conn.execute(sql, params).fetchall()]


def count_publish_events() -> int:
    """Return the total number of publish-related events in events.db."""
    store = _EventStore()
    with store.connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM events WHERE kind IN (?, ?, ?)",
            (KIND_CONFIRMED, KIND_UNVERIFIED, KIND_FAILED),
        ).fetchone()
        return row[0] if row else 0


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
