"""Channel overview (read-only) for ``/api/v1`` — Plan 2026-06-18-002 U7.

``GET /api/v1/settings/channels`` — the per-channel binding status list the SPA
settings page's channel section hydrates from. Single-sourced via
``ChannelOverviewAPI`` (registry − hidden_from_ui ∘ get_channel_status).

``GET /api/v1/settings/channels/forms`` — the per-channel binding-FORM schemas
(which fields to render for each fixed-credential channel). Static metadata via
``ChannelFormsAPI``; the SPA joins it with the overview's bind-state by slug.

No inline guard: both are reads with no secrets (the per-channel credential WRITES
under ``/api/v1/settings/channels/<channel>/…`` keep their inline guards). Like the
other settings GETs they reveal only operator-facing config, not credentials — the
form schema carries field NAMES and labels, never values.
"""

from __future__ import annotations

from flask import jsonify

from ..channel_forms_api import ChannelFormsAPI
from ..channel_overview_api import ChannelOverviewAPI
from . import bp


@bp.get("/settings/channels")
def settings_list_channels():
    """List every WebUI-visible channel with its binding status."""
    return jsonify({"channels": ChannelOverviewAPI().list_channels()})


@bp.get("/settings/channels/forms")
def settings_list_channel_forms():
    """List the binding-form schema for every fixed-credential channel."""
    return jsonify({"forms": ChannelFormsAPI().list_forms()})
