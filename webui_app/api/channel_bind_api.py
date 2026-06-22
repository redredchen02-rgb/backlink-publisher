"""ChannelBindAPI — registry-driven channel credential save, transport-neutral.

Phase-A facade (Plan 2026-06-18-002 U7, Settings security increment). The
5-way auth-type dispatch (``anon`` / ``token`` / ``token_fields`` / ``paste_blob``
/ ``userpass``) plus its security validations (SSRF on URL fields, hostname
format on domain-fragment fields, the paste-blob JSON schema + domain check) were
**moved here, not copied**, from ``routes/channel_bind_save.py``. There is now a
single source of the dispatch: the legacy ``/settings/save-channel-credential``
HTML route and the new ``/api/v1/settings/channels/<channel>/credential`` JSON
binding both call ``ChannelBindAPI.save_channel_credential`` and only differ in
how they render the neutral :class:`BindSaveResult` (flash-redirect vs problem+json).

Copying the dispatch would have risked dropping one validation on the JSON path —
exactly the credential-write threat the security regression battery guards. Moving
it keeps every validation single-source, so both transports inherit the same gates.

The actual ``0600`` secret writes still live in ``services.credential_service``
(unchanged). This module performs NO transport concerns: it never touches
``flask.request`` and never aborts — the per-route transport guards
(``_refuse_when_allow_network`` / ``_check_bind_origin_or_abort``) stay at the
HTTP boundary in each binding.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Mapping

from backlink_publisher._util.net_safety import _check_url_for_ssrf
from backlink_publisher.config import load_config
from backlink_publisher.publishing.registry import auth_type as _registry_auth_type

from ..services import credential_service

_log = logging.getLogger(__name__)

# Channels with dedicated existing routes — never handled here.
_SKIP_CHANNELS: frozenset[str] = frozenset({"devto", "ghpages", "notion"})

# URL fields that must pass SSRF validation (must be https, non-private).
_URL_FIELDS: frozenset[str] = frozenset({"site", "site_url"})

# Domain-fragment fields validated per-channel (hostname format, not full URL).
# Per-channel dict avoids cross-channel pollution — a "blog_id" in another
# channel may carry different semantics.
_BLOG_ID_FIELDS: dict[str, frozenset[str]] = {
    "hatena": frozenset({"blog_id"}),
}

_HOSTNAME_RE = re.compile(
    r"^[A-Za-z0-9]([A-Za-z0-9\-]*[A-Za-z0-9])?"
    r"(\.[A-Za-z0-9]([A-Za-z0-9\-]*[A-Za-z0-9])?)*"
    r"\.[A-Za-z]{2,}$"
)


@dataclass(frozen=True)
class BindSaveResult:
    """Transport-neutral outcome of a credential save/clear.

    ``level`` drives the legacy flash type (``success`` / ``info`` / ``danger``).
    ``error_class`` is set only on failures and selects the ``/api/v1`` HTTP
    status: ``invalid_request`` → 422, ``persistence_failure`` → 502. ``cleared``
    is set (True/False) only for clear operations so the JSON binding can report
    whether a file was actually removed; ``fragment`` is the legacy redirect
    anchor and is ignored by the JSON binding.
    """

    level: str
    message: str
    channel: str = ""
    fragment: str = ""
    error_class: str | None = None
    cleared: bool | None = None

    @property
    def ok(self) -> bool:
        return self.error_class is None


def _ok(message: str, channel: str, *, cleared: bool | None = None) -> BindSaveResult:
    return BindSaveResult(
        level="success", message=message, channel=channel,
        fragment=f"channel-{channel}", cleared=cleared,
    )


def _info(message: str, channel: str, *, cleared: bool | None = None) -> BindSaveResult:
    return BindSaveResult(
        level="info", message=message, channel=channel,
        fragment=f"channel-{channel}", cleared=cleared,
    )


def _danger(message: str, channel: str, *, error_class: str, fragment: str | None = None) -> BindSaveResult:
    return BindSaveResult(
        level="danger", message=message, channel=channel,
        fragment=f"channel-{channel}" if fragment is None else fragment,
        error_class=error_class,
    )


class ChannelBindAPI:
    """Stateless facade; instantiate per call (mirrors SitesAPI / CampaignAPI)."""

    def save_channel_credential(self, *, channel: str, fields: Mapping) -> BindSaveResult:
        """Dispatch a credential save/clear by the channel's registered auth type.

        ``fields`` is any mapping exposing ``.get(name, default)`` — ``request.form``
        for the legacy route, the parsed JSON body for ``/api/v1``. ``channel`` is
        supplied explicitly (form field vs URL path); ``auth_type`` (if present in
        ``fields``) is cross-checked against the registry to reject spoofing.
        """
        channel = (channel or "").strip()
        auth_type = str(fields.get("auth_type") or "").strip()

        if not channel:
            return _danger("channel 参数缺失", "", error_class="invalid_request", fragment="")

        if channel in _SKIP_CHANNELS:
            return _danger(
                f"{channel} 使用专用保存路由，不经此接口", channel,
                error_class="invalid_request",
            )

        registry_at = _registry_auth_type(channel)
        if registry_at is None:
            return _danger(f"未知渠道: {channel}", channel, error_class="invalid_request", fragment="")
        if auth_type and auth_type != registry_at:
            return _danger(
                f"{channel} auth_type 不匹配（表单: {auth_type}, 注册表: {registry_at}）",
                channel, error_class="invalid_request",
            )
        auth_type = registry_at

        is_clear = bool(fields.get("clear"))

        if auth_type == "anon":
            return self._save_anon(channel, is_clear)
        if auth_type == "token":
            return self._save_token(channel, is_clear, fields)
        if auth_type == "token_fields":
            return self._save_token_fields(channel, is_clear, fields)
        if auth_type == "paste_blob":
            return self._save_paste_blob(channel, is_clear, fields)
        if auth_type == "userpass":
            return self._save_userpass(channel, is_clear, fields)

        return _danger(
            f"{channel} 的 auth_type={auth_type!r} 不支持通用保存路由",
            channel, error_class="invalid_request",
        )

    # ── auth-type handlers ───────────────────────────────────────────────────

    def _save_anon(self, channel: str, is_clear: bool) -> BindSaveResult:
        return _info(f"{channel} 为匿名渠道，无需凭据", channel)

    def _clear(self, channel: str, auth_type: str, cfg, *, not_impl_msg: str) -> BindSaveResult:
        """Shared clear path for token / token_fields / paste_blob / userpass.

        The success / file-absent / OSError messages are uniform across auth
        types; only the ``ChannelNotConfigured`` ("not implemented") wording
        differs (token_fields adds "或待实现"), so it is passed in verbatim to
        keep zero message drift from the legacy route.
        """
        try:
            cleared = credential_service.clear_credential(channel, auth_type, cfg)
        except credential_service.ChannelNotConfigured:
            return _danger(not_impl_msg, channel, error_class="invalid_request")
        except OSError:
            return _danger(f"清除 {channel} 凭据失败（详见服务器日志）", channel, error_class="persistence_failure")
        if cleared:
            return _ok(f"{channel} 凭据已清除", channel, cleared=True)
        return _info(f"{channel} 凭据文件不存在，无需清除", channel, cleared=False)

    def _save_token(self, channel: str, is_clear: bool, fields: Mapping) -> BindSaveResult:
        cfg = load_config()
        if is_clear:
            return self._clear(channel, "token", cfg,
                               not_impl_msg=f"{channel} token 保存未实现（渠道可能已退役）")

        token = str(fields.get("token") or "").strip()
        if not token:
            return _info(f"未填入 token，{channel} 配置未变更", channel)
        try:
            credential_service.save_token(channel, cfg, token)
        except credential_service.ChannelNotConfigured:
            return _danger(f"{channel} token 保存未实现（渠道可能已退役）", channel, error_class="invalid_request")
        except Exception:
            _log.exception("save_token failed for channel=%s", channel)
            return _danger(f"保存 {channel} token 失败（详见服务器日志）", channel, error_class="persistence_failure")
        return _ok(f"{channel} token 已绑定 ✓", channel)

    def _save_token_fields(self, channel: str, is_clear: bool, fields: Mapping) -> BindSaveResult:
        cfg = load_config()
        if is_clear:
            return self._clear(
                channel, "token_fields", cfg,
                not_impl_msg=f"{channel} token_fields 保存未实现（渠道可能已退役或待实现）",
            )

        field_names = credential_service.token_field_names(channel)
        if field_names is None:
            return _danger(
                f"{channel} token_fields 保存未实现（渠道可能已退役或待实现）",
                channel, error_class="invalid_request",
            )

        data: dict = {}
        for field_name in field_names:
            val = str(fields.get(field_name) or "").strip()
            if val:
                data[field_name] = val

        if not data:
            return _info(f"未填入任何字段，{channel} 配置未变更", channel)

        # Validate URL / domain-fragment fields before any write (security gate).
        for field_name, val in data.items():
            if field_name in _URL_FIELDS:
                err = _validate_url_field(channel, field_name, val)
                if err:
                    return err
            if field_name in _BLOG_ID_FIELDS.get(channel, frozenset()):
                err = _validate_blog_id_field(channel, field_name, val)
                if err:
                    return err

        try:
            credential_service.save_token_fields(channel, cfg, data)
        except credential_service.ChannelNotConfigured:
            return _danger(
                f"{channel} token_fields 保存未实现（渠道可能已退役或待实现）",
                channel, error_class="invalid_request",
            )
        except credential_service.CorruptCredentialFile as exc:
            _log.error("corrupt credential file for channel=%s: %s", channel, exc)
            return _danger(
                f"凭据文件已损坏，请手动删除后重试: {exc}", channel,
                error_class="persistence_failure",
            )
        except Exception:
            _log.exception("save_token_fields failed for channel=%s", channel)
            return _danger(f"保存 {channel} 凭据失败（详见服务器日志）", channel, error_class="persistence_failure")
        return _ok(f"{channel} 凭据已绑定 ✓", channel)

    def _save_paste_blob(self, channel: str, is_clear: bool, fields: Mapping) -> BindSaveResult:
        cfg = load_config()
        if is_clear:
            return self._clear(channel, "paste_blob", cfg,
                               not_impl_msg=f"{channel} paste_blob 保存未实现（渠道可能已退役）")

        blob_raw = str(fields.get("blob") or "")
        if not blob_raw.strip():
            return _info(f"未填入 Cookie JSON，{channel} 配置未变更", channel)

        if len(blob_raw.encode("utf-8")) > credential_service._PASTE_BLOB_MAX_BYTES:
            return _danger(
                f"Cookie JSON 超过 {credential_service._PASTE_BLOB_MAX_BYTES // 1000}KB 限制",
                channel, error_class="invalid_request",
            )

        try:
            data = json.loads(blob_raw)
        except json.JSONDecodeError as exc:
            return _danger(f"Cookie JSON 解析失败: {exc}", channel, error_class="invalid_request")

        expected_domain = credential_service.paste_blob_expected_domain(channel)
        if expected_domain is None:
            return _danger(
                f"{channel} paste_blob 保存未实现（渠道可能已退役）", channel,
                error_class="invalid_request",
            )

        err = _validate_cookie_blob(data, expected_domain)
        if err:
            return _danger(err, channel, error_class="invalid_request")

        try:
            credential_service.save_paste_blob(channel, cfg, data)
        except credential_service.ChannelNotConfigured:
            return _danger(
                f"{channel} paste_blob 保存未实现（渠道可能已退役）", channel,
                error_class="invalid_request",
            )
        except OSError:
            return _danger(
                f"写入 {channel} cookie 文件失败（详见服务器日志）", channel,
                error_class="persistence_failure",
            )
        return _ok(f"{channel} cookies 已绑定 ✓", channel)

    def _save_userpass(self, channel: str, is_clear: bool, fields: Mapping) -> BindSaveResult:
        cfg = load_config()
        if is_clear:
            return self._clear(channel, "userpass", cfg,
                               not_impl_msg=f"{channel} userpass 保存未实现（渠道可能已退役）")

        username = str(fields.get("username") or "").strip()
        password = str(fields.get("password") or "").strip()

        if not username and not password:
            return _info(f"未填入凭据，{channel} 配置未变更", channel)
        if not username or not password:
            return _danger(f"{channel} 用户名和密码必须同时填写", channel, error_class="invalid_request")

        try:
            credential_service.save_userpass(channel, cfg, username, password)
        except credential_service.ChannelNotConfigured:
            return _danger(f"{channel} userpass 保存未实现（渠道可能已退役）", channel, error_class="invalid_request")
        except Exception:
            _log.exception("save_userpass failed for channel=%s", channel)
            return _danger(f"保存 {channel} 凭据失败（详见服务器日志）", channel, error_class="persistence_failure")
        return _ok(f"{channel} 凭据已绑定 ✓", channel)


# ── validation helpers (moved verbatim; now return BindSaveResult | None) ──────


def _validate_url_field(channel: str, field_name: str, val: str) -> BindSaveResult | None:
    if not val.startswith("https://"):
        return _danger(f"{channel} {field_name} 必须以 https:// 开头", channel, error_class="invalid_request")
    ssrf_err = _check_url_for_ssrf(val)
    if ssrf_err:
        return _danger(f"{channel} {field_name} 地址被拒绝（安全校验）", channel, error_class="invalid_request")
    return None


def _validate_blog_id_field(channel: str, field_name: str, val: str) -> BindSaveResult | None:
    """Validate a domain-fragment field (hostname, not a full URL).

    Accepts valid hostnames (e.g. yourname.hatenablog.com, myblog.example.jp).
    Rejects path traversal, IP addresses, and values containing URL metacharacters.
    """
    if not _HOSTNAME_RE.match(val):
        return _danger(
            f"{channel} {field_name} 格式无效（须为合法域名，如 yourname.hatenablog.com）",
            channel, error_class="invalid_request",
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
