"""Publish-history endpoints for ``/api/v1`` — Plan 2026-06-18-002 U7.

Migrates the history page off the legacy ``/ce:history*`` routes (which
re-rendered ``index.html`` or 302'd with a flash). REUSES the existing
``HistoryAPI`` facade (events.db read + recheck/delete/purge) — no
reimplementation; the row normalisation, recheck service and dual-store writes
stay a single source of truth.

Stateless + SPA-friendly: every mutation returns the refreshed ``{items: [...]}``
so the Pinia store just replaces its list. Validation / not-found surface as RFC
9457 problem+json (replacing the legacy all-200 re-render / flash redirect).
"""

from __future__ import annotations

from typing import Any

from flask import jsonify, request

from ..history_api import HistoryAPI
from . import bp
from .errors import ApiProblem, require_ids

_api = HistoryAPI()


def _require_id(data: dict) -> str:
    item_id = str(data.get("id") or "").strip()
    if not item_id:
        raise ApiProblem(
            422, "Missing id", detail="`id` is required.", error_class="invalid_request"
        )
    return item_id


def _parse_include_deleted() -> str | None:
    """Parse ``?include_deleted=`` (D18) -- only ``"window"`` is recognised.

    Any other non-empty value is a caller bug, not silently ignored
    (quarantine-not-silent-else): reject it with 422 rather than falling
    back to the default filter and hiding the mistake from the caller.
    CLI read paths never pass this parameter at all.
    """
    raw = request.args.get("include_deleted")
    if raw is None or raw == "":
        return None
    if raw != "window":
        raise ApiProblem(
            422, "Invalid include_deleted value",
            detail="`include_deleted` only accepts 'window'.",
            error_class="invalid_request",
        )
    return raw


@bp.get("/history")
def history_list() -> Any:
    """Full publish-history list (events.db, normalised).

    ``?include_deleted=window`` (D18) returns soft-deleted rows still
    within the undo window instead of the live list, each with
    ``deleted_at`` populated for the WebUI's undo affordance.
    """
    return jsonify({"items": _api.list(include_deleted=_parse_include_deleted())})


@bp.post("/history/delete")
def history_delete() -> Any:
    """Soft-delete one history entry → refreshed list (undo-able within the purge window)."""
    item_id = _require_id(request.get_json(silent=True) or {})
    result = _api.delete(item_id)
    return jsonify({"items": result.get("history", _api.list())})


@bp.post("/history/undelete")
def history_undelete() -> Any:
    """Restore a soft-deleted history entry → refreshed list.

    404 problem+json when the id doesn't exist, was never deleted, or
    already aged past the purge window -- never a silent 200 success.
    """
    item_id = _require_id(request.get_json(silent=True) or {})
    result = _api.undelete(item_id)
    if not result.get("ok"):
        raise ApiProblem(
            404, "History item not found",
            detail=result.get("flash_msg"),
            error_class=result.get("error_code", "not_found"),
        )
    return jsonify({"items": result.get("history", _api.list())})


@bp.post("/history/bulk-delete")
def history_bulk_delete() -> Any:
    """Soft-delete multiple history entries → refreshed list.

    Response additionally carries ``deleted``/``skipped`` counts (additive,
    oasdiff-safe) -- a partially-stale selection (some ids already gone)
    reports honestly instead of an all-or-nothing result.
    """
    ids = require_ids(request.get_json(silent=True) or {})
    result = _api.bulk_delete(ids)
    return jsonify({
        "items": _api.list(),
        "message": result.get("flash_msg", ""),
        "deleted": result.get("deleted", 0),
        "skipped": result.get("skipped", 0),
    })


@bp.post("/history/purge-failed")
def history_purge_failed() -> Any:
    """Delete every ``failed`` entry → refreshed list. No-op is a 200, not an error."""
    result = _api.purge_failed()
    return jsonify({"items": _api.list(), "message": result.get("flash_msg", "")})


@bp.post("/history/recheck")
def history_recheck() -> Any:
    """Re-verify one history entry's link liveness → refreshed list."""
    item_id = _require_id(request.get_json(silent=True) or {})
    result = _api.recheck(item_id)
    if not result.get("ok"):
        raise ApiProblem(
            404, "History item not found", detail=result.get("flash_msg"),
            error_class="not_found",
        )
    return jsonify({"items": _api.list(), "message": result.get("flash_msg", "")})


@bp.post("/history/bulk-recheck")
def history_bulk_recheck() -> Any:
    """Re-verify multiple history entries' link liveness → refreshed list.

    Plan 2026-07-02-001 U3. A per-item verify outcome (e.g. a URL now dead) is
    data, not an API failure -- ``HistoryAPI.bulk_recheck`` only returns
    ``ok: False`` for genuine input problems (empty/unmatched ids), which is
    honestly surfaced as 422 rather than a fake 200.
    """
    ids = require_ids(request.get_json(silent=True) or {})
    result = _api.bulk_recheck(ids)
    if not result.get("ok"):
        raise ApiProblem(
            422, "Bulk recheck failed", detail=result.get("flash_msg"),
            error_class="invalid_request",
        )
    return jsonify({"items": _api.list(), "message": result.get("flash_msg", "")})
