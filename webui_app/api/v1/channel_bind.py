"""General channel credential write for ``/api/v1`` — Plan 2026-06-18-002 U7.

JSON sibling of the legacy ``/settings/save-channel-credential`` HTML route. Both
bindings call the SAME facade (``ChannelBindAPI``) — the 5-way auth-type dispatch
and every validation (SSRF, paste-blob schema + domain, hostname format) live
there as a single source, so this port could not silently drop a gate.

This endpoint writes ``0600`` secret files, so it is on the plan's THREAT-3
surface. The ``api_v1`` blueprint does NOT inherit the legacy ``bind`` blueprint's
``before_request``, so the transport guards (``_refuse_when_allow_network`` /
``_check_bind_origin_or_abort``) are enforced INLINE here — gated on CSRF config
(off in the broad suite, on in production and the security regression battery),
mirroring ``settings_credentials.py``. A transport-layer regression suite asserts
forged Origin → 403 and ``ALLOW_NETWORK=1`` → 403 before any write.
"""

from __future__ import annotations

import json

from flask import jsonify, request

from ...helpers.security import _check_bind_origin_or_abort, _refuse_when_allow_network
from ..channel_bind_api import BindSaveResult, ChannelBindAPI
from . import bp
from .errors import ApiProblem
from .settings_credentials import _transport_guards_active


def _render(result: BindSaveResult):
    """Translate the neutral facade result to JSON 200 / RFC 9457 problem+json."""
    if result.error_class == "invalid_request":
        raise ApiProblem(422, "Credential rejected", detail=result.message,
                         error_class="invalid_request")
    if result.error_class == "persistence_failure":
        raise ApiProblem(502, "Credential save failed", detail=result.message,
                         error_class="persistence_failure")
    # success (saved) or a clear op (cleared True/False, idempotent) → ok=True;
    # a leave-as-is / anon no-op → ok=False (nothing was written).
    payload = {
        "ok": result.level == "success" or result.cleared is not None,
        "message": result.message,
    }
    if result.cleared is not None:
        payload["cleared"] = result.cleared
    return jsonify(payload)


@bp.post("/settings/channels/<channel>/credential")
def settings_save_channel_credential(channel: str):
    """Save (or clear) a registry-dispatched channel credential → ``0600`` file.

    Body mirrors the legacy form fields: ``auth_type`` (optional, cross-checked
    against the registry), ``clear`` (truthy to remove), and the auth-type's
    inputs — ``token`` / per-field token_fields / ``blob`` (cookie JSON text) /
    ``username``+``password``.
    """
    # THREAT-3: the api_v1 blueprint does NOT inherit bind.py's before_request,
    # so enforce the transport guards here. Both abort(403).
    if _transport_guards_active():
        _refuse_when_allow_network()
        _check_bind_origin_or_abort()

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        data = {}
    # paste_blob channels expect the cookie JSON as a string (parity with the
    # form route); accept a nested object too by re-serialising it.
    blob = data.get("blob")
    if isinstance(blob, (dict, list)):
        data = {**data, "blob": json.dumps(blob)}

    result = ChannelBindAPI().save_channel_credential(channel=channel, fields=data)
    return _render(result)
