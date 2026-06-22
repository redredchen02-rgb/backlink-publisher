"""Medium browser-login flow for ``/api/v1`` — Plan 2026-06-18-002 U7.

JSON siblings of the legacy ``/settings/medium/*-browser-login`` routes. Both
transports call the SAME facade (``MediumLoginAPI``) — the dispatch, the outcome
classification, and the ``session_op`` decision are single-sourced there, so this
port cannot drift the publish-gating semantics on the JSON path.

  POST /api/v1/settings/medium/launch-browser-login  — open headed Chromium
  POST /api/v1/settings/medium/probe-browser-login   — probe login state
  POST /api/v1/settings/medium/clear-browser-login   — delete the login profile

Security: these spawn OS browser processes / delete the persistent login profile,
so — like the bind routes — each view enforces the Origin / ALLOW_NETWORK guards
INLINE (the ``api_v1`` blueprint does not inherit the legacy ``medium_login``
blueprint's per-route guards), gated on CSRF config and fired in production + the
security regression battery. The envelope (``{level, message, logged_in}``) is the
contract the SPA branches on (NOT RFC 9457): the call succeeds, the operation
outcome rides in ``level`` (success/info/warning/danger), always HTTP 200.
``logged_in`` reflects the resulting publish-gating state (null = unchanged).
"""

from __future__ import annotations

from flask import jsonify, session

from ...helpers.security import _check_bind_origin_or_abort, _refuse_when_allow_network
from ..medium_login_api import MediumLoginAPI
from . import bp
from .settings_credentials import _transport_guards_active


def _logged_in_state(result):
    """The publish-gating flag after this action, for the SPA: True/False when the
    facade set/cleared it, None when it left the prior state unchanged (errors)."""
    if result.session_op == "set":
        return result.logged_in
    if result.session_op == "clear":
        return False
    return None


def _render(result):
    return jsonify({
        "level": result.level,
        "message": result.message,
        "logged_in": _logged_in_state(result),
    })


# The guard literal ``_check_bind_origin_or_abort`` is repeated INLINE in each view
# (not factored into a helper) so the per-route-guard coverage gate
# (test_csrf_only_route_count_snapshot) sees it in the view source and excludes
# these routes — mirrors the bind / credential-write views.


@bp.post("/settings/medium/launch-browser-login")
def api_medium_launch():
    """Open a headed Chromium for the user to log in to Medium."""
    if _transport_guards_active():
        _refuse_when_allow_network()
        _check_bind_origin_or_abort()
    return _render(MediumLoginAPI().launch())


@bp.post("/settings/medium/probe-browser-login")
def api_medium_probe():
    """Probe Medium login state via a short Playwright navigation."""
    if _transport_guards_active():
        _refuse_when_allow_network()
        _check_bind_origin_or_abort()
    return _render(MediumLoginAPI().probe())


@bp.post("/settings/medium/clear-browser-login")
def api_medium_clear():
    """Delete the persistent Chromium profile (clears stored login cookies)."""
    if _transport_guards_active():
        _refuse_when_allow_network()
        _check_bind_origin_or_abort()
    return _render(MediumLoginAPI().clear())


@bp.get("/settings/medium/status")
def api_medium_status():
    """Read-only Medium card state: browser-fallback readiness + oauth-token
    presence. No guard — a status read with no secrets (the action POSTs above keep
    their inline guards). ``medium_probe_logged_in`` is the session publish-gating
    flag set by a prior probe; passed into the flask-free facade explicitly."""
    return jsonify(MediumLoginAPI().status(probe_logged_in=bool(session.get("medium_probe_logged_in"))))
