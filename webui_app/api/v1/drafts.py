"""Draft-queue endpoints for ``/api/v1`` — Plan 2026-06-18-002 U7 (drafts page).

Migrates the draft queue off the legacy ``/ce:draft/*`` routes (302 + flash).
REUSES the existing ``DraftAPI`` facade (drafts_store + APScheduler job wiring) —
the schedule alignment, staggering and job-removal rollback stay single-source.

Stateless + SPA-friendly: every mutation returns the refreshed ``{items: [...]}``.

Error mapping mirrors DraftAPI's own honour-operator-intent semantics:
  * ok                          → 200 + refreshed list (+ message)
  * SCHEDULER_SYNC_FAILED       → 200 + refreshed list + WARNING message — the
    store mutation succeeded (the draft IS cancelled/deleted); only the
    background job couldn't be removed, which is a caveat, not a failure.
  * PERSISTENCE_FAILURE         → 502 problem+json (nothing changed)
  * missing/!valid params       → 422 problem+json
"""

from __future__ import annotations

from flask import jsonify, request

from ..drafts_api import DraftAPI
from . import bp
from .errors import ApiProblem

_api = DraftAPI()


def _require_id(data: dict) -> str:
    item_id = str(data.get("id") or "").strip()
    if not item_id:
        raise ApiProblem(
            422, "Missing id", detail="`id` is required.", error_class="invalid_request"
        )
    return item_id


def _raise_if_hard_failure(result: dict) -> None:
    """Raise problem+json only for genuine failures.

    A SCHEDULER_SYNC_FAILED is a soft-success (store mutated, job lingered) and is
    surfaced as a warning in the refreshed response, not an error.
    """
    if result.get("ok") or result.get("error_code") == "SCHEDULER_SYNC_FAILED":
        return
    code = result.get("error_code")
    status = 502 if code == "PERSISTENCE_FAILURE" else 422
    raise ApiProblem(
        status,
        "Draft operation failed",
        detail=result.get("flash_msg"),
        error_class=(code or "invalid_request").lower(),
    )


def _refreshed(result: dict):
    return jsonify({"items": _api.list_all(), "message": result.get("flash_msg", "")})


@bp.get("/drafts")
def drafts_list():
    """Full draft-queue list (newest first)."""
    return jsonify({"items": _api.list_all()})


@bp.post("/drafts/schedule")
def drafts_schedule():
    """Schedule a draft at an ISO-8601 datetime → refreshed list."""
    data = request.get_json(silent=True) or {}
    item_id = _require_id(data)
    result = _api.schedule(item_id, str(data.get("scheduled_at") or ""))
    _raise_if_hard_failure(result)
    return _refreshed(result)


@bp.post("/drafts/publish-now")
def drafts_publish_now():
    """Publish a draft now (schedules ~5s out) → refreshed list."""
    item_id = _require_id(request.get_json(silent=True) or {})
    result = _api.publish_now(item_id)
    _raise_if_hard_failure(result)
    return _refreshed(result)


@bp.post("/drafts/cancel")
def drafts_cancel():
    """Cancel a scheduled draft (back to pending) → refreshed list."""
    item_id = _require_id(request.get_json(silent=True) or {})
    result = _api.cancel(item_id)
    _raise_if_hard_failure(result)
    return _refreshed(result)


@bp.post("/drafts/delete")
def drafts_delete():
    """Delete one draft (cancels its job if scheduled) → refreshed list."""
    item_id = _require_id(request.get_json(silent=True) or {})
    result = _api.delete(item_id)
    _raise_if_hard_failure(result)
    return _refreshed(result)


@bp.post("/drafts/bulk-delete")
def drafts_bulk_delete():
    """Delete multiple drafts → refreshed list."""
    data = request.get_json(silent=True) or {}
    ids = data.get("ids")
    if not isinstance(ids, list) or not ids:
        raise ApiProblem(
            422, "Missing ids", detail="`ids` must be a non-empty array.",
            error_class="invalid_request",
        )
    result = _api.bulk_delete([str(i) for i in ids])
    _raise_if_hard_failure(result)
    return _refreshed(result)
