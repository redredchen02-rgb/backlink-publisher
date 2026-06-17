"""Live-verify probe implementations and shared result helpers.

Extracted from ``_verify_adapters.py`` (Wave 3 Unit 3).  Contains the
UTC timestamp helper, the six ``VerifyResult`` factory functions, the
``_verify_live`` dispatcher, and all per-platform live-probe implementations.

``_verify_live`` calls ``verify_adapter_setup(mode='offline')`` from
``_verify_setup`` — that import is at module level here; ``_verify_setup``
imports ``_verify_live`` lazily (inside ``verify_adapter_setup``) to avoid
a circular module-level dependency.

``_verify_adapters.py`` re-exports all public names for backward compatibility.
"""

from __future__ import annotations

from requests.exceptions import RequestException as _ReqException, Timeout as _ReqTimeout

from backlink_publisher.config import Config
from backlink_publisher._util.errors import DependencyError

from ._verify import VerifyResult
from .registry import registered_platforms
from ._verify_setup import verify_adapter_setup


# ── UTC timestamp helper ────────────────────────────────────────────


def _utc_now_iso() -> str:
    """UTC iso8601 timestamp for last_verified_at."""
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── Shared verify result helpers ────────────────────────────────────


def _ok_result(identity: str, *, dofollow: bool = True) -> VerifyResult:
    return VerifyResult(
        ok=True,
        identity=identity,
        last_verified_at=_utc_now_iso(),
        last_verify_result="ok",
        dofollow=dofollow,
    )


def _timeout_result(message: str) -> VerifyResult:
    return VerifyResult(
        ok=False,
        last_verify_result="timeout",
        blockers=[message],
    )


def _network_error(platform: str, error: Exception) -> VerifyResult:
    return VerifyResult(
        ok=False,
        last_verify_result="never",
        blockers=[f"{platform} network failure: {error}"],
    )


def _non_json(platform: str) -> VerifyResult:
    return VerifyResult(
        ok=False,
        last_verify_result="never",
        blockers=[f"{platform} returned non-JSON response"],
    )


def _token_expired(message: str) -> VerifyResult:
    return VerifyResult(
        ok=False,
        last_verify_result="token_expired",
        blockers=[message],
    )


def _never(message: str) -> VerifyResult:
    return VerifyResult(
        ok=False,
        last_verify_result="never",
        blockers=[message],
    )


# ── Live verify dispatcher ──────────────────────────────────────────


def _verify_live(platform: str, config: Config) -> VerifyResult:
    """Live verify — dispatches to per-platform real-API impls when available."""
    if platform not in registered_platforms():
        return VerifyResult(
            ok=False,
            last_verify_result="never",
            blockers=[f"no adapter configured for platform: {platform}"],
        )

    # Probe offline-readiness first — if not even configured, no point pinging API.
    try:
        verify_adapter_setup(platform, config, mode="offline")
    except DependencyError as e:
        return VerifyResult(
            ok=False,
            last_verify_result="never",
            blockers=[str(e)],
        )

    if platform == "telegraph":
        return _verify_telegraph_live(config)
    if platform == "ghpages":
        return _verify_ghpages_live(config)
    if platform == "blogger":
        return _verify_blogger_live(config)
    if platform == "velog":
        return _verify_velog_live(config)

    return VerifyResult(
        ok=True,
        last_verify_result="unverifiable_live",
        blockers=["live verify endpoint not yet implemented for this platform"],
    )


# ── Per-platform live probe implementations ─────────────────────────


def _verify_telegraph_live(config: Config) -> VerifyResult:
    from backlink_publisher.http import post as http_post
    from .adapters.telegraph_api import (
        TELEGRAPH_API,
        _HTTP_TIMEOUT_S,
        _INVALID_TOKEN_MARKERS,
        _load_token,
    )

    try:
        token_data = _load_token(config)
    except Exception as e:
        return _never(f"telegraph token file unreadable: {e}")

    access_token = token_data.get("access_token") if token_data else None
    if not access_token:
        return _never("telegraph token not yet created (publish once to auto-create)")

    verify_timeout = min(5, _HTTP_TIMEOUT_S)
    try:
        resp = http_post(
            f"{TELEGRAPH_API}/getAccountInfo",
            data={
                "access_token": access_token,
                "fields": '["short_name","author_name","page_count"]',
            },
            timeout=verify_timeout,
        )
    except _ReqTimeout:
        return _timeout_result(
            f"telegraph getAccountInfo timed out after {verify_timeout}s"
        )
    except _ReqException as e:
        return _network_error("telegraph", e)

    try:
        body = resp.json()
    except Exception:
        return _non_json("telegraph")

    if not body.get("ok"):
        err = str(body.get("error", "unknown"))
        if any(marker in err for marker in _INVALID_TOKEN_MARKERS):
            return _token_expired(f"telegraph token rejected: {err}")
        return _never(f"telegraph API error: {err}")

    result_data = body.get("result") or {}
    identity = result_data.get("short_name") or token_data.get("short_name")
    return _ok_result(identity)


_GHPAGES_VERIFY_TIMEOUT_S = 5


def _verify_ghpages_live(config: Config) -> VerifyResult:
    from backlink_publisher.http import get as http_get
    from .adapters.ghpages import GITHUB_API, _load_token, _required_headers

    try:
        token = _load_token(config)
    except DependencyError as e:
        return _never(str(e))

    try:
        resp = http_get(
            f"{GITHUB_API}/user",
            headers=_required_headers(token),
            timeout=_GHPAGES_VERIFY_TIMEOUT_S,
        )
    except _ReqTimeout:
        return _timeout_result(
            f"github.com/user timed out after {_GHPAGES_VERIFY_TIMEOUT_S}s"
        )
    except _ReqException as e:
        return _network_error("github", e)

    if resp.status_code == 401:
        return _token_expired(
            "GitHub PAT rejected (HTTP 401) — regenerate at "
            "github.com/settings/tokens and re-save to ghpages-token.json"
        )
    if resp.status_code == 403:
        retry_after = resp.headers.get("retry-after")
        suffix = f" (retry-after={retry_after}s)" if retry_after else ""
        return _never(
            f"GitHub /user forbidden (HTTP 403){suffix} — token missing scope "
            "or hit secondary rate limit"
        )
    if resp.status_code != 200:
        return _never(f"GitHub /user returned HTTP {resp.status_code}")

    try:
        body = resp.json()
    except Exception:
        return _non_json("GitHub /user")

    identity = body.get("login") or body.get("name")
    return _ok_result(identity)


_BLOGGER_USERS_SELF = "https://www.googleapis.com/blogger/v3/users/self"
_BLOGGER_VERIFY_TIMEOUT_S = 5


def _verify_blogger_live(config: Config) -> VerifyResult:
    from backlink_publisher.http import get as http_get
    from backlink_publisher.config import load_blogger_token

    try:
        token_data = load_blogger_token(config.blogger_token_path)
    except Exception as e:
        return _never(f"blogger token file unreadable: {e}")

    access_token = (token_data or {}).get("token")
    if not access_token:
        return _never(
            "blogger access token not stored yet (bind via /settings or publish once)"
        )

    try:
        resp = http_get(
            _BLOGGER_USERS_SELF,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=_BLOGGER_VERIFY_TIMEOUT_S,
        )
    except _ReqTimeout:
        return _timeout_result(
            f"blogger users.self timed out after {_BLOGGER_VERIFY_TIMEOUT_S}s"
        )
    except _ReqException as e:
        return _network_error("blogger", e)

    if resp.status_code == 401:
        return _token_expired(
            "blogger access token expired or revoked — re-bind from /settings "
            "(access tokens are 1h; refresh happens on publish)"
        )
    if resp.status_code != 200:
        return _never(f"blogger users.self returned HTTP {resp.status_code}")

    try:
        body = resp.json()
    except Exception:
        return _non_json("blogger")

    identity = body.get("displayName") or body.get("id")
    return _ok_result(identity)


_VELOG_VERIFY_TIMEOUT_S = 5
_VELOG_CURRENT_USER_QUERY = (
    "query CurrentUser { "
    "auth { id username email is_trusted profile { id thumbnail display_name } } "
    "}"
)


def _verify_velog_live(config: Config) -> VerifyResult:
    from backlink_publisher.http import post as http_post
    from .adapters.velog_graphql import (
        _VELOG_GRAPHQL_ENDPOINT,
        _VELOG_REQUIRED_HEADERS,
        _load_cookies,
    )

    velog_cfg = config.velog
    cookies_path = (
        velog_cfg.cookies_path
        if velog_cfg
        else config.config_dir / "velog-cookies.json"
    )

    try:
        cookies = _load_cookies(cookies_path)
    except DependencyError as e:
        return _never(str(e))

    try:
        resp = http_post(
            _VELOG_GRAPHQL_ENDPOINT,
            json={"query": _VELOG_CURRENT_USER_QUERY},
            cookies=cookies,
            headers=_VELOG_REQUIRED_HEADERS,
            timeout=_VELOG_VERIFY_TIMEOUT_S,
        )
    except _ReqTimeout:
        return _timeout_result(
            f"velog auth probe timed out after {_VELOG_VERIFY_TIMEOUT_S}s"
        )
    except _ReqException as e:
        return _network_error("velog", e)

    if resp.status_code != 200:
        return _never(f"velog GraphQL returned HTTP {resp.status_code}")

    try:
        body = resp.json()
    except (ValueError, Exception):
        return _non_json("velog")

    current_user = ((body or {}).get("data") or {}).get("auth")
    if current_user is None:
        return _token_expired(
            "velog cookie session expired or revoked — run velog-login again"
        )

    identity = current_user.get("username") or current_user.get("display_name")
    return _ok_result(identity)
