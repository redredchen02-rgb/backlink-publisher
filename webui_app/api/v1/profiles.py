"""Campaign-profile CRUD endpoints for ``/api/v1`` — Plan 2026-06-18-002 U7.

Converts the legacy ``/profiles/save`` (AJAX ``{ok}``) + ``/profiles/delete``
(form-POST → referrer redirect) routes to the versioned JSON surface. REUSES the
``profiles_store`` singleton directly — the CRUD is trivial (name-keyed upsert /
filter), so no facade is warranted.

Backend-only this unit: profiles is a cross-cutting preset store with NO SPA
consumer today (its live consumer is ``settings.js``). The SPA profile selector
lands with the Settings unit; these endpoints give that migration its contract
ahead of time. Mutations return the refreshed ``{items: [...]}`` (SPA-friendly).
"""

from __future__ import annotations

from typing import Any

from flask import jsonify, request

from webui_store import profiles_store as _store

from . import bp
from .errors import ApiProblem

_PROFILE_FIELDS = ("platform", "language", "url_mode", "publish_mode")
_DEFAULTS = {"platform": "blogger", "language": "zh-CN", "url_mode": "C", "publish_mode": "publish"}


def _require_name(data: dict) -> str:
    name = str(data.get("name") or "").strip()
    if not name:
        raise ApiProblem(
            422, "Missing profile name", detail="`name` is required.",
            error_class="invalid_request",
        )
    return name


@bp.get("/profiles")
def profiles_list() -> Any:
    """All saved campaign profiles."""
    return jsonify({"items": _store.load()})


@bp.post("/profiles/save")
def profiles_save() -> Any:
    """Upsert a campaign profile by name → refreshed list."""
    data = request.get_json(silent=True) or {}
    name = _require_name(data)
    profile_data = {f: str(data.get(f) or _DEFAULTS[f]) for f in _PROFILE_FIELDS}

    def _upsert(profiles: Any) -> Any:
        for p in profiles:
            if p.get("name") == name:
                p.update(profile_data)
                return profiles
        profiles.append({"name": name, **profile_data})
        return profiles

    _store.update(_upsert)
    return jsonify({"items": _store.load()})


@bp.post("/profiles/delete")
def profiles_delete() -> Any:
    """Delete a campaign profile by name → refreshed list."""
    name = _require_name(request.get_json(silent=True) or {})
    _store.update(lambda profiles: [p for p in profiles if p.get("name") != name])
    return jsonify({"items": _store.load()})
