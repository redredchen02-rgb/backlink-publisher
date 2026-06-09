"""Publish defaults + quick-publish routes (Plan 2026-06-09-001 U5 / R12–R14).

GET  /publish/defaults  — return last-used platforms + targets (or 204 if none).
POST /publish/quick     — start publish using stored defaults; 400 if none saved.
POST /publish/save-defaults — update stored defaults (called after normal publish).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request

bp = Blueprint("publish_defaults", __name__)


@bp.route("/publish/defaults", methods=["GET"])
def get_publish_defaults():
    """Return last-used publish defaults (R12).

    Returns 200 + JSON ``{platforms: [...], target_ids: [...]}`` when defaults
    exist, or 204 No Content when no defaults have been saved yet.
    """
    from webui_store import publish_defaults_store

    data = publish_defaults_store.load()
    if not data or not data.get("last_platforms"):
        return "", 204
    return jsonify({
        "platforms": data.get("last_platforms", []),
        "target_ids": data.get("last_target_ids", []),
    })


@bp.route("/publish/quick", methods=["POST"])
def post_publish_quick():
    """Start a publish run using stored defaults (R13).

    Reads defaults from publish_defaults_store; if none saved returns 400.
    If defaults exist, queues a background task via queue_store and returns
    202 with the task_id so the frontend can poll progress (R14).

    The caller may pass ``urls_json`` to override the target URLs; if absent
    the stored target_ids are used as-is (operator must have URLs configured
    in their sites config).
    """
    from webui_store import publish_defaults_store, queue_store

    data = publish_defaults_store.load()
    if not data or not data.get("last_platforms"):
        return jsonify({"error": "no defaults saved"}), 400

    platforms = data.get("last_platforms", [])
    target_ids = data.get("last_target_ids", [])

    # Allow caller to pass explicit urls_json; fall back to stored target_ids
    urls_raw = request.form.get("urls_json") or request.get_json(silent=True, force=True) and request.get_json(silent=True, force=True).get("urls_json")
    if urls_raw:
        import json as _json
        try:
            urls = _json.loads(urls_raw) if isinstance(urls_raw, str) else urls_raw
        except (ValueError, TypeError):
            urls = target_ids
    else:
        urls = target_ids

    task_data = {
        "id": str(uuid.uuid4()),
        "status": "pending",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "config": {"platform": ",".join(platforms)},
        "urls": urls,
        "source": "quick_publish",
    }
    queue_store.update(lambda tasks: tasks + [task_data])

    return jsonify({"status": "queued", "task_id": task_data["id"]}), 202


@bp.route("/publish/save-defaults", methods=["POST"])
def post_save_publish_defaults():
    """Persist last-used platforms + targets after a successful publish (R12).

    Called by the publish pipeline routes after a run is successfully queued.
    Accepts JSON body ``{platforms: [...], target_ids: [...]}``.
    """
    from webui_store import publish_defaults_store

    body = request.get_json(silent=True, force=True) or {}
    platforms = body.get("platforms") or []
    target_ids = body.get("target_ids") or []
    if not isinstance(platforms, list):
        return jsonify({"error": "platforms must be a list"}), 400

    publish_defaults_store.save({
        "last_platforms": platforms,
        "last_target_ids": target_ids,
    })
    return jsonify({"ok": True})
