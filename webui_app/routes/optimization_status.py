"""/optimization-status — optimisation state read-only dashboard card.

Reads ``optimization_state.json`` and renders platform weight + stats in a
simple table. Never 500s — any read error renders an honest "unavailable".

GET /optimization-status  → redirects to SPA /app/optimization-status (P13 B2)
"""

from __future__ import annotations

import logging
from typing import Any

from flask import Blueprint, jsonify, redirect, request, url_for

from ..helpers.contexts import _render

bp = Blueprint("optimization_status", __name__)
_log = logging.getLogger(__name__)

_PLATFORMS_CACHE: list[str] | None = None


def _get_platforms() -> list[str]:
    global _PLATFORMS_CACHE
    if _PLATFORMS_CACHE is None:
        try:
            from backlink_publisher.publishing.registry import registered_platforms
            _PLATFORMS_CACHE = sorted(registered_platforms())
        except Exception:
            _PLATFORMS_CACHE = []
    return _PLATFORMS_CACHE


def _read_platforms() -> list[dict]:
    """Authoritative platform-weight data via OptimizationState.to_summary().

    Same source command_center and the HTML page read, so the JSON endpoint can
    never drift from them. Returns [] on any read error (caller decides ok flag).
    """
    from backlink_publisher.optimization import OptimizationState
    return OptimizationState().to_summary().get("platforms", [])


@bp.route("/optimization-status", methods=["GET"])
def optimization_status() -> Any:
    """Redirect legacy /optimization-status → SPA /app/optimization-status (P13 B2)."""
    return redirect(url_for("spa.spa", subpath="optimization-status"), 302)


@bp.route("/optimization-status/jinja", methods=["GET"])
def optimization_status_jinja() -> Any:
    """Legacy Jinja fallback — kept for LITE mode or SPA-disabled setups."""
    message = request.args.get("message", "")
    try:
        from backlink_publisher.optimization import OptimizationState
        state = OptimizationState()
        summary = state.to_summary()
        platforms = summary.get("platforms", [])
    except Exception as exc:
        _log.warning("optimization-status: read failed: %s", exc)
        platforms = []

    return _render(
        "optimization_status.html",
        platforms=platforms,
        all_platforms=_get_platforms(),
        message=message,
        active_page="optimization_status",
    )


@bp.route("/api/optimization-status", methods=["GET"])
def optimization_status_json() -> Any:
    """Read-only JSON twin of the optimisation page (for the monitor hub, U5/U6).

    Shares OptimizationState.to_summary() with the HTML page and command_center —
    no third source of truth. Fail-open: never 500s; on error ok=false + empty.
    """
    try:
        platforms = _read_platforms()
    except Exception as exc:  # read-only dashboard data must never 500
        _log.warning("optimization-status json: read failed: %s", exc)
        return jsonify({"ok": False, "error": str(exc), "platforms": [], "all_platforms": _get_platforms()})
    return jsonify({"ok": True, "platforms": platforms, "all_platforms": _get_platforms()})


@bp.route("/api/optimization-status/set-weight", methods=["POST"])
def api_set_weight() -> Any:
    """JSON endpoint for setting platform weight (P13 B2 SPA migration)."""
    data = request.get_json(silent=True) or {}
    platform = (data.get("platform") or "").strip()
    weight_raw = data.get("weight")

    if not platform or weight_raw is None:
        return jsonify({"ok": False, "error": "platform and weight required"}), 400

    try:
        weight = float(weight_raw)
    except (ValueError, TypeError):
        return jsonify({"ok": False, "error": "weight must be a number"}), 400

    try:
        from backlink_publisher.optimization import OptimizationState
        state = OptimizationState()
        state.set_weight(platform, weight, rule="manual",
                         reason="manual override via WebUI", force=True)
        state.lock_weight(platform, locked=True)
        return jsonify({
            "ok": True,
            "message": f"Set {platform} weight to {weight} 🔒 (locked)",
        })
    except Exception as exc:
        _log.warning("api set-weight failed: %s", exc)
        return jsonify({"ok": False, "error": str(exc)}), 500


@bp.route("/api/optimization-status/unlock-weight", methods=["POST"])
def api_unlock_weight() -> Any:
    """JSON endpoint for unlocking platform weight (P13 B2 SPA migration)."""
    data = request.get_json(silent=True) or {}
    platform = (data.get("platform") or "").strip()
    if not platform:
        return jsonify({"ok": False, "error": "platform required"}), 400
    try:
        from backlink_publisher.optimization import OptimizationState
        state = OptimizationState()
        state.lock_weight(platform, locked=False)
        return jsonify({
            "ok": True,
            "message": f"Unlocked {platform} — rules can now manage weight",
        })
    except Exception as exc:
        _log.warning("api unlock-weight failed: %s", exc)
        return jsonify({"ok": False, "error": str(exc)}), 500


@bp.route("/optimization-status/set-weight", methods=["POST"])
def set_weight() -> Any:
    """Manually override a platform's dispatch weight."""
    platform = request.form.get("platform", "").strip()
    weight_str = request.form.get("weight", "").strip()

    if not platform or not weight_str:
        return _render("optimization_status.html",
                        platforms=[], all_platforms=_get_platforms(),
                        message="error: platform and weight required",
                        active_page="optimization_status"), 400

    try:
        weight = float(weight_str)
    except ValueError:
        return _render("optimization_status.html",
                        platforms=[], all_platforms=_get_platforms(),
                        message="error: weight must be a number",
                        active_page="optimization_status"), 400

    try:
        from backlink_publisher.optimization import OptimizationState
        state = OptimizationState()
        state.set_weight(platform, weight, rule="manual",
                         reason="manual override via WebUI", force=True)
        state.lock_weight(platform, locked=True)
        summary = state.to_summary()
        platforms = summary.get("platforms", [])
    except Exception as exc:
        _log.warning("set-weight failed: %s", exc)
        return _render("optimization_status.html",
                        platforms=[], all_platforms=_get_platforms(),
                        message=f"error: {exc}",
                        active_page="optimization_status"), 500

    return _render(
        "optimization_status.html",
        platforms=platforms,
        all_platforms=_get_platforms(),
        message=f"Set {platform} weight to {weight} 🔒 (locked)",
        active_page="optimization_status",
    )


@bp.route("/optimization-status/unlock-weight", methods=["POST"])
def unlock_weight() -> Any:
    """Release a platform's manual lock so rules can manage it again."""
    platform = request.form.get("platform", "").strip()
    if not platform:
        return _render("optimization_status.html",
                        platforms=[], all_platforms=_get_platforms(),
                        message="error: platform required",
                        active_page="optimization_status"), 400
    try:
        from backlink_publisher.optimization import OptimizationState
        state = OptimizationState()
        state.lock_weight(platform, locked=False)
        summary = state.to_summary()
        platforms = summary.get("platforms", [])
    except Exception as exc:
        _log.warning("unlock-weight failed: %s", exc)
        return _render("optimization_status.html",
                        platforms=[], all_platforms=_get_platforms(),
                        message=f"error: {exc}",
                        active_page="optimization_status"), 500
    return _render(
        "optimization_status.html",
        platforms=platforms,
        all_platforms=_get_platforms(),
        message=f"Unlocked {platform} — rules can now manage weight",
        active_page="optimization_status",
    )
