"""/optimization-status — optimisation state read-only dashboard card.

Reads ``optimization_state.json`` and renders platform weight + stats in a
simple table. Never 500s — any read error renders an honest "unavailable".
"""

from __future__ import annotations

import logging

from flask import Blueprint, request

from ..helpers.contexts import _render
from ..helpers.security import _check_bind_origin_or_abort

bp = Blueprint("optimization_status", __name__)

@bp.before_request
def _enforce_bind_origin() -> None:
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        _check_bind_origin_or_abort()

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


@bp.route("/optimization-status", methods=["GET"])
def optimization_status():
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


@bp.route("/optimization-status/set-weight", methods=["POST"])
def set_weight():
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
                         reason=f"manual override via WebUI", force=True)
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
def unlock_weight():
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
