"""Velog channel actions for ``/api/v1`` — Plan 2026-06-18-002 U7.

JSON siblings of the legacy ``/api/velog/{login,status}`` routes. Both transports
call the SAME facade (``VelogLoginAPI``) — the spawn dispatch and the operator
message mapping are single-sourced there, so this port cannot drift them.

  GET  /api/v1/settings/velog/status  — channel status (6 states), no secrets
  POST /api/v1/settings/velog/login   — spawn headed velog-login subprocess

Security: ``login`` spawns a detached OS browser process, so — like the medium /
bind routes — it enforces the Origin / ALLOW_NETWORK guards INLINE (the ``api_v1``
blueprint does not inherit the legacy blueprint's per-route guards), gated on CSRF
config. The action returns the ``{ok, message, error_code, log_path}`` envelope
(NOT problem+json) always at HTTP 200 — a spawn that died early is a successful
call reporting an operational result. ``status`` is an unguarded read.
"""

from __future__ import annotations

from flask import jsonify

from ...helpers.security import _check_bind_origin_or_abort, _refuse_when_allow_network
from ..velog_login_api import VelogLoginAPI
from . import bp
from .settings_credentials import _transport_guards_active


@bp.get("/settings/velog/status")
def api_velog_status():
    """Current velog channel status — read-only, no secrets, no guard."""
    return jsonify(VelogLoginAPI().status())


@bp.post("/settings/velog/login")
def api_velog_login():
    """Spawn a headed velog-login window in a detached subprocess."""
    # Spawns an OS browser process, so enforce the transport guards inline (the
    # api_v1 blueprint does not inherit the legacy before_request). Both abort(403).
    if _transport_guards_active():
        _refuse_when_allow_network()
        _check_bind_origin_or_abort()
    r = VelogLoginAPI().login()
    return jsonify({
        "ok": r.ok,
        "message": r.message,
        "error_code": r.error_code,
        "log_path": r.log_path,
    })
