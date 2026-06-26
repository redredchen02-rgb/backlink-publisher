"""VelogLoginAPI — velog browser-login spawn + status, transport-neutral.

Phase-A facade (Plan 2026-06-18-002 U7, Settings section 3 slice 4). The detached
``velog-login`` subprocess spawn and its ``error_code`` → message mapping were
**moved here, not copied**, from the legacy ``/api/velog/login`` route
(``settings_basic.py``); the status read delegates to the single-source
``_get_velog_status``. Both the legacy ``/api/velog/{login,status}`` JSON routes and
the new ``/api/v1/settings/velog/*`` bindings call this facade, so the launch
dispatch + the operator-facing messages are single-sourced and cannot drift.

Flask-free: no request/session access; the per-route transport guards
(``_refuse_when_allow_network`` / ``_check_bind_origin_or_abort``) stay at the HTTP
boundary in each binding — the v1 ``login`` spawns a headed browser process, so it
is inline-guarded like the medium / bind routes.
"""

from __future__ import annotations

from dataclasses import dataclass
import re

# Operator-facing messages per early-failure ``error_code`` (moved from the legacy
# route). The default covers any code not enumerated here.
_MESSAGES: dict[str, str] = {
    "profile_in_use": (
        "已有一个绑定窗口正在运行。请关闭已打开的 Chromium 窗口后再试。"
    ),
    "playwright_not_installed": (
        "Playwright 未安装。请在终端运行：python -m playwright install chromium"
    ),
    "login_url_unreachable": "无法打开 velog.io，请检查网络连接后再试。",
}
_DEFAULT_FAIL_MSG = "启动失败，请在终端运行 velog-login 并查看输出。"
_OK_MSG = "已启动 velog 登录窗口，请在弹出的 Chromium 中完成社交登录。"


@dataclass(frozen=True)
class VelogLoginResult:
    """Transport-neutral outcome of a velog-login spawn. ``ok`` False = the process
    died before the startup probe; ``error_code`` is parsed from its structured log
    so each transport can show a specific cause. ``log_path`` is where the detached
    subprocess keeps writing (``tail -f`` for the operator)."""

    ok: bool
    message: str
    error_code: str | None = None
    log_path: str = ""


class VelogLoginAPI:
    """Stateless facade; instantiate per call (mirrors MediumLoginAPI)."""

    def login(self) -> VelogLoginResult:
        """Spawn ``velog-login`` headed in a detached subprocess; report early
        failure. Lazy import so tests patching
        ``webui_app.services.browser_login.spawn_browser_login`` are honoured."""
        from ..services.browser_login import spawn_browser_login

        result = spawn_browser_login("backlink_publisher.cli.velog_login")
        if result.ok:
            return VelogLoginResult(ok=True, message=_OK_MSG, log_path=str(result.log_path))

        error_code = "playwright_launch_failed"
        if result.error:
            m = re.search(r'"error_code":\s*"([^"]+)"', result.error)
            if m:
                error_code = m.group(1)
        return VelogLoginResult(
            ok=False,
            message=_MESSAGES.get(error_code, _DEFAULT_FAIL_MSG),
            error_code=error_code,
            log_path=str(result.log_path),
        )

    def status(self) -> dict:
        """Current velog channel status (6 states) — single-sourced via the helper
        the publish-gating path also reads, so the card cannot disagree with it."""
        from ..helpers.contexts import _get_velog_status

        return _get_velog_status()
