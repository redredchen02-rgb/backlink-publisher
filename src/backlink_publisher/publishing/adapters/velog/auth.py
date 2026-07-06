"""Velog adapter — cookie-based authentication helpers.

Provides functions to load cookies from storage, extract tokens from browser
localStorage origins, and probe session liveness via GraphQL currentUser query.
"""

from __future__ import annotations

import json
from pathlib import Path

import requests

from backlink_publisher._util.errors import AuthExpiredError, DependencyError

from .constants import (
    _PROBE_QUERY,
    _PROBE_TIMEOUT,
    _VELOG_GRAPHQL_ENDPOINT,
    _VELOG_REQUIRED_HEADERS,
)


def _extract_tokens_from_origins(origins: object, cookies: dict[str, str]) -> None:
    """Mine velog auth tokens from browser-captured localStorage origins (mutates *cookies*).

    Handles the Playwright storage-state shape where auth lives in
    localStorage rather than the cookies list.  No-ops on non-list input.
    """
    if not isinstance(origins, list):
        return
    for origin in origins:
        if not isinstance(origin, dict):
            continue
        if "velog.io" not in str(origin.get("origin", "")):
            continue
        local_storage = origin.get("localStorage", [])
        if not isinstance(local_storage, list):
            continue
        for entry in local_storage:
            if not isinstance(entry, dict):
                continue
            key = str(entry.get("name", ""))
            val = str(entry.get("value", ""))
            if key == "account":
                try:
                    account = json.loads(val)
                except json.JSONDecodeError:
                    continue
                for token_key in ("access_token", "refresh_token", "token"):
                    token_val = account.get(token_key)
                    if token_val and token_key not in cookies:
                        cookies[token_key] = str(token_val)
            elif key in {"access_token", "refresh_token", "token"} and val and key not in cookies:
                cookies[key] = val


def _load_cookies(cookies_path: Path) -> dict[str, str]:
    """Load velog cookies from *cookies_path* (must be 0600).

    Returns a ``{name: value}`` dict suitable for ``requests`` ``cookies=``.

    Raises:
        DependencyError: file missing, wrong permissions, or unparseable.
        AuthExpiredError: no token found.
    """
    source_path = cookies_path
    if not source_path.exists():
        legacy_path = cookies_path.with_name("velog-storage-state.json")
        if legacy_path.exists():
            source_path = legacy_path
        else:
            raise DependencyError(
                f"velog cookies not found: {cookies_path}\n"
                "Run: velog-login"
            )

    from backlink_publisher._util.permissions import check_0600
    check_0600(source_path, label="velog-cookies.json")

    try:
        raw = json.loads(source_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise DependencyError(
            f"Cannot read velog cookies: {exc}\n"
            "Run: velog-login"
        ) from None

    cookie_list = raw.get("cookies", [])
    if not isinstance(cookie_list, list):
        cookie_list = []

    cookies = {
        c["name"]: c["value"]
        for c in cookie_list
        if isinstance(c, dict) and "name" in c and "value" in c
    }

    # Velog may persist auth in browser localStorage instead of cookies.
    # Preserve compatibility with both shapes by mining the captured
    # storage_state payload for an account token if needed.
    if not cookies or "access_token" not in cookies:
        _extract_tokens_from_origins(raw.get("origins", []), cookies)

    if not cookies:
        raise DependencyError(
            "velog-cookies.json is empty or has no usable auth data.\n"
            "Run: velog-login"
        )
    if not (cookies.get("access_token") or cookies.get("refresh_token")):
        raise AuthExpiredError(
            channel="velog",
            reason="velog credential file has no access_token or refresh_token",
        )
    return cookies


def _probe_session_alive(session: requests.Session) -> tuple[bool, str]:
    """Check whether *session*'s cookies are still valid via currentUser probe.

    Returns ``(True, username)`` when velog confirms the session is authenticated.
    Returns ``(False, reason)`` on any failure — network error, HTTP error, or
    a null/missing ``currentUser`` in the response.

    Fail-safe: network errors return ``(False, "probe_unreachable")`` so that a
    probe failure during a flaky network does not silently downgrade a real auth
    expiry into a content-rejected classification.
    """
    probe_payload = {"query": _PROBE_QUERY}
    try:
        resp = session.post(
            _VELOG_GRAPHQL_ENDPOINT,
            json=probe_payload,
            headers=_VELOG_REQUIRED_HEADERS,
            verify=True,
            timeout=_PROBE_TIMEOUT,
        )
    except requests.RequestException:
        return False, "probe_unreachable"

    if not resp.ok:
        return False, f"probe_http_{resp.status_code}"

    try:
        data = resp.json()
    except ValueError:
        return False, "probe_invalid_json"

    current_user = (data.get("data") or {}).get("currentUser")
    if not current_user or not current_user.get("id"):
        return False, "no_current_user"

    username = current_user.get("username", "")
    return True, username
