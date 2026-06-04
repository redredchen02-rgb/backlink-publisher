"""Keep-alive status screen (R3 / plan 2026-06-04-001 Unit 4).

The LITE operator's landing surface: a read-only per-target scorecard of which
backlinks are still live vs stripped, bleeding deep pages first, sourced from the
``link.rechecked`` time series (the liveness authority — the ledger column is
stale). The recheck / republish *action* states (S1, S3–S7) land in Units 5–7;
this unit owns the read states (S0 / S2-static / S-stale / empty).
"""
from __future__ import annotations

from flask import Blueprint, abort, jsonify

from backlink_publisher._util.errors import UsageError

from ..helpers.contexts import _render
from ..helpers.security import _check_bind_origin_or_abort
from ..services.keep_alive import build_keepalive_view
from ..services.keepalive_job import registry as keepalive_registry

bp = Blueprint("keep_alive", __name__)


@bp.route("/ce:keep-alive", methods=["GET"])
def keep_alive():
    view = build_keepalive_view()
    running = keepalive_registry.running_job("recheck")  # G5a: rehydrate on reopen
    return _render(
        "keep_alive.html", view=view, active_page="keep_alive", running_job=running
    )


@bp.route("/ce:keep-alive/recheck", methods=["POST"])
def start_recheck():
    # A recheck fires ~70 outbound probes — an outbound action — so the Origin
    # guard (sole DNS-rebinding / malicious-localhost defense) is enforced on
    # top of the app-level CSRF guard (mirror routes/bind.py).
    _check_bind_origin_or_abort()
    try:
        job = keepalive_registry.start_recheck()
        return jsonify({"status": "started", "job_id": job.id}), 202
    except UsageError:
        # One running recheck at a time: return the existing job, never a
        # second worker (a double-click must not run two sweeps). 409 is a
        # deliberate route choice (the service raises UsageError).
        running = keepalive_registry.running_job("recheck")
        return jsonify({
            "status": "running",
            "job_id": running["job_id"] if running else None,
            "message": "巡检已在进行中，请稍候。",
        }), 409


@bp.route("/ce:keep-alive/recheck-status/<job_id>", methods=["GET"])
def recheck_status(job_id: str):
    # Returns only progress/rollups — never credentials or the target
    # inventory — and 404s on an unknown/guessed id (bind.py shape).
    poll = keepalive_registry.poll(job_id)
    if poll is None:
        abort(404)
    return jsonify(poll)


@bp.route("/ce:keep-alive/recheck-cancel/<job_id>", methods=["POST"])
def recheck_cancel(job_id: str):
    # Cooperative cancel: flags the worker, which stops at the next probe
    # boundary leaving a partial result. State-changing POST → Origin guard.
    _check_bind_origin_or_abort()
    poll = keepalive_registry.cancel(job_id)
    if poll is None:
        abort(404)
    return jsonify(poll)
