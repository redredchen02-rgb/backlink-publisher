"""Async operation endpoints for ``/api/v1`` — Plan 2026-07-09 (U1).

Submit a pipeline operation (publish / publish-chain / plan / validate) and
get an ``op_id`` back immediately; the work runs in a background worker thread
(``webui_app.services.operation_worker``) while the SPA polls
``GET /api/v1/operations/<op_id>`` for stage + progress. This replaces the
synchronous ``/api/v1/pipeline/publish`` block (up to 300s) with a pollable
job, so the operator always knows what the tool is doing.

Behaviour parity with the legacy publish path is preserved: same
``PipelineAPI`` call, same ``publish_state_summary`` aggregation, same history
side-effects, and the same Velog credential guard.
"""

from __future__ import annotations

from typing import Any

from flask import current_app, jsonify, request

from webui_store import operation_store

from . import bp
from .errors import ApiProblem

_VALID_KINDS = ("plan", "validate", "publish", "publish_chain")


@bp.post("/operations")
def create_operation() -> Any:
    """Enqueue an async operation; returns ``{"op_id": ...}`` (HTTP 202)."""
    data = request.get_json(silent=True) or {}
    kind = data.get("kind")
    if kind not in _VALID_KINDS:
        raise ApiProblem(
            422, "Invalid kind",
            detail=f"`kind` must be one of {list(_VALID_KINDS)}.",
            error_class="invalid_request",
        )

    cfg = {k: v for k, v in data.items() if k != "kind"}

    if kind == "publish":
        if "plans" not in data:
            raise ApiProblem(
                422, "Missing plans",
                detail="`plans` is required for a publish operation.",
                error_class="invalid_request",
            )
        platform = data.get("platform")
        if not platform:
            raise ApiProblem(
                422, "Missing platform",
                detail="`platform` is required for a publish operation.",
                error_class="invalid_request",
            )
        _guard_velog(platform)
    elif kind == "publish_chain":
        if not data.get("urls"):
            raise ApiProblem(
                422, "Missing urls",
                detail="`urls` is required for a publish-chain operation.",
                error_class="invalid_request",
            )
        platform = data.get("platform")
        if not platform:
            raise ApiProblem(
                422, "Missing platform",
                detail="`platform` is required for a publish-chain operation.",
                error_class="invalid_request",
            )
        _guard_velog(platform)

    op_id = operation_store.create(kind=kind, cfg=cfg)

    worker = current_app.config.get("OPERATION_WORKER")
    if worker is None:
        # Worker not started (e.g. unit test without app factory startup).
        # Fail closed rather than silently dropping the op.
        operation_store.update_fields(
            op_id, status="failed", error="operation worker unavailable"
        )
        raise ApiProblem(
            503, "Operation worker unavailable",
            detail="The background operation worker is not running.",
            error_class="service_unavailable",
        )

    try:
        worker.start(op_id, kind, cfg)
    except Exception as exc:  # noqa: BLE001 — AlreadyRunningError etc.
        operation_store.update_fields(op_id, status="failed", error=str(exc))
        raise ApiProblem(
            409, "Operation not started",
            detail=str(exc), error_class="operation_conflict",
        ) from exc

    return jsonify({"op_id": op_id, "kind": kind}), 202


@bp.get("/operations")
def list_operations() -> Any:
    """List recent operations (newest first), optional ``?limit=``."""
    try:
        limit = int(request.args.get("limit", 50))
    except (TypeError, ValueError):
        limit = 50
    limit = max(1, min(limit, 200))
    ops = operation_store.list(limit=limit)
    return jsonify({"operations": ops, "count": len(ops)})


@bp.get("/operations/<op_id>")
def get_operation(op_id: str) -> Any:
    """Poll an operation's current state."""
    op = operation_store.get(op_id)
    if op is None:
        raise ApiProblem(
            404, "Operation not found",
            detail=f"No operation with id {op_id}.", error_class="not_found",
        )

    worker = current_app.config.get("OPERATION_WORKER")
    running = False
    done = True
    if worker is not None:
        status = worker.get_status(op_id)
        if status is not None:
            running = bool(status.get("_running"))
            done = bool(status.get("_done"))

    return jsonify({
        "op_id": op.get("op_id"),
        "kind": op.get("kind"),
        "status": op.get("status"),
        "stage": op.get("stage"),
        "stages": op.get("stages", []),
        "progress_pct": op.get("progress_pct", 0.0),
        "detail": op.get("detail"),
        "result": op.get("result"),
        "error": op.get("error"),
        "created_at": op.get("created_at"),
        "updated_at": op.get("updated_at"),
        "running": running,
        "done": done,
    })


@bp.post("/operations/<op_id>/cancel")
def cancel_operation(op_id: str) -> Any:
    """Request cancellation of a running operation."""
    op = operation_store.get(op_id)
    if op is None:
        raise ApiProblem(
            404, "Operation not found",
            detail=f"No operation with id {op_id}.", error_class="not_found",
        )
    if op.get("status") in ("success", "failed", "canceled"):
        return jsonify({"op_id": op_id, "status": op.get("status"), "canceled": False})

    worker = current_app.config.get("OPERATION_WORKER")
    if worker is None:
        raise ApiProblem(
            503, "Operation worker unavailable",
            detail="The background operation worker is not running.",
            error_class="service_unavailable",
        )
    canceled = worker.cancel(op_id)
    return jsonify({"op_id": op_id, "status": "canceled", "canceled": canceled})


def _guard_velog(platform: str) -> None:
    """Reject publish/chain for Velog when credentials are invalid (parity)."""
    if platform != "velog":
        return
    from ...helpers.contexts import _get_velog_status

    velog_status = _get_velog_status()
    if velog_status.get("state") not in ("ok", "fresh"):
        detail = velog_status.get("guide") or velog_status.get("label") or ""
        raise ApiProblem(
            400, "Velog credentials invalid",
            detail=f"请先在设置页重新绑定 Velog 凭证。{detail}".strip(),
            error_class="velog_credentials_invalid",
        )
