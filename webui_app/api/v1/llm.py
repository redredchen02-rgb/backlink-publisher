"""LLM / image-gen settings save for ``/api/v1`` — Plan 2026-06-18-002 U7.

JSON sibling of the legacy ``/settings/save-llm-config`` route. Both call the
SAME facade (``LlmSettingsAPI``) — the https gates, blank-secret-preserve,
image-gen validation and the pipeline-config bridge are single-sourced there.

This writes ``llm-settings.json`` at ``0600`` (``api_key`` is a long-term secret),
so it joins the inline-guarded credential-write family: the ``api_v1`` blueprint
does NOT inherit a loopback ``before_request``, so the transport guards are
enforced INLINE here (gated on CSRF config, like the other credential writes), and
a transport-layer regression battery (forged Origin → 403, ALLOW_NETWORK=1 → 403)
gates them.

Scope: the save route only. ``test-llm-connection`` / ``test-llm-generation``
already return JSON and carry heavy SSRF-internal test patching; they migrate
later.
"""

from __future__ import annotations

from typing import Any

from flask import jsonify, request

from ...helpers.security import _check_bind_origin_or_abort, _refuse_when_allow_network
from ..llm_diagnostics_api import LlmDiagnosticsAPI
from ..llm_settings_api import LlmSettingsAPI
from . import bp
from .errors import ApiProblem
from .settings_credentials import _transport_guards_active


def _json_body() -> Any:
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def _render(result: Any) -> Any:
    if result.error_class == "invalid_request":
        raise ApiProblem(422, "LLM settings rejected", detail=result.message,
                         error_class="invalid_request")
    if result.error_class == "persistence_failure":
        raise ApiProblem(502, "LLM settings save failed", detail=result.message,
                         error_class="persistence_failure")
    return jsonify({"ok": True, "message": result.message})


@bp.get("/settings/llm-config")
def settings_get_llm_config() -> Any:
    """Hydrate the LLM/image-gen settings form. Redaction-safe: the two secrets are
    returned only as ``has_*`` booleans, never the key itself (no inline guard
    needed — no secret crosses the wire; matches the other settings GETs)."""
    return jsonify(LlmSettingsAPI().get_config())


@bp.post("/settings/llm-config")
def settings_save_llm_config() -> Any:
    """Save (or clear, via ``{"action": "clear"}``) LLM / image-gen settings.

    Body mirrors the legacy form fields (endpoint / api_key / model / temperature
    / system_prompt / use_article_gen / image_gen_* / use_image_gen). Checkbox
    fields are real JSON booleans here; blank secrets preserve the stored value.
    """
    # THREAT-3: writes a 0600 secret file; the api_v1 blueprint does not inherit a
    # loopback before_request, so enforce the transport guards inline. Both abort(403).
    if _transport_guards_active():
        _refuse_when_allow_network()
        _check_bind_origin_or_abort()
    return _render(LlmSettingsAPI().save(_json_body()))


# ── diagnostics (no inline guard — match the legacy posture; the diagnostic
#    envelope {status,message,models|result|reason} is the contract the SPA
#    branches on, not RFC 9457; covered at runtime by the global origin guard) ──


@bp.post("/settings/llm/test-connection")
def settings_test_llm_connection() -> Any:
    """SSRF-guarded connection probe + best-effort last-known-health persist."""
    r = LlmDiagnosticsAPI().test_connection(_json_body())
    return jsonify(r.payload), r.http_status


@bp.post("/settings/llm/test-generation")
def settings_test_llm_generation() -> Any:
    """Article/anchor generation preview from the stored LLM settings."""
    r = LlmDiagnosticsAPI().test_generation(_json_body())
    return jsonify(r.payload), r.http_status
