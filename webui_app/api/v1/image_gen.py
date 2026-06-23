"""Image-gen (AI cover) diagnostics for ``/api/v1`` — Plan 2026-06-18-002 U7.

JSON siblings of the legacy ``/settings/{test-image-gen,generate-sample-image}``
routes. Both transports call the SAME facade (``ImageGenDiagnosticsAPI``) — the
provider dispatch (OpenAI /models vs FRW /balance) and the sample generation are
single-sourced there.

No inline transport guard (matches the legacy posture + the LLM-diagnostics
siblings): these are operator-configured connectivity probes / a generation
preview, NOT 0600 credential writes. They are covered at runtime by the app-level
``_global_origin_guard``. The diagnostic envelope (``{"ok": bool, ...}``) is the
contract the SPA branches on, returned as-is (NOT RFC 9457 problem+json).
"""

from __future__ import annotations

from flask import jsonify, request

from ..image_gen_diagnostics_api import ImageGenDiagnosticsAPI
from . import bp


def _json_body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


@bp.post("/settings/image-gen/test-connection")
def settings_test_image_gen():
    """Probe the configured image-gen endpoint (no generation cost)."""
    r = ImageGenDiagnosticsAPI().test_connection()
    return jsonify(r.payload), r.http_status


@bp.post("/settings/image-gen/generate-sample")
def settings_generate_sample_image():
    """Generate one real banner from config + the optional ``prompt`` body field."""
    r = ImageGenDiagnosticsAPI().generate_sample(_json_body())
    return jsonify(r.payload), r.http_status
