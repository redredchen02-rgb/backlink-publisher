"""Global (non-channel) settings saves for ``/api/v1`` — Plan 2026-06-18-002 U7.

JSON siblings of the legacy ``/settings/save-target-keywords`` + ``/settings/schedule``
routes. Both transports call the SAME facade (``GlobalSettingsAPI``) — the keyword
>60-reject / de-dup and the schedule parse / clamp are single-sourced there.

  POST /api/v1/settings/keywords  — body {"pools": {"<domain>": ["kw", ...]}}
  POST /api/v1/settings/schedule  — body {"min_interval_hours": 4, "jitter_minutes": 30}

No inline transport guard (matches the legacy posture + the OAuth / diagnostics
siblings): these write global config (config.toml / schedule-settings.json), NOT
0600 credential files. They are covered at runtime by the app-level
``_global_origin_guard``. Validation failures map to RFC 9457 problem+json
(invalid_request → 422, persistence_failure → 502).
"""

from __future__ import annotations

from flask import jsonify, request

from ..global_settings_api import GlobalSettingsAPI
from . import bp
from .errors import ApiProblem


def _json_body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def _render(result, *, title: str):
    if result.error_class == "invalid_request":
        raise ApiProblem(422, title, detail=result.message, error_class="invalid_request")
    if result.error_class == "persistence_failure":
        raise ApiProblem(502, title, detail=result.message, error_class="persistence_failure")
    return jsonify({"ok": True, "message": result.message})


@bp.get("/settings/keywords")
def settings_get_keywords():
    """Hydrate the keyword-pool editor: known target domains + current pools."""
    return jsonify(GlobalSettingsAPI().get_keywords())


@bp.get("/settings/schedule")
def settings_get_schedule():
    """Hydrate the publish-cadence form."""
    return jsonify(GlobalSettingsAPI().get_schedule())


@bp.post("/settings/keywords")
def settings_save_keywords():
    """Save the per-domain SEO anchor keyword pools."""
    pools = _json_body().get("pools")
    if not isinstance(pools, dict):
        pools = {}
    return _render(GlobalSettingsAPI().save_keywords(pools), title="Keyword pools rejected")


@bp.post("/settings/schedule")
def settings_save_schedule():
    """Save the publish-cadence (min interval / jitter) settings."""
    return _render(GlobalSettingsAPI().save_schedule(_json_body()), title="Schedule settings rejected")
