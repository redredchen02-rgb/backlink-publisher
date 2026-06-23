"""OAuthAPI — OAuth credential-management operations, transport-neutral.

Phase-A facade (Plan 2026-06-18-002 U7, Settings security increment). The two
API-appropriate OAuth credential mutations were **moved here, not copied**, from
``routes/oauth.py``:

  * ``clear_medium``  — revoke a stored Medium token (delete medium-token.json).
  * ``save_blogger``  — persist the Blogger Client ID / Secret, with the
                        blank-secret-preserves-stored rule single-sourced here.

Both the legacy ``/settings/{clear-medium-oauth,save-blogger-oauth}`` HTML routes
and the new ``/api/v1/settings/{medium-oauth/clear,blogger-oauth}`` JSON bindings
call these and only differ in how they render the neutral :class:`OAuthResult`.

NOT migrated (deliberately): the Blogger ``oauth-start`` → Google → ``oauth-callback``
redirect handshake. The callback is Google's top-level browser redirect target and
MUST answer with a browser redirect (it cannot be a JSON ``/api/v1`` endpoint), so
that matched pair stays as legacy browser-navigation routes — see ``routes/oauth.py``.

``load_config`` / ``save_config`` / ``os`` are module-top imports so tests patch
them here (the logic moved, so the patch targets follow it). This module performs
no transport concerns — it never touches ``flask.request`` and never aborts.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from backlink_publisher.config import load_config, save_config


@dataclass(frozen=True)
class OAuthResult:
    """Transport-neutral outcome of an OAuth credential operation.

    ``level`` drives the legacy flash type (success / warning / danger).
    ``error_class`` is set only on failure and selects the ``/api/v1`` status:
    ``invalid_request`` → 422, ``persistence_failure`` → 502.
    """

    level: str
    message: str
    fragment: str
    error_class: str | None = None

    @property
    def ok(self) -> bool:
        return self.error_class is None


class OAuthAPI:
    """Stateless facade; instantiate per call (mirrors the other api/*_api facades)."""

    def clear_medium(self) -> OAuthResult:
        """Revoke a stored Medium token by deleting medium-token.json."""
        try:
            from backlink_publisher.config import _config_dir
            token_file = _config_dir() / "medium-token.json"
            if token_file.exists():
                os.remove(token_file)
            return OAuthResult("success", "Medium OAuth 授权已清除", "channel-medium")
        except Exception as e:
            return OAuthResult("danger", f"清除失败: {e}", "channel-medium",
                               error_class="persistence_failure")

    def revoke_blogger(self) -> OAuthResult:
        """Revoke Blogger authorization by deleting the stored token file (moved
        from the legacy ``/settings/revoke-blogger`` route)."""
        cfg = load_config()
        try:
            cfg.blogger_token_path.unlink(missing_ok=True)
            return OAuthResult("success", "Blogger 授权已撤销", "channel-blogger")
        except Exception as e:
            return OAuthResult("danger", f"撤销失败: {e}", "channel-blogger",
                               error_class="persistence_failure")

    def blogger_status(self) -> dict:
        """Read-only Blogger card state: authorization + the saved OAuth client.
        No secrets — ``client_id`` is the public app id (the legacy template renders
        it too); the secret is exposed ONLY as ``client_secret_set``."""
        from backlink_publisher.config.tokens import load_blogger_token

        from ..helpers.security import _oauth_callback_uri

        cfg = load_config()
        return {
            "authorized": bool(load_blogger_token(cfg.blogger_token_path)),
            "client_id": cfg.blogger_oauth.client_id if cfg.blogger_oauth else "",
            "client_secret_set": bool(cfg.blogger_oauth and cfg.blogger_oauth.client_secret),
            "callback_uri": _oauth_callback_uri(),
        }

    def save_blogger(self, client_id: str, client_secret: str) -> OAuthResult:
        """Persist Blogger Client ID / Secret. A blank secret preserves the stored
        one (the template no longer round-trips the secret in HTML)."""
        client_id = (client_id or "").strip()
        client_secret = (client_secret or "").strip()
        cfg_existing = load_config()
        if not client_secret and cfg_existing.blogger_oauth:
            client_secret = cfg_existing.blogger_oauth.client_secret or ""
        if not client_id or not client_secret:
            return OAuthResult("warning", "请填写 Client ID 和 Client Secret",
                               "channel-blogger", error_class="invalid_request")
        try:
            save_config(cfg_existing,
                        blogger_client_id=client_id,
                        blogger_client_secret=client_secret,
                        target_three_url=None)
            return OAuthResult(
                "success",
                "凭据已确认绑定，可随时点击「使用 Google 帐号登入」完成授权",
                "channel-blogger",
            )
        except Exception as e:
            return OAuthResult("danger", f"保存失败: {e}", "channel-blogger",
                               error_class="persistence_failure")
