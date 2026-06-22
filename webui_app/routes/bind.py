"""Channel binding routes — Plan 2026-05-19-001 Unit 4 + Plan 003 Unit 4.

POST /settings/channels/<channel>/bind                       — start a bind job
GET  /settings/channels/<channel>/bind/<job_id>              — poll status + events
POST /settings/channels/<channel>/identity-mismatch/keep     — keep old account (Plan 003)
POST /settings/channels/<channel>/identity-mismatch/replace  — replace + force re-bind (Plan 003)

As of Plan 2026-06-18-002 U7 (Settings security increment) the bind logic — the
identity_mismatch TOCTOU guard, the atomic keep/restore closure, and the replace
artifact-wipe — was **moved** into ``webui_app.api.bind_api.BindAPI`` (single
source). These routes are now thin HTML/JSON bindings; the JSON siblings live at
``/api/v1/settings/channels/<channel>/bind*`` and call the same facade.

All POST routes:
  - loopback-only (Blueprint-scoped ``before_request`` + inline guards)
  - require a valid CSRF token (via app-level ``_global_csrf_guard``)
  - reject under ``BACKLINK_PUBLISHER_ALLOW_NETWORK=1`` (Plan 003 Unit 3)
  - validate channel against CHANNELS before any state change (defense in depth
    against ``channel=../traversal``) — now enforced inside the facade.

Identity-mismatch resolution semantics (keep = restore-or-expire, never destroy;
replace = wipe + unbound) are documented on ``BindAPI``.
"""

from __future__ import annotations

from flask import Blueprint, abort, jsonify, redirect, request

from ..api.bind_api import BindAPI
from ..helpers.security import (
    _check_bind_origin_or_abort,
    _LOOPBACK_HOSTS,
    _refuse_when_allow_network,
)


bp = Blueprint("bind", __name__)


@bp.before_request
def _enforce_loopback() -> None:
    if request.remote_addr not in _LOOPBACK_HOSTS:
        abort(403)


def _legacy_json_error(result):
    """Render a facade failure the way the legacy routes always have: unknown
    channel → abort(400); otherwise the ``{"status":"error", ...}`` envelope."""
    if result.error_class == "bad_channel":
        abort(400)
    if result.error_class == "not_found":
        abort(404)
    body = {"status": "error", "error": result.error}
    if result.message:
        body["message"] = result.message
    return jsonify(body), result.status


@bp.route("/settings/channels/<channel>/bind", methods=["POST"])
def start_bind(channel: str):
    _refuse_when_allow_network()
    _check_bind_origin_or_abort()
    result = BindAPI().start(channel)
    if not result.ok:
        return _legacy_json_error(result)
    return jsonify(result.payload)


@bp.route("/settings/channels/<channel>/bind/<job_id>", methods=["GET"])
def poll_bind(channel: str, job_id: str):
    result = BindAPI().poll(channel, job_id)
    if not result.ok:
        return _legacy_json_error(result)
    return jsonify(result.payload)


@bp.route("/settings/channels/<channel>/identity-mismatch/keep", methods=["POST"])
def identity_mismatch_keep(channel: str):
    _refuse_when_allow_network()
    _check_bind_origin_or_abort()
    result = BindAPI().resolve_keep(channel)
    if not result.ok:
        return _legacy_json_error(result)
    return redirect("/settings")


@bp.route("/settings/channels/<channel>/identity-mismatch/replace", methods=["POST"])
def identity_mismatch_replace(channel: str):
    _refuse_when_allow_network()
    _check_bind_origin_or_abort()
    result = BindAPI().resolve_replace(channel)
    if not result.ok:
        return _legacy_json_error(result)
    return redirect("/settings")
