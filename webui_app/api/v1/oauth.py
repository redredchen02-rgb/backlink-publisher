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

from typing import Any

from flask import jsonify, request

from ..blogger_settings_api import BloggerSettingsAPI
from ..oauth_api import OAuthAPI
from . import bp
from .errors import ApiProblem


def _render(result: Any) -> Any:
    if result.error_class == "invalid_request":
        raise ApiProblem(422, "OAuth request rejected", detail=result.message,
                         error_class="invalid_request")
    if result.error_class == "persistence_failure":
        raise ApiProblem(502, "OAuth operation failed", detail=result.message,
                         error_class="persistence_failure")
    return jsonify({"ok": True, "message": result.message})


@bp.post("/settings/blogger-oauth")
def settings_save_blogger_oauth() -> Any:
    """Save Blogger Client ID / Secret. Blank secret preserves the stored one."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        data = {}
    result = OAuthAPI().save_blogger(data.get("client_id", ""), data.get("client_secret", ""))
    return _render(result)


@bp.post("/settings/medium-oauth/clear")
def settings_clear_medium_oauth() -> Any:
    """Revoke a stored Medium token (delete medium-token.json)."""
    return _render(OAuthAPI().clear_medium())


@bp.get("/settings/blogger/status")
def settings_blogger_status() -> Any:
    """Read-only Blogger card state: authorization + saved OAuth client + the
    callback URI to register in Google Cloud Console. No secrets (only a
    ``client_secret_set`` boolean), so no inline guard."""
    return jsonify(OAuthAPI().blogger_status())


@bp.post("/settings/blogger/revoke")
def settings_revoke_blogger() -> Any:
    """Revoke Blogger authorization (delete the stored token file). Same posture as
    the other OAuth writes: no inline guard (config/file op, not a 0600 secret
    write), Origin-protected at runtime by the app-level guard."""
    return _render(OAuthAPI().revoke_blogger())


@bp.get("/settings/blogger/blog-ids")
def settings_get_blog_ids() -> Any:
    """The current domain → Blogger Blog ID routing map. Read-only, no secrets."""
    return jsonify({"blog_ids": BloggerSettingsAPI().get_blog_ids()})


@bp.post("/settings/blogger/blog-ids")
def settings_save_blog_ids() -> Any:
    """Save the domain → Blogger Blog ID mapping (config write, same no-inline-guard
    posture as the other blogger writes). Body: ``{"blog_ids": {domain: id}}``."""
    data = request.get_json(silent=True)
    mapping = data.get("blog_ids") if isinstance(data, dict) else None
    if not isinstance(mapping, dict):
        mapping = {}
    return _render(BloggerSettingsAPI().save_blog_ids(mapping))
