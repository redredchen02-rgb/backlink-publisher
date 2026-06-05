"""/survival-dashboard — 30-day link-survival rate, read-only (R5).

Surfaces "% of mature links still live + dofollow", with sample size and honest
maturing/insufficient/stale/empty states. Never 500s — a read error degrades to
an "unavailable" panel (the service already catches; the route double-guards).
"""

from __future__ import annotations

import logging

from flask import Blueprint

from ..helpers.contexts import _render
from ..services.survival import build_survival_view

bp = Blueprint("survival_dashboard", __name__)
_log = logging.getLogger(__name__)


@bp.route("/survival-dashboard", methods=["GET"])
def survival_dashboard():
    # The render is INSIDE the try: a template fault (not just a service error)
    # must also degrade to the unavailable panel, or the docstring's "double-guard"
    # never-500 promise is false. The fallback view is then rendered separately so
    # only a genuinely broken template (both renders fail) can surface a 500.
    try:
        view = build_survival_view()
        return _render("survival_dashboard.html", view=view,
                       active_page="survival_dashboard")
    except Exception as exc:  # the screen must never 500
        _log.warning("survival-dashboard: render failed: %s", exc)
        view = {"state": "unavailable", "headline": "暂时不可用",
                "sub": "读取存活数据时出错", "display": "—", "has_rate": False,
                "sample_size": 0, "maturing_count": 0, "stale_count": 0,
                "stale": False, "partial": False, "cohort_days": 30}
        return _render("survival_dashboard.html", view=view,
                       active_page="survival_dashboard")
