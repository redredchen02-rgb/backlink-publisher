"""Bootstrap/context endpoints for ``/api/v1`` — Plan 2026-06-18-002 U2.

Exposes as JSON what the Jinja context-processors injected (platforms,
bound_platforms, pro_status, lite_edition, csrf token) so the SPA can bootstrap
without a server-rendered page. Reuses ``webui_app.services.app_meta`` as the
single source (plan R3).

Security (single-origin threat model, plan U2): the global ``_global_origin_guard``
only covers POST/PUT/PATCH/DELETE, so a plain GET to the new ``/csrf-token`` /
``/app-config`` would be readable by a DNS-rebinding page. These two carry a
GET-time Origin/Referer check (same allowlist as the mutating guard), gated by
``ORIGIN_GUARD_ENABLED`` so it matches the global guard's pytest carve-out.
"""

from __future__ import annotations

from flask import current_app, jsonify

from ...helpers.security import _check_bind_origin_or_abort, _ensure_csrf_token
from ...services import app_meta
from . import bp
from .spec import API_VERSION, app_version


def _guard_sensitive_get() -> None:
    """GET-time Origin/Referer check for token/config bootstrap endpoints.

    Closes the DNS-rebinding read of the CSRF token. Gated by
    ``ORIGIN_GUARD_ENABLED`` (auto-off under pytest, same as the global guard),
    so the existing suite — which issues header-less GETs — stays green while a
    real deployment enforces it.
    """
    if current_app.config.get("ORIGIN_GUARD_ENABLED", True):
        _check_bind_origin_or_abort()


@bp.get("/csrf-token")
def csrf_token():
    """Mint/return the per-session CSRF token for the SPA fetch layer.

    The SPA must re-read this per mutating call and never cache it (a rotated
    token would 403). Origin-guarded at GET time (see module docstring).
    """
    _guard_sensitive_get()
    return jsonify({"csrf_token": _ensure_csrf_token()})


@bp.get("/app-config")
def app_config():
    """Single bootstrap payload: edition, Pro status, version. Origin-guarded."""
    _guard_sensitive_get()
    return jsonify(
        {
            "api_version": API_VERSION,
            "version": app_version(),
            "lite_edition": app_meta.lite_edition(),
            "pro_status": app_meta.pro_status_payload(),
            "llm_configured": app_meta.pro_status_payload()["configured"],
        }
    )


@bp.get("/platforms")
def platforms():
    """Full registered-platform list (slug + display_name)."""
    return jsonify({"platforms": app_meta.platforms_payload()})


@bp.get("/bound-platforms")
def bound_platforms():
    """Publish-form filter: bound + manifest-visible platforms."""
    return jsonify({"platforms": app_meta.bound_platforms_payload()})


@bp.get("/pro-status")
def pro_status():
    """Pro-Mode visibility summary (redaction-safe; never includes api_key)."""
    return jsonify({"pro_status": app_meta.pro_status_payload()})
