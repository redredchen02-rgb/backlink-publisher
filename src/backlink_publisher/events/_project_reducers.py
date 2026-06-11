"""Reducer functions for ``events.projector`` — one per JSON source type.

Each reducer diffs a JSON state file (checkpoint / history / drafts) against
the per-source cursor in ``projection_cursor`` and emits events + articles
rows for the new state. All three share the same signature::

    (path: Path, store: EventStore) -> ProjectionResult
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ._project_helpers import (
    ProjectionError,
    article_payload,
    checkpoint_event_timestamp,
    cursor_load,
    cursor_save,
    extract_anchors,
    host_of,
    read_json,
    split_iso_with_offset,
    split_local_naive,
    write_quarantines,
)
from .._util.url import canonicalize_url
from . import kinds
from .scrubber import scrub_text
from .store import EventStore


@dataclass(frozen=True)
class ProjectionResult:
    """Counts returned from a single ``flush_for`` call."""

    events_inserted: int = 0
    articles_inserted: int = 0
    skipped_due_to_dedup: int = 0
    cursor_updated: bool = False
    quarantined: int = 0
    records_considered: int = 0


# ── Checkpoint reducer ────────────────────────────────────────────


def _project_checkpoint(path: Path, store: EventStore) -> ProjectionResult:
    """Diff a checkpoint file against the cursor and emit events."""
    source = str(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ProjectionError(f"checkpoint payload not an object: {path}")

    run_id = data.get("run_id")
    if not isinstance(run_id, str) or not run_id:
        raise ProjectionError(f"checkpoint missing run_id: {path}")
    started_at = data.get("started_at") or ""
    items = data.get("items") or []

    events_inserted = 0
    articles_inserted = 0
    skipped_due_to_dedup = 0
    records_considered = 0
    seen_intent_or_failed: set[tuple[str, str, str]] = set()
    pending_quarantines: list[dict[str, Any]] = []

    with store.connect() as conn:
        prior = cursor_load(conn, source)
        prior_items: dict[str, dict[str, Any]] = prior.get("items", {})
        next_items: dict[str, dict[str, Any]] = {}

        for item in items:
            if not isinstance(item, dict):
                continue
            item_id = item.get("id")
            status = item.get("status")
            if not isinstance(item_id, str) or not isinstance(status, str):
                continue
            records_considered += 1

            published_url = item.get("published_url") or None
            target_url = (item.get("payload") or {}).get("target_url") or None
            host = host_of(target_url)
            ts_raw, ts_utc = checkpoint_event_timestamp(item, started_at)

            next_items[item_id] = {
                "status": status,
                "published_url": published_url,
            }
            prior_state = prior_items.get(item_id)
            if prior_state == next_items[item_id]:
                continue

            outcome = kinds.classify("checkpoint", status)

            if outcome is kinds.PUBLISH_INTENT:
                if _handle_checkpoint_intent(
                    item, run_id, target_url, host, ts_raw, ts_utc,
                    prior_state, seen_intent_or_failed, conn,
                    pending_quarantines, store,
                ):
                    events_inserted += 1

            elif outcome is kinds.CONFIRMED_FAMILY:
                articles, events = _handle_checkpoint_confirmed(
                    item, run_id, published_url, target_url, host,
                    ts_raw, ts_utc, conn, pending_quarantines, store,
                )
                articles_inserted += articles
                events_inserted += events
                if articles == 0 and events == 0:
                    skipped_due_to_dedup += 1

            elif outcome is kinds.PUBLISH_FAILED:
                if _handle_checkpoint_failed(
                    item, run_id, target_url, host, ts_raw, ts_utc,
                    seen_intent_or_failed, conn,
                    pending_quarantines, store,
                ):
                    events_inserted += 1

            elif outcome is kinds.NO_EMIT:
                pass

            else:
                _handle_checkpoint_unmapped(item, pending_quarantines)

        cursor_save(
            conn,
            source,
            {"items": next_items},
            mtime=path.stat().st_mtime,
        )

    events_inserted -= sum(
        1 for q in pending_quarantines if q.get("failure_type") == "missing_field"
    )
    write_quarantines(store, pending_quarantines)

    return ProjectionResult(
        events_inserted=events_inserted,
        articles_inserted=articles_inserted,
        skipped_due_to_dedup=skipped_due_to_dedup,
        cursor_updated=True,
        quarantined=len(pending_quarantines),
        records_considered=records_considered,
    )


# ── Checkpoint outcome handlers (extracted 2026-06-03, CC 39→25) ──


def _handle_checkpoint_intent(
    item: dict[str, Any],
    run_id: str,
    target_url: str | None,
    host: str | None,
    ts_raw: str,
    ts_utc: str | None,
    prior_state: dict[str, Any] | None,
    seen_intent_or_failed: set[tuple[str, str, str]],
    conn: sqlite3.Connection,
    pending_quarantines: list[dict[str, Any]],
    store: EventStore,
) -> bool:
    """Handle a PUBLISH_INTENT checkpoint row.

    Returns ``True`` when an event was appended, ``False`` when skipped
    (previously seen or already in prior state).
    """
    if prior_state is not None:
        return False
    dedup_key = (run_id, target_url or "", kinds.PUBLISH_INTENT)
    if dedup_key in seen_intent_or_failed:
        return False
    seen_intent_or_failed.add(dedup_key)
    store.append(
        kinds.PUBLISH_INTENT,
        {
            "target_url": target_url,
            "title": item.get("title"),
            "platform": item.get("adapter"),
        },
        run_id=run_id,
        target_url=target_url,
        host=host,
        ts_raw=ts_raw,
        ts_utc=ts_utc,
        conn=conn,
        pending_quarantines=pending_quarantines,
    )
    return True


def _handle_checkpoint_confirmed(
    item: dict[str, Any],
    run_id: str,
    published_url: str | None,
    target_url: str | None,
    host: str | None,
    ts_raw: str,
    ts_utc: str | None,
    conn: sqlite3.Connection,
    pending_quarantines: list[dict[str, Any]],
    store: EventStore,
) -> tuple[int, int]:
    """Handle a CONFIRMED_FAMILY checkpoint row.

    Returns ``(articles_inserted, events_inserted)`` for this row.
    ``articles_inserted`` is 0 when the article was already known
    (``sqlite3.IntegrityError`` dedup).
    """
    live_host = host_of(published_url) or host
    payload = item.get("payload") or {}
    _body = payload.get("content_markdown") if isinstance(payload, dict) else None
    _anchors = extract_anchors(payload)
    _completed_at = item.get("completed_at")
    if isinstance(_completed_at, str) and _completed_at:
        try:
            _pub_raw, _pub_utc = split_iso_with_offset(_completed_at)
        except ValueError:
            _pub_raw, _pub_utc = _completed_at, None
    else:
        _pub_raw, _pub_utc = None, None
    _lang = payload.get("lang") if isinstance(payload, dict) else None
    art = article_payload(
        live_url=published_url,
        target_url=target_url,
        host=live_host,
        anchors_json=json.dumps(_anchors, sort_keys=True, ensure_ascii=False),
        run_id=run_id,
        body=_body,
        lang=_lang if isinstance(_lang, str) and _lang else None,
        published_at_raw=_pub_raw,
        published_at_utc=_pub_utc,
    )
    try:
        article_id = store.add_article(art, conn=conn)
    except sqlite3.IntegrityError:
        # Duplicate article (live_url UNIQUE collision): emit a reconcile.swallowed
        # event so the equity ledger can account for the drop instead of losing
        # it silently in the int counter.
        store.append(
            kinds.RECONCILE_SWALLOWED,
            {"live_url": published_url, "target_url": target_url},
            run_id=run_id,
            target_url=target_url,
            host=live_host,
            ts_raw=ts_raw,
            ts_utc=ts_utc,
            conn=conn,
        )
        return (0, 1)
    _verified = item.get("verified", True)
    _kind = kinds.PUBLISH_CONFIRMED if _verified else kinds.PUBLISH_UNVERIFIED
    store.append(
        _kind,
        {
            "live_url": published_url,
            "target_url": target_url,
            "live_url_canonical": (
                canonicalize_url(published_url)
                if published_url
                else None
            ),
            "platform": item.get("adapter"),
        },
        run_id=run_id,
        target_url=target_url,
        host=live_host,
        article_id=article_id,
        ts_raw=ts_raw,
        ts_utc=ts_utc,
        conn=conn,
        pending_quarantines=pending_quarantines,
    )
    return (1, 1)


def _handle_checkpoint_failed(
    item: dict[str, Any],
    run_id: str,
    target_url: str | None,
    host: str | None,
    ts_raw: str,
    ts_utc: str | None,
    seen_intent_or_failed: set[tuple[str, str, str]],
    conn: sqlite3.Connection,
    pending_quarantines: list[dict[str, Any]],
    store: EventStore,
) -> bool:
    """Handle a PUBLISH_FAILED checkpoint row.

    Returns ``True`` when an event was appended, ``False`` when skipped
    (already seen).
    """
    dedup_key = (run_id, target_url or "", kinds.PUBLISH_FAILED)
    if dedup_key in seen_intent_or_failed:
        return False
    seen_intent_or_failed.add(dedup_key)
    error_class = item.get("error_class")
    error_message = item.get("error") or ""
    cleaned, hits = scrub_text(error_message)
    store.append(
        kinds.PUBLISH_FAILED,
        {
            "error_class": error_class,
            "error_message_clean": cleaned,
            "scrub_hits": hits or {},
            "platform": item.get("adapter"),
        },
        run_id=run_id,
        target_url=target_url,
        host=host,
        ts_raw=ts_raw,
        ts_utc=ts_utc,
        conn=conn,
        pending_quarantines=pending_quarantines,
    )
    return True


def _handle_checkpoint_unmapped(
    item: dict[str, Any],
    pending_quarantines: list[dict[str, Any]],
) -> None:
    """Handle an unmapped checkpoint status — appends a quarantine entry."""
    target_url = (item.get("payload") or {}).get("target_url") or None
    item_id = item.get("id", "")
    status = item.get("status", "")
    pending_quarantines.append(
        {
            "reason": f"unmapped_status: checkpoint/{status}",
            "failure_type": "unmapped_status",
            "source": "checkpoint",
            "run_id": "",
            "source_status": status,
            "record_identity": item_id,
            "raw_payload": {"target_url": target_url, "adapter": item.get("adapter")},
        }
    )


# ── History reducer helpers ───────────────────────────────────────


from ._project_emit import (  # noqa: F401 — re-export for callers
    _emit_confirmed_history_row,
    _emit_drafts_confirmed,
    _parse_row_timestamps,
)


def _project_history(
    path: Path,
    store: EventStore,
) -> ProjectionResult:
    """Append-only history list: diff by ``id``, emit per row."""
    source = str(path)
    rows = read_json(path)
    if rows is None:
        return ProjectionResult()
    if not isinstance(rows, list):
        raise ProjectionError(f"history payload not a list: {path}")

    events_inserted = 0
    articles_inserted = 0
    skipped_due_to_dedup = 0
    records_considered = 0
    pending_quarantines: list[dict[str, Any]] = []

    with store.connect() as conn:
        prior = cursor_load(conn, source)
        seen_ids: set[str] = set(prior.get("seen_ids") or [])
        next_seen: list[str] = list(seen_ids)

        for row in rows:
            if not isinstance(row, dict):
                continue
            row_id = row.get("id")
            if not isinstance(row_id, str) or not row_id:
                continue
            if row_id in seen_ids:
                continue
            records_considered += 1

            status = row.get("status")
            target_url = row.get("target_url")
            host = host_of(target_url) if isinstance(target_url, str) else None
            created_at = row.get("created_at") or ""
            ts_raw, ts_utc = _parse_row_timestamps(created_at)

            article_urls = row.get("article_urls") or []
            language = row.get("language") if isinstance(row.get("language"), str) else None

            outcome = kinds.classify("history", status)
            if outcome is kinds.PUBLISH_CONFIRMED:
                ev, art, sk, always_mark = _emit_confirmed_history_row(
                    row, article_urls, target_url, host, language,
                    ts_raw, ts_utc, store, conn, pending_quarantines,
                )
                events_inserted += ev
                articles_inserted += art
                skipped_due_to_dedup += sk
                if always_mark or ev or skipped_due_to_dedup:
                    next_seen.append(row_id)
                    seen_ids.add(row_id)

            elif outcome is kinds.PUBLISH_FAILED:
                error = row.get("error") or ""
                cleaned, hits = scrub_text(error)
                store.append(
                    kinds.PUBLISH_FAILED,
                    {
                        "error_class": row.get("error_class"),
                        "error_message_clean": cleaned,
                        "scrub_hits": hits or {},
                        "platform": row.get("platform"),
                    },
                    target_url=target_url,
                    host=host,
                    ts_raw=ts_raw,
                    ts_utc=ts_utc,
                    conn=conn,
                    pending_quarantines=pending_quarantines,
                )
                events_inserted += 1
                next_seen.append(row_id)
                seen_ids.add(row_id)
            else:
                next_seen.append(row_id)
                seen_ids.add(row_id)

        cursor_save(
            conn,
            source,
            {"seen_ids": next_seen},
            mtime=path.stat().st_mtime,
        )

    events_inserted -= sum(
        1 for q in pending_quarantines if q.get("failure_type") == "missing_field"
    )
    write_quarantines(store, pending_quarantines)

    return ProjectionResult(
        events_inserted=events_inserted,
        articles_inserted=articles_inserted,
        skipped_due_to_dedup=skipped_due_to_dedup,
        cursor_updated=True,
        quarantined=len(pending_quarantines),
        records_considered=records_considered,
    )


# ── Drafts reducer ────────────────────────────────────────────────


def _project_drafts(path: Path, store: EventStore) -> ProjectionResult:
    """Per-draft state machine — see ``plan §U4 Design notes``."""
    source = str(path)
    rows = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise ProjectionError(f"drafts payload not a list: {path}")

    events_inserted = 0
    articles_inserted = 0
    skipped_due_to_dedup = 0
    records_considered = 0
    pending_quarantines: list[dict[str, Any]] = []

    with store.connect() as conn:
        prior = cursor_load(conn, source)
        prior_items: dict[str, str] = prior.get("items", {})
        next_items: dict[str, str] = {}

        for row in rows:
            if not isinstance(row, dict):
                continue
            draft_id = row.get("id")
            status = row.get("status")
            if not isinstance(draft_id, str) or not isinstance(status, str):
                continue
            next_items[draft_id] = status

            prior_status = prior_items.get(draft_id)
            if prior_status == status:
                continue
            records_considered += 1

            target_url = row.get("target_url")
            host = host_of(target_url) if isinstance(target_url, str) else None
            published_at = row.get("published_at")
            try:
                ts_raw, ts_utc = (
                    split_local_naive(published_at)
                    if isinstance(published_at, str) and published_at
                    else (None, None)
                )
            except ValueError:
                ts_raw, ts_utc = published_at, None

            outcome = kinds.classify("drafts", status)

            if outcome is kinds.PUBLISH_CONFIRMED:
                article_urls = row.get("article_urls") or []
                _lang = row.get("language")
                ev, art, sk = _emit_drafts_confirmed(
                    draft_id, article_urls,
                    _lang if isinstance(_lang, str) and _lang else None,
                    target_url, host, ts_raw, ts_utc,
                    store, conn, pending_quarantines,
                )
                events_inserted += ev
                articles_inserted += art
                skipped_due_to_dedup += sk

            elif outcome is kinds.DRAFT_SCHEDULED:
                if prior_status == "scheduled":
                    continue
                store.append(
                    kinds.DRAFT_SCHEDULED,
                    {"draft_id": draft_id},
                    target_url=target_url,
                    host=host,
                    conn=conn,
                    pending_quarantines=pending_quarantines,
                )
                events_inserted += 1

            elif outcome is kinds.DRAFT_CREATED:
                if prior_status is not None:
                    continue
                store.append(
                    kinds.DRAFT_CREATED,
                    {"draft_id": draft_id},
                    target_url=target_url,
                    host=host,
                    conn=conn,
                    pending_quarantines=pending_quarantines,
                )
                events_inserted += 1

            else:
                pass

        cursor_save(
            conn,
            source,
            {"items": next_items},
            mtime=path.stat().st_mtime,
        )

    events_inserted -= sum(
        1 for q in pending_quarantines if q.get("failure_type") == "missing_field"
    )
    write_quarantines(store, pending_quarantines)

    return ProjectionResult(
        events_inserted=events_inserted,
        articles_inserted=articles_inserted,
        skipped_due_to_dedup=skipped_due_to_dedup,
        cursor_updated=True,
        quarantined=len(pending_quarantines),
        records_considered=records_considered,
    )
