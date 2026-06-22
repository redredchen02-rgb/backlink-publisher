"""MediumLoginAPI — Medium browser-login flow (launch / probe / clear),
transport-neutral.

Phase-A facade (Plan 2026-06-18-002 U7, Settings increment). The dispatch +
outcome classification of the three ``/settings/medium/*-browser-login`` routes was
**moved here, not copied**, from ``routes/medium_login.py``: each method loads the
config, calls the Playwright helper (``launch_login_window`` / ``probe_login_status``
/ ``clear_browser_profile``), and maps the result — or a ``DependencyError`` /
``ExternalServiceError`` — into a neutral :class:`MediumLoginResult`.

Stateful seam: the routes persist a ``session["medium_probe_logged_in"]`` flag used
by publish-gating. This module never touches ``flask.session`` (a transport
concern) — instead the result carries a ``session_op`` *decision* (``set`` / ``clear``
/ ``keep``) that each transport applies. This mirrors the BindAPI outcome-capture
pattern: the decision is single-sourced, the mutation stays at the edge.

The helpers are imported at module top so the redirect-sanitization tests can patch
``webui_app.api.medium_login_api.{launch_login_window,probe_login_status,
clear_browser_profile}`` — the names the dispatch now resolves through.
"""

from __future__ import annotations

from dataclasses import dataclass

from backlink_publisher._util.errors import DependencyError, ExternalServiceError
from backlink_publisher.config import load_config

from ..helpers._request_cache import _g_cache
from ..medium_login import (
    clear_browser_profile,
    launch_login_window,
    probe_login_status,
)


@dataclass(frozen=True)
class MediumLoginResult:
    """Transport-neutral outcome of a medium browser-login action.

    ``level`` is the flash severity / SPA toast class. ``session_op`` tells the
    transport how to mutate the ``medium_probe_logged_in`` publish-gating flag:
    ``set`` → write ``logged_in``; ``clear`` → pop it; ``keep`` → leave it. The
    fragment anchors the legacy flash back to the medium channel card.
    """

    level: str
    message: str
    session_op: str = "keep"  # "set" | "clear" | "keep"
    logged_in: bool = False  # value written when session_op == "set"
    fragment: str = "channel-medium"


class MediumLoginAPI:
    """Stateless facade; instantiate per call (mirrors the other api/*_api facades)."""

    def launch(self) -> MediumLoginResult:
        """Open a headed Chromium for the user to log in to Medium."""
        cfg = _g_cache("config", load_config)
        try:
            result = launch_login_window(cfg)
            return MediumLoginResult(
                "success", "Medium 浏览器登录完成！",
                session_op="set", logged_in=result.get("logged_in", False),
            )
        except DependencyError as e:
            return MediumLoginResult("warning", str(e))
        except ExternalServiceError as e:
            return MediumLoginResult("danger", str(e))

    def probe(self) -> MediumLoginResult:
        """Probe Medium login state via a short Playwright navigation."""
        cfg = _g_cache("config", load_config)
        try:
            result = probe_login_status(cfg)
            if result["logged_in"]:
                name = f" (@{result['username']})" if result.get("username") else ""
                return MediumLoginResult(
                    "info", f"Medium 登录有效{name}，发布通道就绪",
                    session_op="set", logged_in=True,
                )
            return MediumLoginResult(
                "info", "Medium 未登录，请点击「打开浏览器登录」完成登录",
                session_op="clear",
            )
        except DependencyError as e:
            return MediumLoginResult("warning", str(e))
        except ExternalServiceError as e:
            return MediumLoginResult("warning", str(e))

    def clear(self) -> MediumLoginResult:
        """Delete the persistent Chromium profile (clears stored login cookies)."""
        cfg = _g_cache("config", load_config)
        try:
            clear_browser_profile(cfg)
            return MediumLoginResult(
                "success", "浏览器登录已清除；下次发布前请重新登录",
                session_op="clear",
            )
        except Exception as e:
            return MediumLoginResult("danger", f"清除失败: {e}")
