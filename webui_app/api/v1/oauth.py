"""OAuth credential management for ``/api/v1`` — Plan 2026-06-18-002 U7.

JSON siblings of the legacy ``/settings/{save-blogger-oauth,clear-medium-oauth}``
routes. Both call the SAME facade (``OAuthAPI``) — the blank-secret-preserves rule
and the token-clear are single-sourced there.

Only the two credential-management routes are on ``/api/v1``; the Blogger
``oauth-start`` → Google → ``oauth-callback`` redirect handshake stays as legacy
browser-navigation routes (the callback is Google's top-level browser redirect
target and cannot answer with JSON) — see ``routes/oauth.py``.

Guard posture mirrors the legacy routes: NO inline ``_check_bind_origin_or_abort``
(these are config writes, not 0600 secret-file writes). They are Origin-protected
at runtime by the app-level ``_global_origin_guard`` — proven by
``test_global_guard_covers_every_mutating_route`` — and CSRF by ``_global_csrf_guard``.
"""

from __future__ import annotations

from flask import jsonify, request

from ..oauth_api import OAuthAPI
from . import bp
from .errors import ApiProblem


def _render(result):
    if result.error_class == "invalid_request":
        raise ApiProblem(422, "OAuth request rejected", detail=result.message,
                         error_class="invalid_request")
    if result.error_class == "persistence_failure":
        raise ApiProblem(502, "OAuth operation failed", detail=result.message,
                         error_class="persistence_failure")
    return jsonify({"ok": True, "message": result.message})


@bp.post("/settings/blogger-oauth")
def settings_save_blogger_oauth():
    """Save Blogger Client ID / Secret. Blank secret preserves the stored one."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        data = {}
    result = OAuthAPI().save_blogger(data.get("client_id", ""), data.get("client_secret", ""))
    return _render(result)


@bp.post("/settings/medium-oauth/clear")
def settings_clear_medium_oauth():
    """Revoke a stored Medium token (delete medium-token.json)."""
    return _render(OAuthAPI().clear_medium())
