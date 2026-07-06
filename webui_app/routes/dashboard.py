"""Task Dashboard Route — Plan 2026-05-18-001.

Plan 012 Unit 2 made `/ce:dashboard` a 302 redirect (the retry-task POST
endpoint moved to the `history` blueprint; `/ce:retry-task` is unchanged).
Plan 2026-05-25-006 U3 repurposes "dashboard" to mean the publishing **health**
dashboard, so the redirect now targets `/ce:health`. The in-progress task list
is still reachable directly at `/ce:history?section=in-progress`.
"""

from __future__ import annotations

from typing import Any

from flask import Blueprint, jsonify, redirect, request

bp = Blueprint("dashboard", __name__)


@bp.route('/ce:dashboard', methods=['GET'])
def ce_dashboard() -> Any:
    return redirect('/ce:health', code=302)


@bp.route("/dashboard/autopilot-alert/dismiss", methods=["POST"])
def dashboard_autopilot_alert_dismiss() -> Any:
    """Clear alert_pending for a site (Plan 2026-06-09-001 U8 R4).

    Does NOT disable autopilot — only clears the alert flag.
    Body: {site_url: str}
    """
    import webui_store as _ws

    body = request.get_json(silent=True) or {}
    site_url = (body.get("site_url") or "").strip()
    if not site_url:
        return jsonify({"error": "missing site_url"}), 400

    def _clear_alert(settings: Any) -> Any:
        targets = dict(settings.get("autopilot_targets", {}))
        if site_url in targets:
            site_cfg = dict(targets[site_url])
            site_cfg["alert_pending"] = False
            targets[site_url] = site_cfg
        return {**settings, "autopilot_targets": targets}

    _ws.schedule_store.update(_clear_alert)
    return jsonify({"ok": True}), 200
