"""/schedule — Plan 2026-05-29-001 Unit 2.

GET /schedule        → redirects to SPA /app/schedule (Sprint B1)
GET /schedule/jinja   → legacy Jinja fallback — kept for LITE mode or
                        SPA-disabled setups (mirrors the pattern used by
                        pr-queue / survival-dashboard / optimization-status).
"""

from __future__ import annotations

from typing import Any

from flask import Blueprint, jsonify, redirect, url_for

from ..api.scheduled_api import list_scheduled
from ..helpers.contexts import _render

bp = Blueprint("schedule", __name__)


@bp.get("/schedule")
def schedule_redirect() -> Any:
    """Redirect legacy /schedule → SPA /app/schedule (Sprint B1)."""
    return redirect(url_for("spa.spa", subpath="schedule"), 302)


@bp.get("/schedule/jinja")
def schedule_list() -> Any:
    """Return CSRF-time-safe page_data bootstrap with scheduled drafts."""
    scheduled = list_scheduled()
    return _render(
        "schedule.html",
        scheduled_items=scheduled.get("items", []) if scheduled.get("ok") else [],
        active_page='schedule',
    )


@bp.get("/api/scheduled")
def api_scheduled() -> Any:
    """Return scheduled drafts as JSON for the schedule page ESM."""
    data = list_scheduled()
    resp = jsonify(data)
    resp.headers["Content-Type"] = "application/json; charset=utf-8"
    return resp
