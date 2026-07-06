"""Survival-dashboard — read-only, fail-open.

Surfaces "% of mature links still live + dofollow", with sample size and honest
maturing/insufficient/stale/empty states. Never 500s — any exception during
template rendering degrades to an "unavailable" card.

GET /survival-dashboard  → redirects to SPA /app/survival (P13 B1 migration)
GET /api/survival        → JSON twin for the SPA
GET /survival-dashboard/jinja → legacy Jinja fallback
"""

from __future__ import annotations

import logging
from typing import Any

from flask import Blueprint, jsonify, redirect, url_for

from ..helpers.contexts import _render
from ..services.survival import build_survival_view

bp = Blueprint("survival_dashboard", __name__)
_log = logging.getLogger(__name__)


@bp.route("/survival-dashboard", methods=["GET"])
def survival_dashboard() -> Any:
    """Redirect legacy /survival-dashboard → SPA /app/survival (P13 B1)."""
    return redirect(url_for("spa.spa", subpath="survival"), 302)


@bp.route("/survival-dashboard/jinja", methods=["GET"])
def survival_dashboard_jinja() -> Any:
    """Legacy Jinja fallback — kept for LITE mode or SPA-disabled setups."""
    try:
        view = build_survival_view()
        return _render("survival_dashboard.html", view=view,
                       active_page="survival_dashboard")
    except Exception:  # noqa: BLE001 — never 500 the page
        _log.warning("survival-dashboard: render failed", exc_info=True)
        view = {"state": "unavailable", "headline": "暂时不可用",
                "sub": "读取存活数据时出错", "display": "—", "has_rate": False,
                "sample_size": 0, "maturing_count": 0, "stale_count": 0,
                "stale": False, "partial": False, "cohort_days": 30}
        return _render("survival_dashboard.html", view=view,
                       active_page="survival_dashboard")


@bp.route("/api/survival", methods=["GET"])
def api_survival() -> Any:
    """JSON twin of the survival dashboard (for SPA consumption, P13 B1)."""
    try:
        view = build_survival_view()
        return jsonify(view)
    except Exception:  # noqa: BLE001 — never 500
        _log.warning("api/survival: build failed", exc_info=True)
        return jsonify({"state": "unavailable", "headline": "暂时不可用",
                        "sub": "", "display": "—", "has_rate": False,
                        "sample_size": 0, "survived": 0, "mature_count": 0,
                        "maturing_count": 0, "stale": False, "stale_count": 0,
                        "partial": False, "stale_days": None,
                        "cohort_days": 30})
