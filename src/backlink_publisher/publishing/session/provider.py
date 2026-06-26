"""Credential loading, probing, and refreshing for channel sessions."""

from __future__ import annotations

from abc import ABC, abstractmethod
import json
import os
from pathlib import Path
from typing import Any, cast

import requests

from backlink_publisher._util.errors import (
    AuthExpiredError,
    DependencyError,
    ExternalServiceError,
)
from backlink_publisher._util.http_client import http_client
from backlink_publisher._util.logger import opencli_logger as log
from backlink_publisher.config import Config
from backlink_publisher.config.tokens import (
    load_blogger_token,
    load_medium_integration_token,
    load_medium_token,
    save_blogger_token,
)
from backlink_publisher.publishing._manifest_types import (
    RefreshConfig,
    SessionDescriptor,
)

from .credential import Credential


class CredentialProvider(ABC):
    """Abstract interface for credential lifecycle operations.

    Three operations, all driven by the ``SessionDescriptor`` declared in
    the channel manifest. ``load`` is channel-specific (cookie file, OAuth
    token JSON, bearer token); ``probe`` and ``refresh`` are generic enough
    to reuse the same implementation across channels.
    """

    @abstractmethod
    def load(
        self, channel: str, config: Config, descriptor: SessionDescriptor
    ) -> Credential:
        """Load credential data for *channel* from its stored artifact.

        Raises ``DependencyError`` when the credential file is missing or
        unreadable, ``AuthExpiredError`` when the stored credential has
        no usable auth data.
        """
        ...

    @abstractmethod
    def probe(
        self, session: requests.Session, descriptor: SessionDescriptor
    ) -> tuple[bool, str]:
        """Check whether *session* is still authenticated.

        Returns ``(True, reason)`` on success (reason = probe response
        value), ``(False, reason)`` on failure (reason = error code).
        """
        ...

    @abstractmethod
    def refresh(
        self,
        credential: Credential,
        descriptor: SessionDescriptor,
        config: Config,
        channel: str = "unknown",
    ) -> Credential | None:
        """Attempt to refresh *credential*.

        Returns updated ``Credential`` on success, ``None`` when the
        descriptor declares ``cookie-implicit`` (no-op — ``Set-Cookie``
        from a normal request handles the refresh).
        Raises ``AuthExpiredError`` when refresh is needed but fails.
        """
        ...


class DefaultCredentialProvider(CredentialProvider):
    """Default implementation supporting cookie, bearer, and OAuth types.

    Platform-specific loaders are registered in the ``load()`` dispatch
    by channel name. The generic ``probe()`` and ``refresh()`` work for
    any channel that declares a ``SessionDescriptor`` with the correct
    ``ProbeConfig`` / ``RefreshConfig``.
    """

    # ── Public interface ────────────────────────────────────────────────────

    def load(
        self, channel: str, config: Config, descriptor: SessionDescriptor
    ) -> Credential:
        loader = _LOADERS.get(channel)
        if loader is None:
            raise DependencyError(
                f"No credential loader registered for channel: {channel!r}"
            )
        return cast("Credential", loader(self, config, descriptor))

    def probe(
        self, session: requests.Session, descriptor: SessionDescriptor
    ) -> tuple[bool, str]:
        """Generic liveness probe via configured endpoint.

        Sends the probe request as declared in ``descriptor.probe`` and
        checks whether the response JSON contains non-null values at the
        expected shape path. Returns ``(True, value)`` on success,
        ``(False, error_reason)`` on failure.
        """
        probe = descriptor.probe
        if probe is None:
            return True, "no_probe_configured"

        try:
            if probe.http_method == "POST" and probe.graphql_query:
                payload: dict[str, Any] = {"query": probe.graphql_query}
                resp = session.post(
                    probe.endpoint,
                    json=payload,
                    headers=dict(probe.headers or {}),
                    timeout=probe.timeout_sec,
                )
            else:
                resp = session.get(
                    probe.endpoint,
                    headers=dict(probe.headers or {}),
                    timeout=probe.timeout_sec,
                )
        except requests.RequestException as exc:
            return False, f"probe_unreachable: {exc}"

        if not resp.ok:
            return False, f"probe_http_{resp.status_code}"

        if not probe.shape:
            return True, "probe_ok"

        try:
            data = resp.json()
        except ValueError:
            return False, "probe_invalid_json"

        current: Any = data
        for key in probe.shape:
            if not isinstance(current, dict):
                return False, f"probe_missing_{key}"
            current = current.get(key)
            if current is None:
                return False, f"probe_null_{key}"

        return True, str(current)

    def refresh(
        self,
        credential: Credential,
        descriptor: SessionDescriptor,
        config: Config,
        channel: str = "unknown",
    ) -> Credential | None:
        """Refresh credential per the descriptor's refresh config.

        Routes to the appropriate refresh implementation based on
        ``descriptor.refresh.method``.
        """
        refresh_cfg = descriptor.refresh
        if refresh_cfg is None:
            return None

        if refresh_cfg.method == "cookie-implicit":
            return None

        if refresh_cfg.method == "oauth-refresh-token":
            return self._oauth_refresh(
                credential, refresh_cfg, descriptor.config_path, config, channel
            )

        raise ExternalServiceError(
            f"Unknown refresh method: {refresh_cfg.method!r}"
        )

    # ── Helpers ─────────────────────────────────────────────────────────────

    def _resolve_config_path(self, path_template: str, config: Config) -> Path:
        """Replace ``<config_dir>`` placeholder with the actual config dir."""
        resolved = path_template.replace("<config_dir>", str(config.config_dir))
        return Path(resolved)

    def _oauth_refresh(
        self,
        credential: Credential,
        refresh_cfg: RefreshConfig,
        config_path_template: str,
        config: Config,
        channel: str = "unknown",
    ) -> Credential:
        """Perform OAuth2 ``refresh_token`` grant via generic POST.

        Replaces per-provider refresh libraries (e.g. ``google-auth``)
        with a direct POST to the token endpoint using stored client
        credentials. Saves the updated token back to the credential
        file on success.
        """
        refresh_token = credential.refresh_token
        if not refresh_token:
            refresh_token = (
                credential.oauth_data or {}
            ).get("refresh_token")
        if not refresh_token:
            raise AuthExpiredError(
                channel=channel,
                reason="OAuth token has no refresh_token; cannot refresh",
            )

        oauth = credential.oauth_data or {}
        client_id = oauth.get("client_id", "")
        client_secret = oauth.get("client_secret", "")

        payload = {
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }

        try:
            resp = http_client.post(
                refresh_cfg.token_endpoint or "",
                data=payload,
                timeout=30,
                raise_for_status=False,
            )
        except ExternalServiceError as exc:
            raise AuthExpiredError(
                channel=channel,
                reason=f"OAuth refresh failed (unreachable): {exc}",
            ) from None

        if not resp.ok:
            raise AuthExpiredError(
                channel=channel,
                reason=f"OAuth refresh failed (HTTP {resp.status_code}): "
                f"{resp.text[:200]}",
            )

        token_data = resp.json()
        new_token = token_data.get("access_token", "")
        if not new_token:
            raise AuthExpiredError(
                channel=channel,
                reason="OAuth refresh returned no access_token",
            )

        # Merge new token data into stored credential — preserve fields
        # the refresh response may omit (token_uri, client_id, etc.).
        merged = dict(oauth)
        merged["token"] = new_token
        if token_data.get("refresh_token"):
            merged["refresh_token"] = token_data["refresh_token"]

        # Persist back to the credential file
        try:
            token_path = self._resolve_config_path(
                config_path_template, config
            )
            save_blogger_token(merged, token_path)
        except Exception:
            log.warning("Failed to persist refreshed OAuth token")

        return Credential(
            type="oauth",
            oauth_data=merged,
            token=new_token,
            refresh_token=merged.get("refresh_token"),
            expires_at=token_data.get("expires_at"),
        )


# ── Platform-specific loaders ─────────────────────────────────────────────


def _load_velog_cookies(
    provider: DefaultCredentialProvider,
    config: Config,
    descriptor: SessionDescriptor,
) -> Credential:
    """Load Velog cookies from Playwright storage-state JSON.

    Supports both the current ``velog-cookies.json`` and the legacy
    ``velog-storage-state.json`` name for backward compatibility.
    """
    cookies_path = provider._resolve_config_path(
        descriptor.config_path, config
    )
    if not cookies_path.exists():
        legacy = cookies_path.with_name("velog-storage-state.json")
        if legacy.exists():
            cookies_path = legacy
        else:
            raise DependencyError(
                f"velog cookies not found: {cookies_path}\n"
                "Run: velog-login"
            )

    mode = os.stat(cookies_path).st_mode & 0o777
    if mode != 0o600:
        raise DependencyError(
            f"velog-cookies.json must be 0600 (found {oct(mode)})\n"
            f"Run: chmod 600 {cookies_path}"
        )

    try:
        raw = json.loads(cookies_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise DependencyError(
            f"Cannot read velog cookies: {exc}\nRun: velog-login"
        ) from None

    cookies: dict[str, str] = {}
    cookie_list = raw.get("cookies", [])
    if isinstance(cookie_list, list):
        for c in cookie_list:
            if isinstance(c, dict) and "name" in c and "value" in c:
                cookies[c["name"]] = c["value"]

    # Mine localStorage origins for token values
    origins = raw.get("origins", [])
    if isinstance(origins, list):
        for origin in origins:
            if not isinstance(origin, dict):
                continue
            if "velog.io" not in str(origin.get("origin", "")):
                continue
            for entry in (origin.get("localStorage") or []):
                if not isinstance(entry, dict):
                    continue
                key = str(entry.get("name", ""))
                val = str(entry.get("value", ""))
                if key == "account":
                    try:
                        account = json.loads(val)
                    except json.JSONDecodeError:
                        continue
                    for tk in ("access_token", "refresh_token", "token"):
                        tv = account.get(tk)
                        if tv:
                            cookies.setdefault(tk, str(tv))
                elif key in {"access_token", "refresh_token", "token"}:
                    if val:
                        cookies.setdefault(key, val)

    if not cookies:
        raise DependencyError(
            "velog-cookies.json has no usable auth data.\nRun: velog-login"
        )

    # At least one token-family key must be present
    has_token = any(
        k in cookies for k in ("access_token", "refresh_token", "token")
    )
    if not has_token:
        raise AuthExpiredError(
            channel="velog",
            reason="velog credential file has no access_token or refresh_token",
        )

    return Credential(type="cookie", cookies=cookies)


def _load_medium_token(
    provider: DefaultCredentialProvider,
    config: Config,
    descriptor: SessionDescriptor,
) -> Credential:
    """Load Medium OAuth token or fallback Integration Token.

    Precedence: OAuth access_token → Integration Token file → TOML config.
    """
    token_data = load_medium_token()
    token: str | None = None
    refresh_token: str | None = None
    expires_at: float | None = None
    oauth_data: dict[str, Any] | None = None

    if token_data:
        token = token_data.get("access_token")
        refresh_token = token_data.get("refresh_token")
        expires_at = token_data.get("expires_at")
        oauth_data = token_data

    if not token:
        it_data = load_medium_integration_token()
        token = None
        if it_data:
            token = (it_data.get("integration_token") or "").strip() or None

    if not token:
        token = getattr(config, "medium_integration_token", None)

    if not token:
        raise DependencyError(
            "Medium access token or integration token not configured"
            " — please authorize via Settings → Medium 授权"
        )

    return Credential(
        type="bearer",
        token=token,
        oauth_data=oauth_data,
        expires_at=expires_at,
        refresh_token=refresh_token,
    )


def _load_blogger_oauth(
    provider: DefaultCredentialProvider,
    config: Config,
    descriptor: SessionDescriptor,
) -> Credential:
    """Load Blogger OAuth token data from JSON file."""
    token_path = provider._resolve_config_path(
        descriptor.config_path, config
    )
    token_data = load_blogger_token(token_path)

    if not token_data:
        raise DependencyError(
            "Blogger token not configured"
            " — please authorize via Settings → Blogger 授权"
        )

    return Credential(
        type="oauth",
        oauth_data=token_data,
        token=token_data.get("token"),
        refresh_token=token_data.get("refresh_token"),
        expires_at=token_data.get("expires_at"),
    )


def _load_substack_cookies(
    provider: DefaultCredentialProvider,
    config: Config,
    descriptor: SessionDescriptor,
) -> Credential:
    """Load Substack cookies from Playwright storage-state JSON.

    Reads ``substack-credentials.json`` which stores cookies exported from
    a logged-in ``substack.com`` session (same format as velog-cookies.json).
    """
    cookies_path = provider._resolve_config_path(
        descriptor.config_path, config
    )
    if not cookies_path.exists():
        raise DependencyError(
            f"Substack cookies not found: {cookies_path}\n"
            "Export cookies from a logged-in substack.com session.\n"
            "Save as 'substack-credentials.json' (chmod 600)."
        )

    mode = os.stat(cookies_path).st_mode & 0o777
    if mode != 0o600:
        raise DependencyError(
            f"substack-credentials.json must be 0600 (found {oct(mode)})\n"
            f"Run: chmod 600 {cookies_path}"
        )

    try:
        raw = json.loads(cookies_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        raise DependencyError(
            "Cannot read Substack credentials: file missing, corrupt, or unreadable"
        ) from None

    cookie_list = raw.get("cookies", [])
    if not isinstance(cookie_list, list):
        raise DependencyError("Substack credentials missing 'cookies' array")

    cookies: dict[str, str] = {
        c["name"]: c["value"]
        for c in cookie_list
        if isinstance(c, dict) and "name" in c and "value" in c
    }

    if not cookies:
        raise DependencyError(
            "substack-credentials.json has no usable cookies.\n"
            "Re-export cookies from a logged-in substack.com session."
        )

    return Credential(type="cookie", cookies=cookies)


# Registration table for load() dispatch
_LOADERS: dict[str, Any] = {
    "velog": _load_velog_cookies,
    "medium": _load_medium_token,
    "blogger": _load_blogger_oauth,
    "substack": _load_substack_cookies,
}
