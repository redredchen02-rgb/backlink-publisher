"""Batch-campaign creation endpoints for ``/api/v1`` — Plan 2026-06-18-002 U7.

Migrates the ``/batch-campaign`` form off the legacy Jinja route (render / 302).
REUSES the ``CampaignAPI`` facade — seed/platform/mode/cap/delay validation and
``campaign_store.create`` + CampaignWorker dispatch stay single-source.

Stateless + SPA-friendly: validation failure is a 422 problem+json carrying
per-field ``errors[]``; success returns ``{campaign_id}`` so the SPA navigates
to the (separately-migrated) ``/campaign/<id>`` progress page.
"""

from __future__ import annotations

from typing import Any

from flask import jsonify, request

from ..campaign_api import CampaignAPI
from . import bp
from .errors import ApiProblem

_api = CampaignAPI()


@bp.get("/campaigns/form")
def campaigns_form() -> Any:
    """Bootstrap for the creation form: platforms + connection-state partition."""
    return jsonify(_api.form_bootstrap())


@bp.post("/campaigns")
def campaigns_create() -> Any:
    """Validate + create a campaign → ``{campaign_id}``.

    Field validation failures surface as a 422 problem+json with ``errors[]``
    (the SPA renders them inline); success returns the new campaign id.
    """
    data = request.get_json(silent=True) or {}
    result = _api.create(data)
    if not result.get("ok"):
        raise ApiProblem(
            422,
            "Campaign request is invalid",
            detail="请修正下方表单错误",
            error_class="invalid_request",
            errors=[{"field": f, "message": m} for f, m in result.get("errors", {}).items()],
        )
    return jsonify({"campaign_id": result["campaign_id"]})
