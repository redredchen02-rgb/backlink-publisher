"""/ce:draft/* — Plan Unit 3.

Phase A refactoring: delegates to ``DraftAPI`` for all operations.
"""

from __future__ import annotations

from typing import Any

from flask import Blueprint, request, session

from ..api import DraftAPI
from ..helpers.security import _safe_flash_redirect

bp = Blueprint("drafts", __name__)
_draft = DraftAPI()

# Scheduler-job-removal honesty lives in ``DraftAPI`` (api/drafts_api.py
# ``_remove_scheduled_job``); these routes just surface the result's
# ``flash_type`` ("warning" when a job may still fire).


def _draft_redirect(flash_type: str, flash_msg: str) -> Any:
    """Redirect back to the (legacy) draft tab, sanitizing flash_type/flash_msg
    through ``_safe_flash_redirect`` instead of splicing them into an f-string
    (Plan 2026-07-06-004 Unit 5 / K8).

    ``tab=draft`` is prepended onto the already-sanitized Location header
    rather than passed as part of ``_safe_flash_redirect``'s ``path`` — that
    function concatenates ``path + qs`` where ``qs`` starts with its own
    ``?``, so a path of ``'/?tab=draft'`` would produce an invalid
    ``/?tab=draft?flash_type=...`` double-``?`` URL. ``tab=draft`` itself is a
    static literal (not attacker-controlled), so no extra sanitization is
    needed for it.

    ``tab=draft`` is kept for backward compatibility even though the new SPA
    homepage does not read it (Scope Boundaries: legacy-only, dropped by
    main.py's bare ``/`` → ``/app/`` redirect before it would ever reach the
    SPA). It is still read by main.py's ``/jinja`` fallback route
    (``history_active = tab == 'draft'``), and existing tests
    (tests/test_webui_history_routes.py) assert its literal presence in these
    routes' own Location header, so dropping it here would be an unrelated
    behavior change outside this unit's scope.
    """
    resp = _safe_flash_redirect('/', flash_type=flash_type, msg=flash_msg)
    location = resp.headers.get("Location", "/")
    if location.startswith("/?"):
        resp.headers["Location"] = "/?tab=draft&" + location[2:]
    else:
        resp.headers["Location"] = "/?tab=draft"
    return resp


@bp.route('/ce:draft/save', methods=['POST'])
def ce_draft_save() -> Any:
    """Save current validated plans as a draft queue item."""
    plans_jsonl = request.form.get('plans', '').strip()
    config = session.get('config', {})
    platform = request.form.get('platform', config.get('platform', 'medium'))
    target_url = config.get('target_url', request.form.get('target_url', 'unknown'))
    language = config.get('target_language', 'zh-CN')

    result = _draft.create(
        plans_jsonl, config,
        platform=platform,
        target_url=target_url,
        language=language,
    )
    flash_type = result.get("flash_type") or ("success" if result["ok"] else "danger")
    return _draft_redirect(flash_type, result["flash_msg"])


@bp.route('/ce:draft/schedule', methods=['POST'])
def ce_draft_schedule() -> Any:
    """Schedule a draft item for publishing at a given datetime."""
    item_id = request.form.get('id', '')
    scheduled_at_str = request.form.get('scheduled_at', '')
    result = _draft.schedule(item_id, scheduled_at_str)
    flash_type = result.get("flash_type") or ("success" if result["ok"] else "danger")
    return _draft_redirect(flash_type, result["flash_msg"])


@bp.route('/ce:draft/publish-now', methods=['POST'])
def ce_draft_publish_now() -> Any:
    """Immediately schedule a draft item to publish in ~5 seconds."""
    item_id = request.form.get('id', '')
    result = _draft.publish_now(item_id)
    flash_type = result.get("flash_type") or ("info" if result["ok"] else "danger")
    return _draft_redirect(flash_type, result["flash_msg"])


@bp.route('/ce:draft/cancel', methods=['POST'])
def ce_draft_cancel() -> Any:
    """Cancel a scheduled draft job."""
    item_id = request.form.get('id', '')
    result = _draft.cancel(item_id)
    flash_type = result.get("flash_type") or ("success" if result["ok"] else "danger")
    return _draft_redirect(flash_type, result["flash_msg"])


@bp.route('/ce:draft/delete', methods=['POST'])
def ce_draft_delete() -> Any:
    """Delete a draft item (cancel job if scheduled)."""
    item_id = request.form.get('id', '')
    result = _draft.delete(item_id)
    flash_type = result.get("flash_type") or ("success" if result["ok"] else "danger")
    return _draft_redirect(flash_type, result["flash_msg"])


# ── Bulk operations —───────────────────────────────────────────────────────


@bp.route('/ce:draft/bulk-delete', methods=['POST'])
def ce_draft_bulk_delete() -> Any:
    """Delete multiple drafts by id. Form: ids=<id1>&ids=<id2>..."""
    ids = request.form.getlist('ids')
    result = _draft.bulk_delete(ids)
    flash_type = result.get("flash_type") or ("success" if result["ok"] else "warning")
    return _draft_redirect(flash_type, result["flash_msg"])


@bp.route('/ce:draft/bulk-publish-now', methods=['POST'])
def ce_draft_bulk_publish_now() -> Any:
    """Schedule multiple drafts for near-immediate publish, staggered by 5s."""
    ids = request.form.getlist('ids')
    result = _draft.bulk_publish_now(ids)
    flash_type = result.get("flash_type") or ("info" if result["ok"] else "warning")
    return _draft_redirect(flash_type, result["flash_msg"])


@bp.route('/ce:draft/bulk-cancel', methods=['POST'])
def ce_draft_bulk_cancel() -> Any:
    """Cancel scheduling for multiple drafts (revert to pending)."""
    ids = request.form.getlist('ids')
    result = _draft.bulk_cancel(ids)
    flash_type = result.get("flash_type") or ("success" if result["ok"] else "warning")
    return _draft_redirect(flash_type, result["flash_msg"])
