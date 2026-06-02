"""Registry-driven credential save route — Plan 2026-05-26-002 Unit 4.

Single POST endpoint dispatching channel→auth-type→saver.  Handles TOKEN,
TOKEN+FIELDS, PASTE-BLOB, USERPASS, and ANON auth types.

Security guarantees
-------------------
* ``_refuse_when_allow_network()`` — hard-disabled when not on loopback.
* ``_check_bind_origin_or_abort()`` — Origin/Referer must be loopback.
* CSRF is enforced globally by ``_global_csrf_guard`` in ``create_app()``;
  no duplicate check here.
* Secrets never appear in flash messages (``_safe_flash_redirect`` sanitises).
* SSRF: URL fields (site, site_url) are validated via ``_check_url_for_ssrf``
  and must use https.
* Paste-blob: size-capped, JSON-schema checked, domain-validated per channel.

Channels devto / ghpages / notion keep their existing routes in
``token_paste.py``; this route ignores them to avoid conflicts.
Dispatch maps and credential writes live in
``webui_app.services.credential_service`` (U3b).
"""

from __future__ import annotations

import json
import logging

_log = logging.getLogger(__name__)

from flask import Blueprint, request

from backlink_publisher.config import load_config
from backlink_publisher._util.net_safety import _check_url_for_ssrf
from backlink_publisher.publishing.registry import auth_type as _registry_auth_type

from ..helpers.security import (
    _check_bind_origin_or_abort,
    _refuse_when_allow_network,
    _safe_flash_redirect,
)
from ..services import credential_service

bp = Blueprint("channel_bind_save", __name__)

# Channels with dedicated existing routes — never handled here.
_SKIP_CHANNELS: frozenset[str] = frozenset({"devto", "ghpages", "notion"})

# URL fields that must pass SSRF validation (must be https, non-private).
_URL_FIELDS: frozenset[str] = frozenset({"site", "site_url"})


@bp.route("/settings/save-channel-credential", methods=["POST"])
def save_channel_credential():
    _refuse_when_allow_network()
    _check_bind_origin_or_abort()

    channel = (request.form.get("channel", "") or "").strip()
    auth_type = (request.form.get("auth_type", "") or "").strip()

    if not channel:
        return _safe_flash_redirect("/settings", flash_type="danger",
                                    msg="channel 参数缺失")

    if channel in _SKIP_CHANNELS:
        return _safe_flash_redirect(
            "/settings", flash_type="danger",
            msg=f"{channel} 使用专用保存路由，不经此接口",
            fragment=f"channel-{channel}",
        )

    # Verify channel is registered and auth_type agrees with registry.
    registry_at = _registry_auth_type(channel)
    if registry_at is None:
        return _safe_flash_redirect("/settings", flash_type="danger",
                                    msg=f"未知渠道: {channel}")
    if auth_type and auth_type != registry_at:
        return _safe_flash_redirect(
            "/settings", flash_type="danger",
            msg=f"{channel} auth_type 不匹配（表单: {auth_type}, 注册表: {registry_at}）",
            fragment=f"channel-{channel}",
        )
    auth_type = registry_at

    is_clear = bool(request.form.get("clear"))

    if auth_type == "anon":
        return _save_anon(channel, is_clear)
    if auth_type == "token":
        return _save_token(channel, is_clear)
    if auth_type == "token_fields":
        return _save_token_fields(channel, is_clear)
    if auth_type == "paste_blob":
        return _save_paste_blob(channel, is_clear)
    if auth_type == "userpass":
        return _save_userpass(channel, is_clear)

    return _safe_flash_redirect(
        "/settings", flash_type="danger",
        msg=f"{channel} 的 auth_type={auth_type!r} 不支持通用保存路由",
        fragment=f"channel-{channel}",
    )


# ── auth-type handlers ────────────────────────────────────────────────────────


def _save_anon(channel: str, is_clear: bool):
    return _safe_flash_redirect(
        "/settings", flash_type="info",
        msg=f"{channel} 为匿名渠道，无需凭据",
        fragment=f"channel-{channel}",
    )


def _save_token(channel: str, is_clear: bool):
    cfg = load_config()
    frag = f"channel-{channel}"

    if is_clear:
        try:
            cleared = credential_service.clear_credential(channel, "token", cfg)
            if cleared:
                return _safe_flash_redirect(
                    "/settings", flash_type="success",
                    msg=f"{channel} 凭据已清除", fragment=frag)
            return _safe_flash_redirect(
                "/settings", flash_type="info",
                msg=f"{channel} 凭据文件不存在，无需清除", fragment=frag)
        except credential_service.ChannelNotConfigured:
            return _safe_flash_redirect(
                "/settings", flash_type="danger",
                msg=f"{channel} token 保存未实现（渠道可能已退役）", fragment=frag)
        except OSError:
            return _safe_flash_redirect(
                "/settings", flash_type="danger",
                msg=f"清除 {channel} 凭据失败（详见服务器日志）", fragment=frag)

    token = (request.form.get("token", "") or "").strip()
    if not token:
        return _safe_flash_redirect(
            "/settings", flash_type="info",
            msg=f"未填入 token，{channel} 配置未变更",
            fragment=frag,
        )
    try:
        credential_service.save_token(channel, cfg, token)
    except credential_service.ChannelNotConfigured:
        return _safe_flash_redirect(
            "/settings", flash_type="danger",
            msg=f"{channel} token 保存未实现（渠道可能已退役）", fragment=frag)
    except Exception:
        _log.exception("save_token failed for channel=%s", channel)
        return _safe_flash_redirect(
            "/settings", flash_type="danger",
            msg=f"保存 {channel} token 失败（详见服务器日志）",
            fragment=frag,
        )
    return _safe_flash_redirect(
        "/settings", flash_type="success",
        msg=f"{channel} token 已绑定 ✓",
        fragment=frag,
    )


def _save_token_fields(channel: str, is_clear: bool):
    cfg = load_config()
    frag = f"channel-{channel}"

    if is_clear:
        try:
            cleared = credential_service.clear_credential(channel, "token_fields", cfg)
            if cleared:
                return _safe_flash_redirect(
                    "/settings", flash_type="success",
                    msg=f"{channel} 凭据已清除", fragment=frag)
            return _safe_flash_redirect(
                "/settings", flash_type="info",
                msg=f"{channel} 凭据文件不存在，无需清除", fragment=frag)
        except credential_service.ChannelNotConfigured:
            return _safe_flash_redirect(
                "/settings", flash_type="danger",
                msg=f"{channel} token_fields 保存未实现（渠道可能已退役或待实现）",
                fragment=frag)
        except OSError:
            return _safe_flash_redirect(
                "/settings", flash_type="danger",
                msg=f"清除 {channel} 凭据失败（详见服务器日志）", fragment=frag)

    field_names = credential_service.token_field_names(channel)
    if field_names is None:
        return _safe_flash_redirect(
            "/settings", flash_type="danger",
            msg=f"{channel} token_fields 保存未实现（渠道可能已退役或待实现）",
            fragment=frag,
        )

    data: dict = {}
    for field_name in field_names:
        val = (request.form.get(field_name, "") or "").strip()
        if val:
            data[field_name] = val

    if not data:
        return _safe_flash_redirect(
            "/settings", flash_type="info",
            msg=f"未填入任何字段，{channel} 配置未变更",
            fragment=frag,
        )

    # Validate URL fields against SSRF before any write (security gate stays in route).
    for field_name, val in data.items():
        if field_name in _URL_FIELDS:
            err = _validate_url_field(channel, field_name, val)
            if err:
                return err

    try:
        credential_service.save_token_fields(channel, cfg, data)
    except credential_service.ChannelNotConfigured:
        return _safe_flash_redirect(
            "/settings", flash_type="danger",
            msg=f"{channel} token_fields 保存未实现（渠道可能已退役或待实现）",
            fragment=frag)
    except credential_service.CorruptCredentialFile as exc:
        _log.error("corrupt credential file for channel=%s: %s", channel, exc)
        return _safe_flash_redirect(
            "/settings", flash_type="danger",
            msg=f"凭据文件已损坏，请手动删除后重试: {exc}",
            fragment=frag,
        )
    except Exception:
        _log.exception("save_token_fields failed for channel=%s", channel)
        return _safe_flash_redirect(
            "/settings", flash_type="danger",
            msg=f"保存 {channel} 凭据失败（详见服务器日志）",
            fragment=frag,
        )
    return _safe_flash_redirect(
        "/settings", flash_type="success",
        msg=f"{channel} 凭据已绑定 ✓",
        fragment=frag,
    )


def _save_paste_blob(channel: str, is_clear: bool):
    cfg = load_config()
    frag = f"channel-{channel}"

    if is_clear:
        try:
            cleared = credential_service.clear_credential(channel, "paste_blob", cfg)
            if cleared:
                return _safe_flash_redirect(
                    "/settings", flash_type="success",
                    msg=f"{channel} 凭据已清除", fragment=frag)
            return _safe_flash_redirect(
                "/settings", flash_type="info",
                msg=f"{channel} 凭据文件不存在，无需清除", fragment=frag)
        except credential_service.ChannelNotConfigured:
            return _safe_flash_redirect(
                "/settings", flash_type="danger",
                msg=f"{channel} paste_blob 保存未实现（渠道可能已退役）", fragment=frag)
        except OSError:
            return _safe_flash_redirect(
                "/settings", flash_type="danger",
                msg=f"清除 {channel} 凭据失败（详见服务器日志）", fragment=frag)

    blob_raw = request.form.get("blob", "") or ""
    if not blob_raw.strip():
        return _safe_flash_redirect(
            "/settings", flash_type="info",
            msg=f"未填入 Cookie JSON，{channel} 配置未变更",
            fragment=frag,
        )

    if len(blob_raw.encode("utf-8")) > credential_service._PASTE_BLOB_MAX_BYTES:
        return _safe_flash_redirect(
            "/settings", flash_type="danger",
            msg=f"Cookie JSON 超过 {credential_service._PASTE_BLOB_MAX_BYTES // 1000}KB 限制",
            fragment=frag,
        )

    try:
        data = json.loads(blob_raw)
    except json.JSONDecodeError as exc:
        return _safe_flash_redirect(
            "/settings", flash_type="danger",
            msg=f"Cookie JSON 解析失败: {exc}",
            fragment=frag,
        )

    expected_domain = credential_service.paste_blob_expected_domain(channel)
    if expected_domain is None:
        return _safe_flash_redirect(
            "/settings", flash_type="danger",
            msg=f"{channel} paste_blob 保存未实现（渠道可能已退役）", fragment=frag)

    err = _validate_cookie_blob(data, expected_domain)
    if err:
        return _safe_flash_redirect("/settings", flash_type="danger", msg=err, fragment=frag)

    try:
        credential_service.save_paste_blob(channel, cfg, data)
    except credential_service.ChannelNotConfigured:
        return _safe_flash_redirect(
            "/settings", flash_type="danger",
            msg=f"{channel} paste_blob 保存未实现（渠道可能已退役）", fragment=frag)
    except OSError:
        return _safe_flash_redirect(
            "/settings", flash_type="danger",
            msg=f"写入 {channel} cookie 文件失败（详见服务器日志）",
            fragment=frag,
        )
    return _safe_flash_redirect(
        "/settings", flash_type="success",
        msg=f"{channel} cookies 已绑定 ✓",
        fragment=frag,
    )


def _save_userpass(channel: str, is_clear: bool):
    cfg = load_config()
    frag = f"channel-{channel}"

    if is_clear:
        try:
            cleared = credential_service.clear_credential(channel, "userpass", cfg)
            if cleared:
                return _safe_flash_redirect(
                    "/settings", flash_type="success",
                    msg=f"{channel} 凭据已清除", fragment=frag)
            return _safe_flash_redirect(
                "/settings", flash_type="info",
                msg=f"{channel} 凭据文件不存在，无需清除", fragment=frag)
        except credential_service.ChannelNotConfigured:
            return _safe_flash_redirect(
                "/settings", flash_type="danger",
                msg=f"{channel} userpass 保存未实现（渠道可能已退役）", fragment=frag)
        except OSError:
            return _safe_flash_redirect(
                "/settings", flash_type="danger",
                msg=f"清除 {channel} 凭据失败（详见服务器日志）", fragment=frag)

    username = (request.form.get("username", "") or "").strip()
    password = (request.form.get("password", "") or "").strip()

    if not username and not password:
        return _safe_flash_redirect(
            "/settings", flash_type="info",
            msg=f"未填入凭据，{channel} 配置未变更",
            fragment=frag,
        )
    if not username or not password:
        return _safe_flash_redirect(
            "/settings", flash_type="danger",
            msg=f"{channel} 用户名和密码必须同时填写",
            fragment=frag,
        )

    try:
        credential_service.save_userpass(channel, cfg, username, password)
    except credential_service.ChannelNotConfigured:
        return _safe_flash_redirect(
            "/settings", flash_type="danger",
            msg=f"{channel} userpass 保存未实现（渠道可能已退役）", fragment=frag)
    except Exception:
        _log.exception("save_userpass failed for channel=%s", channel)
        return _safe_flash_redirect(
            "/settings", flash_type="danger",
            msg=f"保存 {channel} 凭据失败（详见服务器日志）",
            fragment=frag,
        )
    return _safe_flash_redirect(
        "/settings", flash_type="success",
        msg=f"{channel} 凭据已绑定 ✓",
        fragment=frag,
    )


# ── helpers ───────────────────────────────────────────────────────────────────


def _validate_url_field(channel: str, field_name: str, val: str):
    if not val.startswith("https://"):
        return _safe_flash_redirect(
            "/settings", flash_type="danger",
            msg=f"{channel} {field_name} 必须以 https:// 开头",
            fragment=f"channel-{channel}",
        )
    ssrf_err = _check_url_for_ssrf(val)
    if ssrf_err:
        return _safe_flash_redirect(
            "/settings", flash_type="danger",
            msg=f"{channel} {field_name} 地址被拒绝（安全校验）",
            fragment=f"channel-{channel}",
        )
    return None


def _validate_cookie_blob(data: object, expected_domain: str) -> str | None:
    """Return an error message string, or None if the blob looks valid."""
    if not isinstance(data, dict):
        return "Cookie JSON 必须是 JSON 对象（{...}）"

    cookies = data.get("cookies")
    if cookies is None:
        return 'Cookie JSON 缺少 "cookies" 键'
    if not isinstance(cookies, list):
        return '"cookies" 字段必须是数组'
    if len(cookies) == 0:
        return '"cookies" 数组不能为空'

    for i, c in enumerate(cookies):
        if not isinstance(c, dict):
            return f"cookies[{i}] 必须是对象"
        if "name" not in c:
            return f"cookies[{i}] 缺少 name 字段"
        if "value" not in c:
            return f"cookies[{i}] 缺少 value 字段"

    # Advisory domain check — at least one cookie's domain should match
    # the expected channel domain (warns operator if they pasted wrong site).
    if expected_domain:
        domains = [
            c.get("domain", "") for c in cookies if isinstance(c, dict)
        ]
        if not any(expected_domain in (d or "") for d in domains):
            return (
                f"Cookie 域名校验失败：未发现包含 {expected_domain!r} 的 domain。"
                "请确认是否导出了正确站点的 Cookie。"
            )

    return None
