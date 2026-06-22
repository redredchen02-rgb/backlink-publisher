"""Image-gen settings routes — Plan 2026-05-20-001 Unit 6.

Thin HTML bindings; the connectivity probe + sample-generation logic was moved to
the single-source ``ImageGenDiagnosticsAPI`` facade (Plan 2026-06-18-002 U7) and is
shared with the ``/api/v1/settings/image-gen/*`` JSON routes.

  * ``/settings/test-image-gen`` — connectivity probe (no generation cost).
  * ``/settings/generate-sample-image`` — real generation call; returns the
    image as a base64 data-URL for preview in the settings UI.
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request

# Re-export for the lift-parity tests: ``patch("...routes.image_gen.http_client.get")``
# patches the shared singleton the facade probes call (same object via either
# namespace), so the legacy probe tests keep working after the move to the facade.
from backlink_publisher._util.http_client import http_client  # noqa: F401

from ..api.image_gen_diagnostics_api import ImageGenDiagnosticsAPI

bp = Blueprint("image_gen", __name__)


@bp.route("/settings/test-image-gen", methods=["POST"])
def settings_test_image_gen():
    """Probe the configured image-gen endpoint and return connection status."""
    return jsonify(ImageGenDiagnosticsAPI().test_connection().payload), 200


@bp.route("/settings/generate-sample-image", methods=["POST"])
def settings_generate_sample_image():
    """Generate a real test banner and return it as a base64 data-URL (one API call)."""
    body = request.get_json(silent=True) or {}
    return jsonify(ImageGenDiagnosticsAPI().generate_sample(body).payload), 200
