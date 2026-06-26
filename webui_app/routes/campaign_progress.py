"""/campaign/<id> — Plan 2026-06-02-001 U5.

Campaign progress page + JSON polling endpoint.
"""

from __future__ import annotations

from typing import Any

from flask import Blueprint, current_app, jsonify, render_template

from ..helpers.security import _ensure_csrf_token

bp = Blueprint("campaign_progress", __name__)


@bp.route("/campaign/<campaign_id>")
def campaign_progress_page(campaign_id: str) -> Any:
    """Render the campaign progress / results page."""
    from webui_store import campaign_store

    csrf_token = _ensure_csrf_token()
    campaign = campaign_store.get(campaign_id)
    if campaign is None:
        return render_template(
            "campaign_progress.html",
            csrf_token=csrf_token,
            campaign=None,
            error="未找到该任务",
            active_page="batch_campaign",
        ), 404

    worker = current_app.config.get("CAMPAIGN_WORKER")
    running = False
    if worker is not None:
        status = worker.get_status(campaign_id)
        running = bool(status and status.get("_running"))

    return render_template(
        "campaign_progress.html",
        csrf_token=csrf_token,
        campaign=campaign,
        running=running,
        error=None,
        active_page="batch_campaign",
    )


@bp.route("/api/campaign/<campaign_id>/status")
def campaign_status_api(campaign_id: str) -> Any:
    """JSON polling endpoint for campaign progress."""
    from webui_store import campaign_store

    campaign = campaign_store.get(campaign_id)
    if campaign is None:
        return jsonify({"error": "campaign not found"}), 404

    worker = current_app.config.get("CAMPAIGN_WORKER")
    running = False
    done = True
    if worker is not None:
        status = worker.get_status(campaign_id)
        if status is not None:
            running = status.get("_running", False)
            done = status.get("_done", True)

    return jsonify({
        "campaign_id": campaign["campaign_id"],
        "status": campaign.get("status"),
        "progress_pct": campaign.get("progress_pct", 0.0),
        "mode": campaign.get("mode"),
        "running": running,
        "done": done,
        "seeds": campaign.get("seeds", []),
        "result_summary": campaign.get("result_summary"),
    })
