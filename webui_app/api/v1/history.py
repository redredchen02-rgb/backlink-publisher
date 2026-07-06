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
from .errors import ApiProblem, paginate, parse_pagination

_api = HistoryAPI()


def _require_id(data: dict) -> str:
    item_id = str(data.get("id") or "").strip()
    if not item_id:
        raise ApiProblem(
            422, "Missing id", detail="`id` is required.", error_class="invalid_request"
        )
    return item_id


def _require_ids(data: dict) -> list[str]:
    ids = data.get("ids")
    if not isinstance(ids, list) or not ids:
        raise ApiProblem(
            422, "Missing ids", detail="`ids` must be a non-empty array.",
            error_class="invalid_request",
        )
    return [str(i) for i in ids]


@bp.get("/history")
def history_list() -> Any:
    """Publish-history list (events.db, normalised).

    Plan 2026-07-02-001 U5: opt-in incremental pagination via ``?limit=&offset=``.
    Paginated at this layer, not pushed into the store -- history has dual
    JSON/events.db backends, so store-level pagination would need to fan out
    differently per backend. Omitting ``limit`` returns the original flat
    ``{items: [...]}`` shape (old clients don't break, K6).
    """
    limit, offset = parse_pagination()
    return jsonify(paginate(_api.list(), limit, offset))


@bp.post("/history/delete")
def history_delete() -> Any:
    """Delete one history entry → refreshed list."""
    item_id = _require_id(request.get_json(silent=True) or {})
    result = _api.delete(item_id)
    return jsonify({"items": result.get("history", _api.list())})


@bp.post("/history/bulk-delete")
def history_bulk_delete() -> Any:
    """Delete multiple history entries → refreshed list."""
    ids = _require_ids(request.get_json(silent=True) or {})
    result = _api.bulk_delete(ids)
    return jsonify({"items": _api.list(), "message": result.get("flash_msg", "")})


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
