"""Stateful channel browser-bind flow for ``/api/v1`` — Plan 2026-06-18-002 U7.

JSON siblings of the legacy ``/settings/channels/<channel>/bind*`` routes. Both
transports call the SAME facade (``BindAPI``) — the identity_mismatch TOCTOU
guard, the atomic keep/restore closure, and the replace artifact-wipe live there
as a single source, so this port cannot drift the keep≠destroy semantics on the
JSON path.

  POST /api/v1/settings/channels/<channel>/bind                      — start a job
  GET  /api/v1/settings/channels/<channel>/bind/<job_id>             — poll
  POST /api/v1/settings/channels/<channel>/identity-mismatch/keep    — keep old
  POST /api/v1/settings/channels/<channel>/identity-mismatch/replace — replace

Security: the ``api_v1`` blueprint does NOT inherit the legacy ``bind`` blueprint's
``before_request`` loopback check, so each view enforces the loopback ``remote_addr``
gate inline (this is the ONLY loopback defense on the GET poll, which has no
``_refuse_when_allow_network``). The mutating routes additionally enforce the
Origin / ALLOW_NETWORK guards inline — gated on CSRF config like the other v1
credential writes, fired in production and the security regression battery.
"""

from __future__ import annotations

from typing import Any

from flask import abort, jsonify, request

from ...helpers.security import (
    _check_bind_origin_or_abort,
    _LOOPBACK_HOSTS,
    _refuse_when_allow_network,
)
from ..bind_api import BindAPI
from . import bp
from .errors import ApiProblem
from .settings_credentials import _transport_guards_active

_PROBLEM_TITLES = {
    "bad_channel": "Unknown channel",
    "not_found": "Bind job not found",
    "conflict": "Bind blocked by unresolved identity mismatch",
    "invalid_request": "Bind request rejected",
}


def _enforce_loopback_addr() -> None:
    """Mirror the legacy ``bind`` blueprint's ``before_request`` — peer must be
    loopback. Belt-and-suspenders under loopback binding; the real defense on the
    GET poll when ``ALLOW_NETWORK=1`` widens the bind address."""
    if request.remote_addr not in _LOOPBACK_HOSTS:
        abort(403)


def _render(result: Any) -> Any:
    if not result.ok:
        raise ApiProblem(
            result.status,
            _PROBLEM_TITLES.get(result.error_class, "Bind error"),
            detail=result.message or result.error,
            error_class=result.error_class,
        )
    return jsonify(result.payload)


@bp.post("/settings/channels/<channel>/bind")
def api_start_bind(channel: str) -> Any:
    _enforce_loopback_addr()
    if _transport_guards_active():
        _refuse_when_allow_network()
        _check_bind_origin_or_abort()
    return _render(BindAPI().start(channel))


@bp.get("/settings/channels/<channel>/bind/<job_id>")
def api_poll_bind(channel: str, job_id: str) -> Any:
    _enforce_loopback_addr()
    return _render(BindAPI().poll(channel, job_id))


@bp.post("/settings/channels/<channel>/identity-mismatch/keep")
def api_identity_mismatch_keep(channel: str) -> Any:
    _enforce_loopback_addr()
    if _transport_guards_active():
        _refuse_when_allow_network()
        _check_bind_origin_or_abort()
    return _render(BindAPI().resolve_keep(channel))


@bp.post("/settings/channels/<channel>/identity-mismatch/replace")
def api_identity_mismatch_replace(channel: str) -> Any:
    _enforce_loopback_addr()
    if _transport_guards_active():
        _refuse_when_allow_network()
        _check_bind_origin_or_abort()
    return _render(BindAPI().resolve_replace(channel))
