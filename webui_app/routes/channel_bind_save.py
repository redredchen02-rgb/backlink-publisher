"""Registry-driven credential save route — Plan 2026-05-26-002 Unit 4.

Single POST endpoint dispatching channel→auth-type→saver.  Handles TOKEN,
TOKEN+FIELDS, PASTE-BLOB, USERPASS, and ANON auth types.

As of Plan 2026-06-18-002 U7 (Settings security increment) the dispatch and all
validations were **moved** into ``webui_app.api.channel_bind_api.ChannelBindAPI``
(single source), so this route is now a thin HTML binding: enforce the transport
guards, hand ``request.form`` to the facade, and render the neutral result as a
flash-redirect. The JSON sibling ``/api/v1/settings/channels/<channel>/credential``
calls the same facade.

Security guarantees (enforced here, at the HTTP boundary)
--------------------------------------------------------
* ``_refuse_when_allow_network()`` — hard-disabled when not on loopback.
* ``_check_bind_origin_or_abort()`` — Origin/Referer must be loopback.
* CSRF is enforced globally by ``_global_csrf_guard`` in ``create_app()``.
* Secrets never appear in flash messages (``_safe_flash_redirect`` sanitises);
  the facade never echoes a token/password into its result message.

The SSRF / paste-blob / hostname validations themselves live in the facade.
Channels devto / ghpages / notion keep their dedicated routes in
``token_paste.py``; the facade ignores them to avoid conflicts.
"""

from __future__ import annotations

from flask import Blueprint, request

from ..api.channel_bind_api import ChannelBindAPI
from ..helpers.security import (
    _check_bind_origin_or_abort,
    _refuse_when_allow_network,
    _safe_flash_redirect,
)

bp = Blueprint("channel_bind_save", __name__)


@bp.route("/settings/save-channel-credential", methods=["POST"])
def save_channel_credential():
    _refuse_when_allow_network()
    _check_bind_origin_or_abort()

    channel = (request.form.get("channel", "") or "").strip()
    result = ChannelBindAPI().save_channel_credential(channel=channel, fields=request.form)
    return _safe_flash_redirect(
        "/settings",
        flash_type=result.level,
        msg=result.message,
        fragment=result.fragment,
    )
