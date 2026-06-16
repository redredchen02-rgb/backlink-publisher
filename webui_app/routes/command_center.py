from __future__ import annotations

import re

from flask import Blueprint, jsonify, request

from backlink_publisher._util.errors import UsageError
from ..helpers.contexts import _render
from ..services.keepalive_job import registry as keepalive_registry

bp = Blueprint("command_center", __name__)


def _friendly_error(msg: str) -> str:
    """Truncate noisy Python paths from error messages."""
    msg = re.sub(r"\([^)]*\.py[^)]*\)", "", msg)
    msg = re.sub(r"/[^\s]+\.py", "", msg)
    return msg.strip().rstrip(",").strip()


def _collect_subsystem_status():
    """Aggregate a lightweight snapshot from each monitored subsystem.

    Returns a dict with top-level keys (keepalive, equity, optimization, history)
    that the template sections read to render their cards. Never raises — every
    section degrades to "unavailable" on error.
    """
    result = {}

    # ── keep-alive ──────────────────────────────────────────────────────
    try:
        from ..services.keep_alive import build_keepalive_view
        view = build_keepalive_view()
        result["keepalive"] = {
            "n_targets": len(view.get("targets", [])),
            "stripped": view.get("stripped_count", 0),
            "alive": view.get("alive_count", 0),
            "unknown": view.get("unknown_count", 0),
        }
    except Exception as exc:
        result["keepalive"] = {"error": _friendly_error(str(exc))}

    # ── running jobs ────────────────────────────────────────────────────
    jobs = []
    try:
        for kind in ("recheck", "republish", "gap_closure"):
            j = keepalive_registry.running_job(kind)
            if j:
                jobs.append(j)
        result["jobs"] = jobs
    except Exception as exc:
        result["jobs"] = {"error": _friendly_error(str(exc))}

    # ── equity — derived from optimization state (no ledger_store) ──────
    try:
        from backlink_publisher.optimization import OptimizationState as _OS
        _eq_state = _OS()
        _eq_summary = _eq_state.to_summary()
        platforms = _eq_summary.get("platforms", [])
        low_weight = [p for p in platforms if (p.get("current") or p.get("weight") or 0) < 0.3]
        result["equity"] = {
            "total_rows": len(platforms),
            "low_weight_count": len(low_weight),
        }
    except Exception as exc:
        result["equity"] = {"error": _friendly_error(str(exc))}

    # ── optimization state ──────────────────────────────────────────────
    try:
        from backlink_publisher.optimization import OptimizationState
        state = OptimizationState()
        summary = state.to_summary()
        result["optimization"] = {
            "n_platforms": len(summary.get("platforms", [])),
            "platforms": summary.get("platforms", []),
        }
    except Exception as exc:
        result["optimization"] = {"error": _friendly_error(str(exc))}

    # ── history (recent publish count) ──────────────────────────────────
    try:
        from webui_store import history_store
        from datetime import datetime, timezone, timedelta
        hist = history_store.load()
        now = datetime.now(timezone.utc)
        cutoff_24h = (now - timedelta(hours=24)).isoformat()[:16]
        cutoff_7d  = (now - timedelta(days=7)).isoformat()[:10]
        def _ts(h):
            return h.get("created_at") or h.get("published_at") or ""
        recent_24h = sum(1 for h in hist if _ts(h) >= cutoff_24h)
        recent_7d  = sum(1 for h in hist if _ts(h)[:10] >= cutoff_7d)
        last_ts = max((_ts(h) for h in hist if _ts(h)), default=None)
        result["history"] = {
            "total": len(hist),
            "recent_24h": recent_24h,
            "recent_7d": recent_7d,
            "last_published_at": (last_ts or "")[:10] or None,
        }
    except Exception as exc:
        result["history"] = {"error": _friendly_error(str(exc))}

    return result


@bp.route("/ce:command-center", methods=["GET"])
def command_center():
    status = _collect_subsystem_status()
    return _render("command_center.html", status=status, active_page="command_center")


@bp.route("/ce:command-center/gap-closure", methods=["POST"])
def trigger_gap_closure():
    """Trigger a full-pipeline gap-closure run in the background."""
    try:
        job = keepalive_registry.start_gap_closure()
        return jsonify({"status": "started", "job_id": job.id}), 202
    except UsageError as exc:
        running = keepalive_registry.running_job("gap_closure")
        return jsonify({
            "status": "running",
            "job_id": running["job_id"] if running else None,
            "message": str(exc),
        }), 409


@bp.route("/ce:command-center/jobs", methods=["GET"])
def list_jobs():
    """Return all tracked jobs across kinds."""
    jobs_by_kind = {}
    for kind in ("recheck", "republish", "gap_closure"):
        try:
            j = keepalive_registry.running_job(kind)
            if j:
                jobs_by_kind[kind] = j
        except Exception:
            pass
    return jsonify(jobs_by_kind)


@bp.route("/ce:command-center/job/<job_id>", methods=["GET"])
def poll_job(job_id: str):
    """Poll a specific job by id."""
    result = keepalive_registry.poll(job_id)
    if result is None:
        return jsonify({"error": "job not found"}), 404
    return jsonify(result)
