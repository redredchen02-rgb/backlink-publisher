"""Flask-free OAuth helpers — Plan 2026-06-01-001 Unit 5.

Extracted from routes/oauth.py. Route keeps session, redirect, and
google_auth_oauthlib.Flow calls (can't be unit-tested without mocking
the full OAuth round-trip). This module is import-safe under any context.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from urllib.parse import urlparse

_OAUTH_ENV_VAR = "OAUTHLIB_INSECURE_TRANSPORT"
_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})

# Standard Blogger OAuth endpoints (not secrets — documented by Google).
_BLOGGER_AUTH_URI = "https://accounts.google.com/o/oauth2/auth"
_BLOGGER_TOKEN_URI = "https://oauth2.googleapis.com/token"


def is_loopback_uri(uri: str) -> bool:
    """Return True when *uri* points to a loopback host.

    Handles bare ``::1`` netloc (non-bracketed IPv6) which urlparse
    cannot resolve to a ``hostname`` attribute but is still a valid
    loopback address when it appears literally in the netloc.
    """
    try:
        parsed = urlparse(uri)
        host = (parsed.hostname or "").lower()
        # urlparse("http://::1/...").hostname is None; check netloc directly.
        netloc = parsed.netloc.lower()
        return host in _LOOPBACK_HOSTS or netloc in _LOOPBACK_HOSTS
    except Exception:
        return False


@contextmanager
def oauthlib_insecure_transport(callback_uri: str):
    """Scope OAUTHLIB_INSECURE_TRANSPORT to a single OAuth handler.

    Refuses to enable the bypass when *callback_uri* is not a loopback host —
    that situation requires real TLS and the bypass would be a downgrade.

    Raises:
        RuntimeError: If *callback_uri* is not a loopback address.
    """
    if not is_loopback_uri(callback_uri):
        raise RuntimeError(
            f"refusing to enable OAUTHLIB_INSECURE_TRANSPORT: "
            f"callback URI {callback_uri!r} is not loopback. "
            f"Off-loopback OAuth must use https without the bypass."
        )
    prev = os.environ.get(_OAUTH_ENV_VAR)
    os.environ[_OAUTH_ENV_VAR] = "1"
    try:
        yield
    finally:
        if prev is None:
            os.environ.pop(_OAUTH_ENV_VAR, None)
        else:
            os.environ[_OAUTH_ENV_VAR] = prev


def build_blogger_client_config(
    client_id: str, client_secret: str, cb_uri: str
) -> dict:
    """Build the google-auth-oauthlib client config dict for Blogger OAuth."""
    return {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uris": ["http://localhost", cb_uri],
            "auth_uri": _BLOGGER_AUTH_URI,
            "token_uri": _BLOGGER_TOKEN_URI,
        }
    }
