"""Credential-write endpoints for ``/api/v1`` — Plan 2026-06-18-002 U7 (Settings, security core).

Converts the token-paste credential writes (``/settings/save-channel-token`` +
``/settings/save-notion-token``) to the versioned JSON surface. These write
``0600`` secret files, so this is the plan's THREAT-3 surface: a naive HTML→JSON
port could silently drop the per-route transport guards. It does not — the guards
are enforced INLINE here (the new blueprint does NOT inherit the legacy ``bind``
blueprint's ``before_request``), and a transport-layer security regression battery
(forged Origin → 403, ``ALLOW_NETWORK=1`` → 403, file still ``0600``) gates them.

All secret writes REUSE ``credential_service`` / ``save_notion_token`` (the single
source of the ``0600`` atomic write) — nothing is reimplemented. The legacy
``token_paste`` route is untouched (additive; retired in U8).

Guard gating mirrors ``bind.py``: the inline guards are skipped when CSRF is
disabled (the broad test suite) and exercised by the security regression tests
(which run a CSRF-enabled app). In production CSRF is always on, so they fire.

Scope: token-paste credentials only. The registry-driven ``channel_bind_save``
dispatch (anon/token/token_fields/paste_blob/userpass + SSRF/blob validation) and
the stateful ``bind`` browser flow are a separate security increment — porting
them needs single-source facade extraction to avoid reproducing (and risk
dropping) a validation.
"""

from __future__ import annotations

import os
import stat

from flask import current_app, jsonify, request

from backlink_publisher.config import load_config, save_notion_token
from backlink_publisher.config.tokens import load_notion_token
from backlink_publisher.publishing.registry import auth_type as _registry_auth_type

from ...helpers.security import _check_bind_origin_or_abort, _refuse_when_allow_network
from ...services import credential_service

# Channels handled by token-paste save: token (devto) + single-field token_fields (ghpages).
# Defined here after routes/token_paste.py was retired in U8 (Plan 2026-06-18-002).
_PASTE_ROUTE_CHANNELS: frozenset[str] = frozenset(
    credential_service._TOKEN_DISPATCH
) | {
    ch for ch in credential_service._TOKEN_FIELDS_DISPATCH
    if credential_service._TOKEN_FIELDS_DISPATCH[ch][2] == ["token"]
}
from . import bp
from .errors import ApiProblem


def _transport_guards_active() -> bool:
    """Whether the inline credential-write guards should fire.

    Gated on CSRF config so the broad pytest suite (CSRF off) is unaffected; the
    security regression tests run a CSRF-enabled app to exercise them. In
    production CSRF is always on, so they always fire. (The guard calls
    themselves stay INLINE in each view — both for ``abort(403)`` short-circuit
    and so the per-route-guard coverage gate sees them in the view source.)
    """
    return bool(
        current_app.config.get("CSRF_ENABLED", True)
        and current_app.config.get("WTF_CSRF_ENABLED", True)
    )


@bp.post("/settings/channels/<channel>/token")
def settings_save_channel_token(channel: str):
    """Save (or clear) a paste-token channel credential → ``0600`` file.

    Body: ``{"token": "..."}`` to save, or ``{"clear": true}`` to remove.
    """
    # THREAT-3: the api_v1 blueprint does NOT inherit bind.py's before_request,
    # so enforce the transport guards here. Both abort(403).
    if _transport_guards_active():
        _refuse_when_allow_network()
        _check_bind_origin_or_abort()
    channel = (channel or "").strip()
    if channel not in _PASTE_ROUTE_CHANNELS:
        raise ApiProblem(
            422, "Unknown channel",
            detail=f'"{channel}" is not a paste-token channel.',
            error_class="invalid_request",
        )

    cfg = load_config()
    channel_auth_type = _registry_auth_type(channel) or "token"
    data = request.get_json(silent=True) or {}

    if data.get("clear"):
        try:
            cleared = credential_service.clear_credential(channel, channel_auth_type, cfg)
        except credential_service.ChannelNotConfigured:
            raise ApiProblem(422, "Channel not configured", error_class="invalid_request")
        except OSError:
            raise ApiProblem(502, "Failed to clear credential", error_class="persistence_failure")
        msg = f"{channel} token 已清除" if cleared else f"{channel} token 文件不存在，无需清除"
        return jsonify({"ok": True, "cleared": bool(cleared), "message": msg})

    token = str(data.get("token") or "").strip()
    if not token:
        return jsonify({"ok": False, "message": f"未填入 token，{channel} 配置未变更"})

    try:
        if channel_auth_type == "token_fields":
            credential_service.save_token_fields(channel, cfg, {"token": token})
        else:
            credential_service.save_token(channel, cfg, token)
    except credential_service.ChannelNotConfigured:
        raise ApiProblem(422, "Channel not configured", error_class="invalid_request")
    except Exception:
        raise ApiProblem(502, "Failed to save token", error_class="persistence_failure")
    return jsonify({"ok": True, "message": f"{channel} token 已绑定 ✓"})


@bp.post("/settings/notion-token")
def settings_save_notion_token():
    """Save (or clear) the Notion credential (integration_token + database_id) → ``0600``."""
    # THREAT-3: same inline transport guards as the channel-token endpoint.
    if _transport_guards_active():
        _refuse_when_allow_network()
        _check_bind_origin_or_abort()
    data = request.get_json(silent=True) or {}

    if data.get("clear"):
        token_path = load_config().notion_token_path
        try:
            existed = token_path.exists()
            if existed:
                token_path.unlink()
        except OSError:
            raise ApiProblem(502, "Failed to clear Notion token", error_class="persistence_failure")
        msg = "notion token 已清除" if existed else "notion token 文件不存在，无需清除"
        return jsonify({"ok": True, "cleared": existed, "message": msg})

    integration_token = str(data.get("integration_token") or "").strip()
    database_id = str(data.get("database_id") or "").strip()
    if not integration_token:
        raise ApiProblem(422, "Missing integration_token", error_class="invalid_request")
    if not database_id:
        raise ApiProblem(422, "Missing database_id", error_class="invalid_request")

    try:
        save_notion_token({"integration_token": integration_token, "database_id": database_id})
        token_path = load_config().notion_token_path
        if not token_path.exists():
            raise ApiProblem(502, "Notion token file not created", error_class="persistence_failure")
        # Belt-and-suspenders: re-assert 0600 (save_notion_token already does).
        if os.name != "nt" and stat.S_IMODE(token_path.stat().st_mode) != 0o600:
            os.chmod(token_path, 0o600)
    except ApiProblem:
        raise
    except Exception:
        raise ApiProblem(502, "Failed to save Notion token", error_class="persistence_failure")
    return jsonify({"ok": True, "message": "notion token 已绑定 ✓"})


@bp.get("/settings/notion/status")
def settings_notion_status():
    """Notion card state: whether a credential is stored + the (non-secret) database_id.

    Read-only — the integration_token is NEVER returned, only ``configured``. No
    secret leaves the box, so (like the other status GETs) no inline transport guard.
    """
    data = load_notion_token() or {}
    integration_token = str(data.get("integration_token") or "").strip()
    database_id = str(data.get("database_id") or "").strip()
    return jsonify({"configured": bool(integration_token), "database_id": database_id})
