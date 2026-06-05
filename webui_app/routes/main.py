"""/ + /ce:clear — Plan 2026-05-18-001 Unit 3."""

from __future__ import annotations

from flask import Blueprint, request, session

from ..helpers.contexts import _render
from ..helpers.security import _check_bind_origin_or_abort

bp = Blueprint("main", __name__)

@bp.before_request
def _enforce_bind_origin() -> None:
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        _check_bind_origin_or_abort()



@bp.route('/')
def index():
    config = session.get('config', {})
    tab = request.args.get('tab', '')
    flash_type = request.args.get('flash_type', '')
    flash_msg = request.args.get('flash_msg', '')
    flash = {'type': flash_type, 'msg': flash_msg} if flash_type else None
    history_active = tab == 'draft'
    campaign_id = request.args.get('campaign_id', '') or ''
    return _render('index.html', config=config,
                   history_active=history_active, flash=flash,
                   active_page='index',
                   filter_campaign_id=campaign_id)


@bp.route('/ce:clear', methods=['POST'])
def ce_clear():
    """Clear session and restart."""
    session.clear()
    return _render('index.html', active_page='index')
