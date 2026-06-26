"""SessionManager tests — credential lifecycle integration.

Tests the ``SessionManager`` class: descriptor lookup, credential loading,
refresh-on-expiry, session auth application, and liveness probing.
"""
from __future__ import annotations

__tier__ = "unit"
import time
from unittest.mock import MagicMock, patch

import pytest
import requests

from backlink_publisher._util.errors import AuthExpiredError, DependencyError
from backlink_publisher.publishing._manifest_types import (
    ProbeConfig,
    RefreshConfig,
    SessionDescriptor,
)
from backlink_publisher.publishing.session import Credential, SessionManager

# ── Fixtures ────────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_provider():
    return MagicMock()


@pytest.fixture
def mgr(mock_provider):
    return SessionManager(mock_provider)


@pytest.fixture
def cookie_descriptor():
    return SessionDescriptor(
        credential_type="cookie",
        config_path="<config_dir>/velog-cookies.json",
        probe=ProbeConfig(
            endpoint="https://v3.velog.io/graphql",
            http_method="POST",
            graphql_query="{ currentUser { id username } }",
            shape=("data", "currentUser", "id"),
            timeout_sec=10,
            headers={"content-type": "application/json"},
        ),
        refresh=RefreshConfig(method="cookie-implicit"),
    )


@pytest.fixture
def cookie_credential():
    return Credential(type="cookie", cookies={"sid": "abc", "velog_id": "123"})


# ── get_session — happy path ────────────────────────────────────────────────────

class TestGetSession:
    def test_happy_path(self, mgr, mock_provider, cookie_descriptor, cookie_credential):
        """Valid descriptor + credential + probe → authenticated requests.Session."""
        with patch(
            "backlink_publisher.publishing.session.session_manager.get_descriptor",
            return_value=cookie_descriptor,
        ):
            mock_provider.load.return_value = cookie_credential
            mock_provider.probe.return_value = (True, "testuser")

            session = mgr.get_session("velog", MagicMock())

        assert isinstance(session, requests.Session)
        # Cookies from credential should be attached
        assert session.cookies.get("sid") == "abc"
        assert session.cookies.get("velog_id") == "123"

    def test_no_descriptor_raises(self, mgr, mock_provider):
        """Channel without a SessionDescriptor → DependencyError."""
        with patch(
            "backlink_publisher.publishing.session.session_manager.get_descriptor",
            return_value=None,
        ):
            with pytest.raises(DependencyError) as exc:
                mgr.get_session("telegraph", MagicMock())
        assert "No SessionDescriptor registered" in str(exc.value)

    def test_probe_failure_raises(self, mgr, mock_provider, cookie_descriptor, cookie_credential):
        """Session whose liveness probe fails → AuthExpiredError."""
        with patch(
            "backlink_publisher.publishing.session.session_manager.get_descriptor",
            return_value=cookie_descriptor,
        ):
            mock_provider.load.return_value = cookie_credential
            mock_provider.probe.return_value = (False, "no_current_user")

            with pytest.raises(AuthExpiredError) as exc:
                mgr.get_session("velog", MagicMock())
        assert "expired" in str(exc.value).lower()

    def test_load_error_propagates(self, mgr, mock_provider, cookie_descriptor):
        """When provider.load() raises DependencyError, it propagates."""
        with patch(
            "backlink_publisher.publishing.session.session_manager.get_descriptor",
            return_value=cookie_descriptor,
        ):
            mock_provider.load.side_effect = DependencyError(
                "velog cookies not found: /path/to/cookies\nRun: velog-login"
            )

            with pytest.raises(DependencyError) as exc:
                mgr.get_session("velog", MagicMock())
        assert "velog cookies not found" in str(exc.value)


# ── _maybe_refresh ──────────────────────────────────────────────────────────────

class TestMaybeRefresh:
    def test_refresh_within_window(self, mgr, mock_provider):
        """Credential near expiry → provider.refresh is called."""
        cred = Credential(
            type="oauth",
            token="tok",
            refresh_token="rtok",
            expires_at=time.time() + 10,  # expires in 10s (within 300s window)
        )
        descriptor = SessionDescriptor(
            credential_type="oauth",
            refresh=RefreshConfig(
                method="oauth-refresh-token",
                token_endpoint="https://example.com/refresh",
            ),
        )
        mock_provider.refresh.return_value = Credential(
            type="oauth", token="new_tok", refresh_token="new_rtok",
        )

        result = mgr._maybe_refresh(cred, descriptor, MagicMock())

        mock_provider.refresh.assert_called_once()
        assert result.token == "new_tok"

    def test_no_refresh_when_far_from_expiry(self, mgr, mock_provider):
        """Credential far from expiry → provider.refresh is NOT called."""
        cred = Credential(
            type="oauth",
            token="tok",
            expires_at=time.time() + 3600,  # expires in 1h (beyond 300s window)
        )
        descriptor = SessionDescriptor(
            credential_type="oauth",
            refresh=RefreshConfig(
                method="oauth-refresh-token",
                token_endpoint="https://example.com/refresh",
            ),
        )

        result = mgr._maybe_refresh(cred, descriptor, MagicMock())

        mock_provider.refresh.assert_not_called()
        assert result is cred

    def test_no_refresh_when_no_expires_at(self, mgr, mock_provider):
        """Credential without expires_at → no refresh attempt."""
        cred = Credential(type="cookie", cookies={"sid": "x"})
        descriptor = SessionDescriptor(credential_type="cookie")

        result = mgr._maybe_refresh(cred, descriptor, MagicMock())

        mock_provider.refresh.assert_not_called()
        assert result is cred

    def test_no_refresh_when_no_refresh_config(self, mgr, mock_provider):
        """Descriptor without refresh config → no refresh attempt."""
        cred = Credential(type="bearer", token="tok", expires_at=time.time() + 5)
        descriptor = SessionDescriptor(credential_type="bearer")

        result = mgr._maybe_refresh(cred, descriptor, MagicMock())

        mock_provider.refresh.assert_not_called()
        assert result is cred

    def test_refresh_returns_none_noop(self, mgr, mock_provider):
        """When provider.refresh returns None (cookie-implicit) → original cred kept."""
        cred = Credential(
            type="cookie",
            cookies={"sid": "x"},
            expires_at=time.time() + 10,
        )
        descriptor = SessionDescriptor(
            credential_type="cookie",
            refresh=RefreshConfig(method="cookie-implicit"),
        )
        mock_provider.refresh.return_value = None

        result = mgr._maybe_refresh(cred, descriptor, MagicMock())

        mock_provider.refresh.assert_called_once()
        assert result is cred


# ── _apply_session ──────────────────────────────────────────────────────────────

class TestApplySession:
    def test_cookie_auth(self, mgr):
        """Cookie credential populates session cookies."""
        session = requests.Session()
        cred = Credential(type="cookie", cookies={"sid": "abc", "my_id": "42"})
        descriptor = SessionDescriptor(credential_type="cookie")

        mgr._apply_session(session, cred, descriptor)

        assert session.cookies.get("sid") == "abc"
        assert session.cookies.get("my_id") == "42"

    def test_bearer_auth(self, mgr):
        """Bearer credential sets Authorization header."""
        session = requests.Session()
        cred = Credential(type="bearer", token="tok_secret")
        descriptor = SessionDescriptor(credential_type="bearer")

        mgr._apply_session(session, cred, descriptor)

        assert session.headers.get("Authorization") == "Bearer tok_secret"

    def test_oauth_auth(self, mgr):
        """OAuth credential sets Authorization header (same as bearer)."""
        session = requests.Session()
        cred = Credential(type="oauth", token="oauth_tok")
        descriptor = SessionDescriptor(credential_type="oauth")

        mgr._apply_session(session, cred, descriptor)

        assert session.headers.get("Authorization") == "Bearer oauth_tok"

    def test_probe_headers_applied_for_cookie(self, mgr):
        """Probe headers are applied when descriptor has them."""
        session = requests.Session()
        cred = Credential(type="cookie", cookies={"sid": "x"})
        descriptor = SessionDescriptor(
            credential_type="cookie",
            probe=ProbeConfig(
                endpoint="https://api.example.com/me",
                headers={"origin": "https://example.com", "referer": "https://example.com/"},
            ),
        )

        mgr._apply_session(session, cred, descriptor)

        assert session.headers.get("origin") == "https://example.com"
        assert session.headers.get("referer") == "https://example.com/"

    def test_no_auth_for_unknown_type(self, mgr):
        """Credential with no cookies or token → no headers added."""
        session = requests.Session()
        cred = Credential(type="cookie", cookies=None)  # noqa
        descriptor = SessionDescriptor(credential_type="cookie")

        mgr._apply_session(session, cred, descriptor)

        assert session.headers.get("Authorization") is None
