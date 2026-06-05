"""Batch recheck — POST to start + GET to poll (Plan 2026-06-05-001 U5).

Runs recheck on multiple stale/failed/weak targets in a background thread
with progress polling. In-memory job store (non-persistent).
"""

from __future__ import annotations

import threading
import uuid

from flask import Blueprint, jsonify, request

from backlink_publisher._util.url import canonicalize_url
from backlink_publisher.ledger import build_ledger

from ..services.recheck import recheck_many

bp = Blueprint("equity_batch_recheck", __name__)

_STALE_DAYS_DEFAULT: int = 30

# In-memory job store.
_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()


def _resolve_stale_days() -> int:
    try:
        days = int(request.args.get("stale_days", 30))
    except (TypeError, ValueError):
        return 30
    return days if days > 0 else 30


def _run_batch(job_id: str, target_urls: list[str]) -> None:
    """Background worker: recheck each target, update job state."""
    from webui_store import history_store

    from backlink_publisher.events.history_query import get_history_item

    total = len(target_urls)
    checked = 0
    confirmed = 0
    failed = 0
    skipped = 0

    for target in target_urls:
        row = next(
            (r for r in build_ledger(stale_days=_STALE_DAYS_DEFAULT)
             if r.target_url == canonicalize_url(target)),
            None,
        )
        if row is None:
            skipped += 1
            checked += 1
            with _jobs_lock:
                _jobs[job_id] = {
                    "done": total == checked,
                    "checked": checked,
                    "total": total,
                    "confirmed": confirmed,
                    "failed": failed,
                    "skipped": skipped,
                }
            continue

        items = []
        for item_id in row.history_item_ids:
            item = get_history_item(item_id)
            if item:
                items.append(item)

        if not items:
            skipped += 1
            checked += 1
            with _jobs_lock:
                _jobs[job_id] = {
                    "done": total == checked,
                    "checked": checked,
                    "total": total,
                    "confirmed": confirmed,
                    "failed": failed,
                    "skipped": skipped,
                }
            continue

        by_id, summary = recheck_many(items)
        for item_id, mutation in by_id.items():
            history_store.update_item(item_id, **mutation)

        confirmed += summary.confirmed
        failed += summary.downgraded_to_failed
        skipped += summary.skipped
        checked += 1

        with _jobs_lock:
            _jobs[job_id] = {
                "done": checked >= total,
                "checked": checked,
                "total": total,
                "confirmed": confirmed,
                "failed": failed,
                "skipped": skipped,
            }


def _select_targets(filter_type: str) -> list[str]:
    """Select target URLs matching the given filter."""
    targets = []
    rows = build_ledger(stale_days=_STALE_DAYS_DEFAULT)
    for row in rows:
        if filter_type == "weak":
            if row.live_dofollow == 0:
                targets.append(row.target_url)
        elif filter_type == "stale-failed":
            if row.liveness in ("stale", "failed"):
                targets.append(row.target_url)
        else:
            targets.append(row.target_url)
    return targets


@bp.route("/ce:equity-ledger/batch-recheck", methods=["POST"])
def batch_recheck_start():
    data = request.get_json(silent=True) or {}
    filter_type = data.get("filter", "all")

    target_urls: list[str] = []
    explicit = data.get("target_urls")
    if explicit and isinstance(explicit, list):
        target_urls = [canonicalize_url(u) for u in explicit]
    else:
        if filter_type not in ("weak", "stale-failed", "all"):
            return jsonify({"error": f"invalid filter: {filter_type}"}), 400
        target_urls = _select_targets(filter_type)

    if not target_urls:
        return jsonify({"done": True, "checked": 0, "total": 0,
                        "confirmed": 0, "failed": 0, "skipped": 0})

    job_id = str(uuid.uuid4())
    with _jobs_lock:
        _jobs[job_id] = {
            "done": False,
            "checked": 0,
            "total": len(target_urls),
            "confirmed": 0,
            "failed": 0,
            "skipped": 0,
        }

    thread = threading.Thread(target=_run_batch, args=(job_id, target_urls), daemon=True)
    thread.start()

    return jsonify({"job_id": job_id, "total": len(target_urls)})


@bp.route("/ce:equity-ledger/batch-recheck/<job_id>/status", methods=["GET"])
def batch_recheck_status(job_id: str):
    with _jobs_lock:
        job = _jobs.get(job_id)
    if job is None:
        return jsonify({"error": "job not found"}), 404
    return jsonify(job)
