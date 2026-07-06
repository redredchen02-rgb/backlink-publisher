"""/ + /ce:clear — Plan 2026-05-18-001 Unit 3.

Plan 2026-07-06-004 Unit 4: '/' now redirects to the SPA ('/app/', the new
Monitor-dashboard homepage — see origin doc-review P1 finding), matching the
existing pattern used by the 8 other migrated legacy routes (schedule.py,
settings_basic.py, keep_alive.py, etc: bare route redirects, ``/jinja``
keeps the old Jinja render as a LITE-mode / SPA-disabled fallback). Before
this unit, '/' rendered index.html directly with no redirect at all — a
known, deliberately-deferred gap (see webui_app/CLAUDE.md's dual-frontend
section) that left the new homepage invisible to any browser session that
had never separately loaded '/app/'.
"""

from __future__ import annotations

from typing import Any

from flask import Blueprint, request, session, url_for

from ..helpers.contexts import _render
from ..helpers.security import _safe_flash_redirect

bp = Blueprint("main", __name__)


@bp.route('/')
def index() -> Any:
    """Redirect legacy bare '/' → SPA '/app/' (Plan 2026-07-06-004 Unit 4).

    Forwards flash_type/flash_msg (through the existing _safe_flash_redirect
    sanitizer — CR/LF strip, length cap, URL-quote) so the 10 existing
    outbound redirects to bare '/' from checkpoint.py (2) and drafts.py (8)
    keep carrying their flash message through to the new homepage rather
    than silently losing it; Unit 5 wires up the SPA-side consumption of
    these two query params on the new homepage entry point. ``tab``/
    ``campaign_id`` are deliberately NOT forwarded — the new homepage does
    not handle those two legacy params (see plan's Scope Boundaries /
    Deferred to Separate Tasks).
    """
    target = url_for("spa.spa", subpath="")
    return _safe_flash_redirect(
        target,
        flash_type=request.args.get('flash_type', ''),
        msg=request.args.get('flash_msg', ''),
    )


@bp.route('/jinja')
def index_jinja() -> Any:
    """Legacy Jinja fallback — kept for LITE mode or SPA-disabled setups
    (mirrors the pattern used by pr-queue / survival-dashboard / schedule)."""
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
def ce_clear() -> Any:
    """Clear session and restart."""
    session.clear()
    return _render('index.html', active_page='index')
