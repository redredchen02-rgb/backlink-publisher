"""LLM settings route handlers — thin bindings over the LLM settings + diagnostics facades.

As of Plan 2026-06-18-002 U7 the save logic moved to ``api.llm_settings_api`` and
the connection/generation diagnostics to ``api.llm_diagnostics_api`` (single source).
These routes are now thin: save → flash-redirect, the two diagnostics → JSON.
"""
import requests  # noqa: F401 — retained as the patch surface for the SSRF redirect
# tests in test_webui_unit3_security.py, which patch
# ``webui_app.routes.llm.requests.{get,post}`` (a global-module handle that also
# reaches http_guard's safe_post_json + the diagnostics facade's _safe_get_json).

from flask import Blueprint, jsonify, request

# Lift-parity re-exports: test_llm_client.py asserts ``_guard_llm_endpoint`` /
# ``_safe_post_json`` resolve from routes.llm, and test_webui_unit3_security.py
# imports ``_safe_get_json`` / ``_safe_post_json`` here. The SSRF helpers' canonical
# home is http_guard; _safe_get_json lives in the diagnostics facade.
from backlink_publisher.llm.http_guard import (  # noqa: F401
    guard_llm_endpoint as _guard_llm_endpoint,
    safe_post_json as _safe_post_json,
)

from ..api.llm_diagnostics_api import LlmDiagnosticsAPI, _safe_get_json  # noqa: F401
from ..api.llm_settings_api import LlmSettingsAPI
from ..helpers.security import _safe_flash_redirect

bp = Blueprint("llm", __name__)


@bp.route('/settings/save-llm-config', methods=['POST'])
def settings_save_llm_config():
    """Save (or clear) LLM / image-gen settings — delegates to the single-source
    facade, then renders the neutral result as a flash-redirect."""
    r = LlmSettingsAPI().save(request.form)
    return _safe_flash_redirect('/settings', flash_type=r.level, msg=r.message,
                                fragment=r.fragment)


@bp.route('/settings/test-llm-connection', methods=['POST'])
def settings_test_llm():
    """Run the SSRF-guarded connection probe + persist last-known health."""
    r = LlmDiagnosticsAPI().test_connection(request.form)
    return jsonify(r.payload), r.http_status


@bp.route('/settings/test-llm-generation', methods=['POST'])
def settings_preview_llm():
    """Generate an article/anchor preview from the stored LLM settings."""
    r = LlmDiagnosticsAPI().test_generation(request.form)
    return jsonify(r.payload), r.http_status
