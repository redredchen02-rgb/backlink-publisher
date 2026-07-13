"""Unit tests for the session credential management package.

Plan 2026-05-25-002 Unit 7 — covers Credential, DefaultCredentialProvider
(load/probe/refresh), and SessionManager.get_session().
"""
from __future__ import annotations

__tier__ = "integration"
import json
import os
from pathlib import Path
import sys
from unittest.mock import MagicMock, patch

import pytest
import requests

from backlink_publisher._util.errors import AuthExpiredError, DependencyError
from backlink_publisher.config import Config
from backlink_publisher.publishing._manifest_types import (
    ProbeConfig,
    RefreshConfig,
    SessionDescriptor,
)
from backlink_publisher.publishing.session import (
    Credential,
    DefaultCredentialProvider,
    SessionManager,
)

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    return tmp_path / ".config" / "backlink-publisher"


@pytest.fixture
def mock_config(config_dir: Path) -> MagicMock:
    cfg = MagicMock(spec=Config)
    cfg.config_dir = config_dir
    return cfg


@pytest.fixture
def velog_descriptor() -> SessionDescriptor:
    return SessionDescriptor(
        credential_type="cookie",
        config_path="<config_dir>/velog-cookies.json",
        probe=ProbeConfig(
            http_method="POST",
            endpoint="https://v2.velog.io/graphql",
            graphql_query="{ currentUser { id username } }",
            shape=("data", "currentUser", "id"),
            timeout_sec=10,
            headers={
                "accept": "*/*",
                "content-type": "application/json",
                "origin": "https://velog.io",
                "referer": "https://velog.io/",
            },
        ),
        refresh=RefreshConfig(method="cookie-implicit"),
    )


@pytest.fixture
def medium_descriptor() -> SessionDescriptor:
    return SessionDescriptor(
        credential_type="bearer",
        config_path="<config_dir>/medium-token.json",
        probe=ProbeConfig(
            http_method="GET",
            endpoint="https://api.medium.com/v1/me",
            shape=("data", "id"),
            timeout_sec=30,
        ),
        refresh=RefreshConfig(
            method="oauth-refresh-token",
            token_endpoint="https://api.medium.com/v1/tokens",
            expiration_window_sec=300,
        ),
    )


@pytest.fixture
def blogger_descriptor() -> SessionDescriptor:
    return SessionDescriptor(
        credential_type="oauth",
        config_path="<config_dir>/blogger-token.json",
        probe=ProbeConfig(
            http_method="GET",
            endpoint="https://www.googleapis.com/oauth2/v1/tokeninfo",
            shape=("email",),
            timeout_sec=30,
        ),
        refresh=RefreshConfig(
            method="oauth-refresh-token",
            token_endpoint="https://oauth2.googleapis.com/token",
            expiration_window_sec=300,
        ),
    )


# ── Credential dataclass ──────────────────────────────────────────────────────


class TestCredential:
    def test_construction(self) -> None:
        c = Credential(type="cookie", cookies={"a": "1"})
        assert c.type == "cookie"
        assert c.cookies == {"a": "1"}
        assert c.token is None
        assert c.oauth_data is None
        assert c.expires_at is None
        assert c.refresh_token is None

    def test_bearer_construction(self) -> None:
        c = Credential(type="bearer", token="tok123")
        assert c.type == "bearer"
        assert c.token == "tok123"
        assert c.cookies is None

    def test_frozen(self) -> None:
        c = Credential(type="cookie", cookies={"a": "1"})
        with pytest.raises(AttributeError):
            c.type = "bearer"  # type: ignore[misc]


# ── DefaultCredentialProvider.load() ──────────────────────────────────────────


class TestProviderLoadVelog:
    def _write_cookie_file(self, path: Path, data: dict | None = None) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        if data is None:
            data = {
                "cookies": [{"name": "access_token", "value": "tok_abc"}],
                "origins": [
                    {
                        "origin": "https://velog.io",
                        "localStorage": [
                            {"name": "account", "value": '{"access_token":"tok_local","refresh_token":"rt_1"}'}
                        ],
                    }
                ],
            }
        path.write_text(json.dumps(data))
        os.chmod(path, 0o600)
        return path

    def test_load_velog_cookies(self, mock_config: MagicMock, velog_descriptor: SessionDescriptor) -> None:
        config_dir = mock_config.config_dir
        path = config_dir / "velog-cookies.json"
        self._write_cookie_file(path)

        cred = DefaultCredentialProvider().load("velog", mock_config, velog_descriptor)
        assert cred.type == "cookie"
        assert cred.cookies is not None
        assert cred.cookies.get("access_token") == "tok_abc"

    def test_load_legacy_filename(self, mock_config: MagicMock, velog_descriptor: SessionDescriptor) -> None:
        config_dir = mock_config.config_dir
        legacy = config_dir / "velog-storage-state.json"
        self._write_cookie_file(legacy)

        cred = DefaultCredentialProvider().load("velog", mock_config, velog_descriptor)
        assert cred.type == "cookie"
        assert cred.cookies is not None

    def test_load_missing_file(self, mock_config: MagicMock, velog_descriptor: SessionDescriptor) -> None:
        with pytest.raises(DependencyError, match="velog cookies not found"):
            DefaultCredentialProvider().load("velog", mock_config, velog_descriptor)

    @pytest.mark.skipif(
        sys.platform == "win32",
        reason="permission enforcement is a no-op on Windows by design — see _util/permissions.py",
    )
    def test_load_bad_permissions(self, mock_config: MagicMock, velog_descriptor: SessionDescriptor) -> None:
        path = mock_config.config_dir / "velog-cookies.json"
        self._write_cookie_file(path)
        os.chmod(path, 0o644)  # wrong permissions

        with pytest.raises(DependencyError, match="must be 0600"):
            DefaultCredentialProvider().load("velog", mock_config, velog_descriptor)

    def test_load_no_auth_data(self, mock_config: MagicMock, velog_descriptor: SessionDescriptor) -> None:
        path = mock_config.config_dir / "velog-cookies.json"
        self._write_cookie_file(path, {"cookies": [], "origins": []})
        with pytest.raises(DependencyError, match="no usable auth data"):
            DefaultCredentialProvider().load("velog", mock_config, velog_descriptor)

    def test_load_no_token_key(self, mock_config: MagicMock, velog_descriptor: SessionDescriptor) -> None:
        """Cookie file with only non-token cookies should raise AuthExpiredError."""
        path = mock_config.config_dir / "velog-cookies.json"
        self._write_cookie_file(path, {
            "cookies": [{"name": "some_other", "value": "x"}],
        })
        with pytest.raises(AuthExpiredError, match="no access_token"):
            DefaultCredentialProvider().load("velog", mock_config, velog_descriptor)


class TestProviderLoadMedium:
    def _write_token_file(self, path: Path, data: dict) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data))
        return path

    @patch("backlink_publisher.publishing.session.provider.load_medium_token")
    def test_load_oauth_token(
        self, mock_load: MagicMock, mock_config: MagicMock, medium_descriptor: SessionDescriptor
    ) -> None:
        mock_load.return_value = {"access_token": "oauth_tok", "refresh_token": "rt_1", "expires_at": 9999999999.0}

        cred = DefaultCredentialProvider().load("medium", mock_config, medium_descriptor)
        assert cred.type == "bearer"
        assert cred.token == "oauth_tok"
        assert cred.refresh_token == "rt_1"
        assert cred.oauth_data is not None

    @patch("backlink_publisher.publishing.session.provider.load_medium_token")
    @patch("backlink_publisher.publishing.session.provider.load_medium_integration_token")
    def test_load_integration_token_fallback(
        self, mock_it: MagicMock, mock_oauth: MagicMock, mock_config: MagicMock, medium_descriptor: SessionDescriptor
    ) -> None:
        mock_oauth.return_value = None
        mock_it.return_value = {"integration_token": "it_tok"}

        cred = DefaultCredentialProvider().load("medium", mock_config, medium_descriptor)
        assert cred.type == "bearer"
        assert cred.token == "it_tok"
        assert cred.oauth_data is None

    @patch("backlink_publisher.publishing.session.provider.load_medium_token")
    @patch("backlink_publisher.publishing.session.provider.load_medium_integration_token")
    def test_load_missing_token(
        self, mock_it: MagicMock, mock_oauth: MagicMock, mock_config: MagicMock, medium_descriptor: SessionDescriptor
    ) -> None:
        mock_oauth.return_value = None
        mock_it.return_value = None
        # MagicMock attributes are truthy — ensure the TOML fallback is empty
        mock_config.medium_integration_token = ""

        with pytest.raises(DependencyError, match="not configured"):
            DefaultCredentialProvider().load("medium", mock_config, medium_descriptor)


class TestProviderLoadBlogger:
    def _write_token_file(self, path: Path, data: dict) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data))
        return path

    @patch("backlink_publisher.publishing.session.provider.load_blogger_token")
    def test_load(
        self, mock_load: MagicMock, mock_config: MagicMock, blogger_descriptor: SessionDescriptor
    ) -> None:
        mock_load.return_value = {"token": "tok", "refresh_token": "rt", "expires_at": 9999999999.0}

        cred = DefaultCredentialProvider().load("blogger", mock_config, blogger_descriptor)
        assert cred.type == "oauth"
        assert cred.token == "tok"
        assert cred.refresh_token == "rt"
        assert cred.oauth_data == mock_load.return_value

    @patch("backlink_publisher.publishing.session.provider.load_blogger_token")
    def test_load_no_token(
        self, mock_load: MagicMock, mock_config: MagicMock, blogger_descriptor: SessionDescriptor
    ) -> None:
        mock_load.return_value = None
        with pytest.raises(DependencyError, match="not configured"):
            DefaultCredentialProvider().load("blogger", mock_config, blogger_descriptor)

    def test_load_unknown_channel(self, mock_config: MagicMock) -> None:
        with pytest.raises(DependencyError, match="No credential loader"):
            DefaultCredentialProvider().load("nonexistent", mock_config, MagicMock())


# ── DefaultCredentialProvider.probe() ─────────────────────────────────────────


class TestProviderProbe:
    @patch.object(requests.Session, "get")
    def test_get_success_shape(self, mock_get: MagicMock) -> None:
        mock_get.return_value = MagicMock(ok=True, status_code=200)
        mock_get.return_value.json.return_value = {"data": {"id": "1234"}}

        session = requests.Session()
        session.headers.update({"Authorization": "Bearer tok"})

        descriptor = SessionDescriptor(
            credential_type="bearer",
            config_path="",
            probe=ProbeConfig(
                endpoint="https://api.example.com/v1/me",
                shape=("data", "id"),
                timeout_sec=10,
            ),
        )

        alive, reason = DefaultCredentialProvider().probe(session, descriptor)
        assert alive is True
        assert reason == "1234"

    @patch.object(requests.Session, "post")
    def test_post_graphql_success(self, mock_post: MagicMock) -> None:
        mock_post.return_value = MagicMock(ok=True, status_code=200)
        mock_post.return_value.json.return_value = {"data": {"currentUser": {"id": "u1"}}}

        session = requests.Session()
        descriptor = SessionDescriptor(
            credential_type="cookie",
            config_path="",
            probe=ProbeConfig(
                http_method="POST",
                endpoint="https://v2.velog.io/graphql",
                graphql_query="{ currentUser { id } }",
                shape=("data", "currentUser", "id"),
                timeout_sec=10,
                headers={"content-type": "application/json"},
            ),
        )

        alive, reason = DefaultCredentialProvider().probe(session, descriptor)
        assert alive is True
        assert reason == "u1"

    @patch.object(requests.Session, "get")
    def test_no_probe_configured(self, mock_get: MagicMock) -> None:
        session = requests.Session()
        descriptor = SessionDescriptor(credential_type="bearer")

        alive, reason = DefaultCredentialProvider().probe(session, descriptor)
        assert alive is True
        assert reason == "no_probe_configured"

    @patch.object(requests.Session, "get")
    def test_http_error(self, mock_get: MagicMock) -> None:
        mock_get.return_value = MagicMock(ok=False, status_code=401)
        session = requests.Session()
        descriptor = SessionDescriptor(
            credential_type="bearer",
            config_path="",
            probe=ProbeConfig(endpoint="https://api.example.com/v1/me"),
        )

        alive, reason = DefaultCredentialProvider().probe(session, descriptor)
        assert alive is False
        assert "probe_http_401" in reason

    @patch.object(requests.Session, "get")
    def test_invalid_json(self, mock_get: MagicMock) -> None:
        mock_get.return_value = MagicMock(ok=True, status_code=200)
        mock_get.return_value.json.side_effect = ValueError("bad json")
        session = requests.Session()
        descriptor = SessionDescriptor(
            credential_type="bearer",
            config_path="",
            probe=ProbeConfig(
                endpoint="https://api.example.com/v1/me",
                shape=("data",),
            ),
        )

        alive, reason = DefaultCredentialProvider().probe(session, descriptor)
        assert alive is False
        assert reason == "probe_invalid_json"

    @patch.object(requests.Session, "get")
    def test_missing_shape_key(self, mock_get: MagicMock) -> None:
        mock_get.return_value = MagicMock(ok=True, status_code=200)
        mock_get.return_value.json.return_value = {}
        session = requests.Session()
        descriptor = SessionDescriptor(
            credential_type="bearer",
            config_path="",
            probe=ProbeConfig(
                endpoint="https://api.example.com/v1/me",
                shape=("data", "id"),
            ),
        )

        alive, reason = DefaultCredentialProvider().probe(session, descriptor)
        assert alive is False
        assert reason == "probe_null_data"

    @patch.object(requests.Session, "get")
    def test_unreachable(self, mock_get: MagicMock) -> None:
        mock_get.side_effect = requests.ConnectionError("no route to host")
        session = requests.Session()
        descriptor = SessionDescriptor(
            credential_type="bearer",
            config_path="",
            probe=ProbeConfig(endpoint="https://api.example.com/v1/me"),
        )

        alive, reason = DefaultCredentialProvider().probe(session, descriptor)
        assert alive is False
        assert "probe_unreachable" in reason


# ── DefaultCredentialProvider.refresh() ───────────────────────────────────────


class TestProviderRefresh:
    def test_no_refresh_config(self, mock_config: MagicMock) -> None:
        cred = Credential(type="bearer", token="tok")
        descriptor = SessionDescriptor(credential_type="bearer")
        result = DefaultCredentialProvider().refresh(cred, descriptor, mock_config)
        assert result is None

    def test_cookie_implicit(self, mock_config: MagicMock) -> None:
        cred = Credential(type="cookie", cookies={"a": "1"})
        descriptor = SessionDescriptor(
            credential_type="cookie",
            config_path="",
            refresh=RefreshConfig(method="cookie-implicit"),
        )
        result = DefaultCredentialProvider().refresh(cred, descriptor, mock_config)
        assert result is None

    @patch("backlink_publisher.publishing.session.provider.http_client.post")
    def test_oauth_refresh_success(self, mock_post: MagicMock, mock_config: MagicMock) -> None:
        mock_post.return_value = MagicMock(ok=True, status_code=200)
        mock_post.return_value.json.return_value = {"access_token": "new_tok"}

        cred = Credential(
            type="oauth",
            oauth_data={"refresh_token": "rt_1", "client_id": "cid", "client_secret": "cs"},
            token="old_tok",
            refresh_token="rt_1",
        )
        descriptor = SessionDescriptor(
            credential_type="oauth",
            config_path="<config_dir>/blogger-token.json",
            refresh=RefreshConfig(
                method="oauth-refresh-token",
                token_endpoint="https://oauth2.googleapis.com/token",
                expiration_window_sec=300,
            ),
        )

        result = DefaultCredentialProvider().refresh(cred, descriptor, mock_config)
        assert result is not None
        assert result.token == "new_tok"

    @patch("backlink_publisher.publishing.session.provider.http_client.post")
    def test_oauth_refresh_failure(self, mock_post: MagicMock, mock_config: MagicMock) -> None:
        mock_post.return_value = MagicMock(ok=False, status_code=400)
        mock_post.return_value.text = "invalid_grant"

        cred = Credential(
            type="oauth",
            oauth_data={"refresh_token": "rt_dead"},
            token="old_tok",
            refresh_token="rt_dead",
        )
        descriptor = SessionDescriptor(
            credential_type="oauth",
            config_path="<config_dir>/blogger-token.json",
            refresh=RefreshConfig(
                method="oauth-refresh-token",
                token_endpoint="https://oauth2.googleapis.com/token",
                expiration_window_sec=300,
            ),
        )

        with pytest.raises(AuthExpiredError, match="OAuth refresh failed"):
            DefaultCredentialProvider().refresh(cred, descriptor, mock_config, channel="blogger")

    def test_unknown_method(self, mock_config: MagicMock) -> None:
        cred = Credential(type="bearer", token="tok")
        descriptor = SessionDescriptor(
            credential_type="bearer",
            config_path="",
            refresh=RefreshConfig(method="unsupported"),
        )
        with pytest.raises(Exception, match="Unknown refresh method"):
            DefaultCredentialProvider().refresh(cred, descriptor, mock_config)


# ── SessionManager.get_session() ──────────────────────────────────────────────


@pytest.fixture
def velog_cookie_file(mock_config: MagicMock) -> Path:
    path = mock_config.config_dir / "velog-cookies.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "cookies": [{"name": "access_token", "value": "tok_abc"}],
        "origins": [],
    }
    path.write_text(json.dumps(data))
    os.chmod(path, 0o600)
    return path


class TestSessionManager:
    @patch("backlink_publisher.publishing.session.session_manager.get_descriptor")
    def test_get_session_happy_path(self, mock_get_desc: MagicMock, mock_config: MagicMock, velog_cookie_file: Path, velog_descriptor: SessionDescriptor) -> None:
        """Full lifecycle: load → apply → probe.success → return session."""
        mock_get_desc.return_value = velog_descriptor
        provider = DefaultCredentialProvider()
        mgr = SessionManager(provider)

        # The probe hits the real velog.io if unmocked, but the conftest
        # blocks sockets.  Patch probe to pass.
        with patch.object(provider, "probe", return_value=(True, "u1")):
            session = mgr.get_session("velog", mock_config)

        assert isinstance(session, requests.Session)
        assert session.cookies.get("access_token") == "tok_abc"

    def test_no_descriptor(self, mock_config: MagicMock) -> None:
        """Unknown channel → DependencyError."""
        provider = DefaultCredentialProvider()
        mgr = SessionManager(provider)

        with pytest.raises(DependencyError, match="No SessionDescriptor"):
            mgr.get_session("nonexistent", mock_config)

    @patch("backlink_publisher.publishing.session.session_manager.get_descriptor")
    def test_probe_failure(self, mock_get_desc: MagicMock, mock_config: MagicMock, velog_cookie_file: Path, velog_descriptor: SessionDescriptor) -> None:
        """Probe returns False → AuthExpiredError."""
        mock_get_desc.return_value = velog_descriptor
        provider = DefaultCredentialProvider()
        mgr = SessionManager(provider)

        with patch.object(provider, "probe", return_value=(False, "probe_http_401")):
            with pytest.raises(AuthExpiredError, match="Session expired"):
                mgr.get_session("velog", mock_config)

    @patch("backlink_publisher.publishing.session.session_manager.get_descriptor")
    def test_near_expiry_triggers_refresh(self, mock_get_desc: MagicMock, mock_config: MagicMock, velog_cookie_file: Path, velog_descriptor: SessionDescriptor) -> None:
        """Credential with expires_at in the past should trigger refresh before probe."""
        mock_get_desc.return_value = velog_descriptor
        provider = DefaultCredentialProvider()
        mgr = SessionManager(provider)

        # Patch load to return a near-expiry credential
        expired_cred = Credential(
            type="cookie",
            cookies={"access_token": "old_tok"},
            expires_at=100.0,  # long past
        )

        with patch.object(provider, "load", return_value=expired_cred):
            with patch.object(provider, "refresh", return_value=None) as mock_refresh:
                with patch.object(provider, "probe", return_value=(True, "u1")):
                    session = mgr.get_session("velog", mock_config)

        mock_refresh.assert_called_once()
        assert isinstance(session, requests.Session)
