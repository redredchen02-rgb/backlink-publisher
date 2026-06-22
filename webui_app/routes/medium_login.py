"""Medium browser-login POST routes: launch / probe / clear.

Thin HTML bindings; the dispatch + outcome classification was moved to the
single-source ``MediumLoginAPI`` facade (Plan 2026-06-18-002 U7) and is shared with
the ``/api/v1/settings/medium/*-browser-login`` JSON routes.

CSRF is enforced globally by ``_global_csrf_guard`` in ``create_app()`` (it aborts
403 on any POST without a valid canonical ``csrf_token`` before this blueprint
runs), so these routes carry no bespoke CSRF layer. Because they spawn OS-level
browser processes and delete the persistent login profile, each POST additionally
guards origin like the ``bind`` routes do: ``_refuse_when_allow_network()`` +
``_check_bind_origin_or_abort()``.
"""

from __future__ import annotations

from flask import Blueprint, session

from ..api.medium_login_api import MediumLoginAPI
from ..helpers.security import (
    _check_bind_origin_or_abort,
    _refuse_when_allow_network,
    _safe_flash_redirect,
)

bp = Blueprint("medium_login", __name__)


def _apply_session(result) -> None:
    """Apply the facade's session decision to the publish-gating flag."""
    if result.session_op == "set":
        session["medium_probe_logged_in"] = result.logged_in
    elif result.session_op == "clear":
        session.pop("medium_probe_logged_in", None)


def _render(result):
    """Sanitized flash-redirect back to the medium channel card (CR/LF-stripped,
    URL-quoted, length-capped — the facade message may embed a raw Playwright/exc
    string)."""
    return _safe_flash_redirect(
        "/settings", flash_type=result.level, msg=result.message, fragment=result.fragment
    )


# ── Routes ────────────────────────────────────────────────────────────────────

@bp.route("/settings/medium/launch-browser-login", methods=["POST"])
def medium_launch_browser_login():
    """Open a headed Chromium for the user to log in to Medium."""
    _refuse_when_allow_network()
    _check_bind_origin_or_abort()
    result = MediumLoginAPI().launch()
    _apply_session(result)
    return _render(result)


@bp.route("/settings/medium/probe-browser-login", methods=["POST"])
def medium_probe_browser_login():
    """Probe Medium login state via a short Playwright navigation."""
    _refuse_when_allow_network()
    _check_bind_origin_or_abort()
    result = MediumLoginAPI().probe()
    _apply_session(result)
    return _render(result)


@bp.route("/settings/medium/clear-browser-login", methods=["POST"])
def medium_clear_browser_login():
    """Delete the persistent Chromium profile (clears stored login cookies)."""
    _refuse_when_allow_network()
    _check_bind_origin_or_abort()
    result = MediumLoginAPI().clear()
    _apply_session(result)
    return _render(result)
