"""Backlink Equity Ledger WebUI — per-target scorecard table.

Renders the same rows the ``equity-ledger`` CLI emits, from the same in-process
``ledger.build_ledger`` engine (no subprocess, no recomputation divergence).
GET is read-only; on-demand recheck POST (U6), Fill Gaps (U4), and batch
recheck (U5) are the mutation endpoints. Plan 2026-05-25-004 + 2026-06-05-001.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from flask import Blueprint, jsonify, request

from backlink_publisher._util.url import canonicalize_url
from backlink_publisher.config import load_config
from backlink_publisher.ledger import build_ledger
from backlink_publisher.publishing.registry import (
    dofollow_status,
    registered_platforms,
)

from ..helpers._request_cache import _g_cache
from ..helpers.contexts import _render

bp = Blueprint("equity_ledger", __name__)

_STALE_DAYS_DEFAULT: int = 30

# _outcome (from recheck_one) → delta-summary bucket.
_OUTCOME_LABELS = {"confirmed": "confirmed", "downgraded": "failed", "skipped": "skipped"}


def _active_dofollow_platforms() -> list[str]:
    return sorted(
        name for name in registered_platforms()
        if dofollow_status(name) is True
    )


def _compute_missing(row: dict) -> list[str]:
    live = set(row.get("live_dofollow_platforms") or [])
    all_dofollow = _active_dofollow_platforms()
    return [p for p in all_dofollow if p not in live]


def _resolve_stale_days() -> int:
    try:
        days = int(request.args.get("stale_days", 30))
    except (TypeError, ValueError):
        return 30
    return days if days > 0 else 30


def _build_rows(stale_days: int) -> tuple[list[dict], int]:
    """Shared ledger-row builder for the HTML page and the JSON endpoint.

    Single source of truth so /ce:equity-ledger and /api/equity-ledger never
    drift. Returns (rows, stale_count); each row carries its missing-dofollow set.
    """
    rows = [row.to_jsonl_dict() for row in build_ledger(stale_days=stale_days)]
    stale_count = sum(1 for r in rows if r["liveness"] in ("stale", "failed"))
    for r in rows:
        r["missing_dofollow_platforms"] = _compute_missing(r)
    return rows, stale_count


@bp.route("/ce:equity-ledger", methods=["GET"])
def equity_ledger() -> Any:
    stale_days = _resolve_stale_days()
    cfg = _g_cache('config', load_config)
    rows, stale_count = _build_rows(stale_days)
    return _render(
        "equity_ledger.html",
        rows=rows,
        stale_days=stale_days,
        stale_count=stale_count,
        exact_match_threshold=cfg.anchor_alarm.exact_ratio_ceiling,
        active_page='equity',
    )


@bp.route("/api/equity-ledger", methods=["GET"])
def equity_ledger_json() -> Any:
    """Read-only JSON twin of the ledger page (for the monitor hub, U5/U6).

    Derives from the same _build_rows() as the HTML route — no recomputation, no
    drift. Fail-open: never 500s; on error returns ok=false with an empty list.
    """
    stale_days = _resolve_stale_days()
    try:
        rows, stale_count = _build_rows(stale_days)
    except Exception as exc:  # read-only dashboard data must never 500
        return jsonify({"ok": False, "error": str(exc), "rows": [], "stale_days": stale_days, "stale_count": 0})
    return jsonify({"ok": True, "rows": rows, "stale_days": stale_days, "stale_count": stale_count})


@bp.route("/ce:equity-ledger/recheck", methods=["POST"])
def equity_ledger_recheck() -> Any:
    """On-demand recheck of one target's links (operator-initiated, U6).

    A canonical target can be backed by several history rows; recheck iterates
    every backing row, calls ``recheck_one`` per row, and writes back via the
    canonical ``update_item`` helper. The target's row is then recomputed and
    returned for in-place refresh. No scheduler, no background job.
    """
    from backlink_publisher.events.history_query import get_history_item as _get_ev_item
    from webui_store import history_store

    def _get_history_item(item_id: str) -> Any:
        """Look up a history item from EventStore first, fallback to history_store.

        history_item_ids from the ledger may be UUID8 strings (from history_store)
        or integer strings (from EventStore); check both so items are never skipped.
        """
        item = _get_ev_item(item_id)
        if item is None:
            item = history_store.get_item(item_id)
        return item

    from backlink_publisher.events.publish_writer import (
        map_history_entry,
        write_event,
    )
    from backlink_publisher.events.store import EventStore as _EventStore

    from ..services.recheck import recheck_one

    data = request.get_json(silent=True) or {}
    target = data.get("target_url")
    if not target:
        return jsonify({"error": "target_url required"}), 400
    # Honor the same staleness window the table was rendered with, so the
    # refreshed row's stale flag matches the rest of the view.
    try:
        stale_days = int(data.get("stale_days", _STALE_DAYS_DEFAULT))
    except (TypeError, ValueError):
        stale_days = _STALE_DAYS_DEFAULT
    if stale_days <= 0:
        stale_days = _STALE_DAYS_DEFAULT
    canon = canonicalize_url(target)

    row = next((r for r in build_ledger(stale_days=stale_days) if r.target_url == canon), None)
    if row is None:
        return jsonify({"error": "target not found"}), 404

    counts: Counter[str] = Counter()
    for item_id in row.history_item_ids:
        item = _get_history_item(item_id)
        if not item:
            counts["skipped"] += 1  # deleted between snapshot and recheck
            continue
        try:
            aid: int | None = int(item_id)
        except (ValueError, TypeError):
            aid = None
        try:
            mutation = recheck_one(item)
        except Exception as exc:  # one bad item must not abort the whole batch
            history_store.update_item(item_id, status="failed", verify_error=str(exc))
            counts["failed"] += 1
            failed_entry = {**item, "status": "failed", "error": str(exc)}
            mapped = map_history_entry(failed_entry)
            if mapped is not None:
                write_event(mapped[0], mapped[1], target_url=failed_entry.get("target_url"),
                            article_id=aid)
            continue
        outcome = mutation.pop("_outcome", None)
        history_store.update_item(item_id, **mutation)
        counts[_OUTCOME_LABELS.get(outcome, "skipped")] += 1
        updated = {**item, **mutation}
        mapped = map_history_entry(updated)
        if mapped is not None:
            write_event(mapped[0], mapped[1], target_url=updated.get("target_url"),
                        article_id=aid)
        if aid is not None:
            _EventStore().update_article_verified(
                aid,
                verified_at=mutation.get("verified_at"),
                verify_error=mutation.get("verify_error"),
            )

    # Recompute the target's row from the freshly mutated history.
    refreshed = next((r for r in build_ledger(stale_days=stale_days) if r.target_url == canon), row)
    summary = (
        f"{counts['confirmed']} confirmed, "
        f"{counts['failed']} failed, {counts['skipped']} skipped"
    )
    return jsonify({"row": refreshed.to_jsonl_dict(), "summary": summary})
