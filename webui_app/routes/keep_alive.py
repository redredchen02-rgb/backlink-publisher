"""Keep-alive status screen (R3 / plan 2026-06-04-001 Unit 4).

The LITE operator's landing surface: a read-only per-target scorecard of which
backlinks are still live vs stripped, bleeding deep pages first, sourced from the
``link.rechecked`` time series (the liveness authority — the ledger column is
stale). The recheck / republish *action* states (S1, S3–S7) land in Units 5–7;
this unit owns the read states (S0 / S2-static / S-stale / empty).

plan 2026-06-04-002: Unit 1 adds POST /ce:keep-alive/recheck.
"""
from __future__ import annotations

from flask import Blueprint, abort, jsonify, request

from backlink_publisher._util.errors import UsageError
from backlink_publisher._util.url import canonicalize_url
from backlink_publisher.gap.engine import KEEPALIVE_STICKY_PLATFORMS

from ..api import HistoryAPI
from ..helpers.contexts import _render
from ..helpers.security import _check_bind_origin_or_abort
from ..services.keep_alive import build_cycle_status_view, build_keepalive_view
from ..services.keepalive_job import registry as keepalive_registry

bp = Blueprint("keep_alive", __name__)
_history = HistoryAPI()


@bp.route("/ce:keep-alive", methods=["GET"])
def keep_alive():
    flash_type = request.args.get("flash_type", "")
    flash_msg = request.args.get("flash_msg", "")
    flash = {"type": flash_type, "msg": flash_msg} if flash_type else None
    view = build_keepalive_view()
    running = keepalive_registry.running_job("recheck")  # G5a: rehydrate on reopen
    return _render(
        "keep_alive.html", view=view, flash=flash, active_page="keep_alive", running_job=running
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


@bp.route("/ce:keep-alive/republish-token", methods=["GET"])
def republish_token():
    # Mint a single-use confirm nonce bound to the CURRENT gap set (S3→S4). It
    # only matters together with the Origin guard + CSRF on the republish POST.
    return jsonify(keepalive_registry.issue_confirm_token())


@bp.route("/ce:keep-alive/republish", methods=["POST"])
def start_republish():
    # Outbound publish — treat the body as hostile even from "the operator".
    _check_bind_origin_or_abort()
    body = request.get_json(silent=True) or {}
    targets = body.get("targets")
    confirm_token = body.get("confirm_token") or ""
    platform = body.get("platform")
    # Hard sticky allowlist: reject a forged non-sticky destination up front,
    # before any plan/publish (the gap set is re-derived sticky-only anyway).
    if platform is not None and platform not in set(KEEPALIVE_STICKY_PLATFORMS):
        return jsonify({"status": "error", "error": "non_sticky_platform"}), 400
    if not isinstance(targets, list) or not targets or not confirm_token:
        return jsonify({"status": "error", "error": "missing targets or confirm_token"}), 400
    try:
        job = keepalive_registry.start_republish(
            selected_targets=targets, confirm_token=confirm_token
        )
        return jsonify({"status": "started", "job_id": job.id}), 202
    except UsageError as exc:
        msg = str(exc)
        code = 409 if "already running" in msg else 400
        return jsonify({"status": "error", "error": msg}), code


@bp.route("/ce:keep-alive/republish-status/<job_id>", methods=["GET"])
def republish_status(job_id: str):
    poll = keepalive_registry.poll(job_id)
    if poll is None or poll.get("kind") != "republish":
        abort(404)
    return jsonify(poll)


@bp.route("/ce:keep-alive/cycle-status", methods=["GET"])
def cycle_status():
    """Return last automated keepalive-run cycle data for the WebUI panel.

    Read-only; no auth required beyond app-level origin guard.
    Cross-process read race with keepalive-run is accepted (same precedent as
    /optimization-status which reads optimization_state.json the same way).
    """
    return jsonify(build_cycle_status_view())


@bp.route("/ce:keep-alive/reset-exhausted", methods=["POST"])
def reset_exhausted():
    """Reset a single exhausted target so it can be retried again.

    Requires Origin guard (state-changing POST, matches start_recheck pattern).
    Returns {status: "ok", was_present: bool}.
    """
    _check_bind_origin_or_abort()
    body = request.get_json(silent=True) or {}
    target_url = (body.get("target_url") or "").strip()
    if not target_url:
        return jsonify({"status": "error", "error": "target_url required"}), 400
    # Normalize so agents/scripts calling with trailing-slash or encoding variants
    # still match the key stored by record_attempt() via chain.py.
    target_url = canonicalize_url(target_url)

    from backlink_publisher.keepalive.run_state import KeepaliveRunState
    rs = KeepaliveRunState()
    data = rs.load()
    was_present = target_url in data.get("retry_counts", {})
    rs.reset_exhausted(target_url)
    return jsonify({"status": "ok", "was_present": was_present})
