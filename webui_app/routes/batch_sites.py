"""Batch site operations — POST /sites/batch-queue + GET /sites/batch-status
(Plan 2026-06-09-001 U6).
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from webui_store.batch_ops import VALID_OPERATIONS

bp = Blueprint("batch_sites", __name__)


@bp.route("/sites/batch-queue", methods=["POST"])
def post_batch_queue():
    """Queue a batch operation for a list of site URLs.

    Accepts JSON body ``{site_urls: [...], operation: str}``.
    Returns 400 for empty site_urls, 422 for unknown operation, 202 on success.
    """
    from webui_store import batch_ops_store

    body = request.get_json(silent=True, force=True) or {}
    site_urls = body.get("site_urls") or []
    operation = body.get("operation") or ""

    if not site_urls:
        return jsonify({"error": "site_urls must be a non-empty list"}), 400
    if not isinstance(site_urls, list):
        return jsonify({"error": "site_urls must be a list"}), 400
    if operation not in VALID_OPERATIONS:
        return jsonify({
            "error": f"unknown operation '{operation}'; valid: {sorted(VALID_OPERATIONS)}"
        }), 422

    ids = batch_ops_store.enqueue_many(site_urls, operation)
    return jsonify({"queued": len(ids), "ids": ids}), 202


@bp.route("/sites/batch-status", methods=["GET"])
def get_batch_status():
    """Return recent batch operation rows for frontend polling.

    Query param ``limit`` (default 100) caps row count.
    """
    from webui_store import batch_ops_store

    try:
        limit = int(request.args.get("limit", 100))
        limit = max(1, min(limit, 500))
    except (ValueError, TypeError):
        limit = 100

    rows = batch_ops_store.list_status(limit=limit)
    return jsonify({"rows": rows})
