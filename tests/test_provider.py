"""Credential provider tests — per-channel loader functions + _LOADERS dispatch.

Tests the ``_load_*`` functions in ``session/provider.py``: file-based
cookie loading (velog, substack), token loading (medium, blogger), and
the ``_LOADERS`` channel→loader mapping.
"""
from __future__ import annotations

__tier__ = "unit"
import json
import os
from unittest.mock import MagicMock, patch

import pytest

from backlink_publisher._util.errors import AuthExpiredError, DependencyError
from backlink_publisher.publishing._manifest_types import SessionDescriptor
from backlink_publisher.publishing.session.provider import (
    _load_blogger_oauth,
    _load_medium_token,
    _load_substack_cookies,
    _load_velog_cookies,
    _LOADERS,
    DefaultCredentialProvider,
)

# ── Helpers ────────────────────────────────────────────────────────────────────

@pytest.fixture
def provider():
    return DefaultCredentialProvider()


@pytest.fixture
def velog_descriptor():
    return SessionDescriptor(credential_type="cookie", config_path="<config_dir>/velog-cookies.json")


@pytest.fixture
def substack_descriptor():
    return SessionDescriptor(credential_type="cookie", config_path="<config_dir>/substack-credentials.json")


# ── _load_velog_cookies ─────────────────────────────────────────────────────────

class TestVelogCookies:
    def test_happy_path(self, provider, tmp_path, velog_descriptor):
        """Valid cookies JSON with cookies + localStorage origins → Credential."""
        cfg = MagicMock()
        cfg.config_dir = tmp_path
        cred_file = tmp_path / "velog-cookies.json"
        data = {
            "cookies": [{"name": "sid", "value": "abc"}, {"name": "velog_id", "value": "123"}],
            "origins": [{
                "origin": "https://velog.io",
                "localStorage": [
                    {"name": "access_token", "value": "tok_xxx"},
                ],
            }],
        }
        cred_file.write_text(json.dumps(data))
        os.chmod(cred_file, 0o600)

        cred = _load_velog_cookies(provider, cfg, velog_descriptor)
        assert cred.type == "cookie"
        assert cred.cookies is not None
        assert cred.cookies["sid"] == "abc"
        assert cred.cookies["access_token"] == "tok_xxx"

    def test_legacy_filename(self, provider, tmp_path, velog_descriptor):
        """Fall back to velog-storage-state.json when velog-cookies.json missing."""
        cfg = MagicMock()
        cfg.config_dir = tmp_path
        legacy = tmp_path / "velog-storage-state.json"
        data = {
            "cookies": [{"name": "sid", "value": "x"}],
            "origins": [{
                "origin": "https://velog.io",
                "localStorage": [{"name": "access_token", "value": "tok_x"}],
            }],
        }
        legacy.write_text(json.dumps(data))
        os.chmod(legacy, 0o600)

        cred = _load_velog_cookies(provider, cfg, velog_descriptor)
        assert cred.type == "cookie"
        assert cred.cookies is not None
        assert cred.cookies["sid"] == "x"
        assert cred.cookies["access_token"] == "tok_x"

    def test_missing_file(self, provider, tmp_path, velog_descriptor):
        """File not found → DependencyError."""
        cfg = MagicMock()
        cfg.config_dir = tmp_path

        with pytest.raises(DependencyError) as exc:
            _load_velog_cookies(provider, cfg, velog_descriptor)
        assert "not found" in str(exc.value)

    def test_corrupt_json(self, provider, tmp_path, velog_descriptor):
        """Corrupt JSON → DependencyError."""
        cfg = MagicMock()
        cfg.config_dir = tmp_path
        cred_file = tmp_path / "velog-cookies.json"
        cred_file.write_text("not { json")
        os.chmod(cred_file, 0o600)

        with pytest.raises(DependencyError) as exc:
            _load_velog_cookies(provider, cfg, velog_descriptor)
        assert "velog cookies" in str(exc.value).lower()

    def test_wrong_chmod(self, provider, tmp_path, velog_descriptor):
        """Non-0600 permissions → DependencyError."""
        cfg = MagicMock()
        cfg.config_dir = tmp_path
        cred_file = tmp_path / "velog-cookies.json"
        cred_file.write_text("{}")
        os.chmod(cred_file, 0o644)

        with pytest.raises(DependencyError) as exc:
            _load_velog_cookies(provider, cfg, velog_descriptor)
        assert "0600" in str(exc.value)

    def test_no_usable_auth_data(self, provider, tmp_path, velog_descriptor):
        """JSON with no cookies key and no origins → DependencyError."""
        cfg = MagicMock()
        cfg.config_dir = tmp_path
        cred_file = tmp_path / "velog-cookies.json"
        cred_file.write_text(json.dumps({"foo": "bar"}))
        os.chmod(cred_file, 0o600)

        with pytest.raises(DependencyError) as exc:
            _load_velog_cookies(provider, cfg, velog_descriptor)
        assert "no usable auth data" in str(exc.value)

    def test_no_token_in_origin(self, provider, tmp_path, velog_descriptor):
        """Cookies present but no access_token/refresh_token in origin → AuthExpiredError."""
        cfg = MagicMock()
        cfg.config_dir = tmp_path
        cred_file = tmp_path / "velog-cookies.json"
        data = {
            "cookies": [{"name": "sid", "value": "abc"}],
            "origins": [{
                "origin": "https://velog.io",
                "localStorage": [{"name": "theme", "value": "dark"}],
            }],
        }
        cred_file.write_text(json.dumps(data))
        os.chmod(cred_file, 0o600)

        with pytest.raises(AuthExpiredError) as exc:
            _load_velog_cookies(provider, cfg, velog_descriptor)
        assert "no access_token or refresh_token" in str(exc.value).lower()

    def test_localstorage_origin_provides_token(self, provider, tmp_path, velog_descriptor):
        """Origin localStorage with account JSON containing access_token → Credential."""
        cfg = MagicMock()
        cfg.config_dir = tmp_path
        cred_file = tmp_path / "velog-cookies.json"
        data = {
            "origins": [{
                "origin": "https://velog.io",
                "localStorage": [
                    {"name": "account", "value": json.dumps({"access_token": "tok_from_account"})},
                ],
            }],
        }
        cred_file.write_text(json.dumps(data))
        os.chmod(cred_file, 0o600)

        cred = _load_velog_cookies(provider, cfg, velog_descriptor)
        assert cred.cookies is not None
        assert cred.cookies["access_token"] == "tok_from_account"

    def test_empty_cookie_list(self, provider, tmp_path, velog_descriptor):
        """Empty cookies list + no origins → DependencyError."""
        cfg = MagicMock()
        cfg.config_dir = tmp_path
        cred_file = tmp_path / "velog-cookies.json"
        cred_file.write_text(json.dumps({"cookies": []}))
        os.chmod(cred_file, 0o600)

        with pytest.raises(DependencyError) as exc:
            _load_velog_cookies(provider, cfg, velog_descriptor)
        assert "no usable auth data" in str(exc.value)


# ── _load_substack_cookies ──────────────────────────────────────────────────────

class TestSubstackCookies:
    def test_happy_path(self, provider, tmp_path, substack_descriptor):
        """Valid cookies JSON → Credential with cookies dict."""
        cfg = MagicMock()
        cfg.config_dir = tmp_path
        cred_file = tmp_path / "substack-credentials.json"
        data = {"cookies": [{"name": "sid", "value": "abc"}, {"name": "xsrf", "value": "def"}]}
        cred_file.write_text(json.dumps(data))
        os.chmod(cred_file, 0o600)

        cred = _load_substack_cookies(provider, cfg, substack_descriptor)
        assert cred.type == "cookie"
        assert cred.cookies == {"sid": "abc", "xsrf": "def"}

    def test_missing_file(self, provider, tmp_path, substack_descriptor):
        """File not found → DependencyError."""
        cfg = MagicMock()
        cfg.config_dir = tmp_path

        with pytest.raises(DependencyError) as exc:
            _load_substack_cookies(provider, cfg, substack_descriptor)
        assert "not found" in str(exc.value)

    def test_corrupt_json_omits_content(self, provider, tmp_path, substack_descriptor):
        """Corrupt JSON must NOT leak file contents."""
        cfg = MagicMock()
        cfg.config_dir = tmp_path
        cred_file = tmp_path / "substack-credentials.json"
        cred_file.write_text("{ broken sid=secretvalue ")
        os.chmod(cred_file, 0o600)

        with pytest.raises(DependencyError) as exc:
            _load_substack_cookies(provider, cfg, substack_descriptor)
        msg = str(exc.value)
        assert "secretvalue" not in msg
        assert "Expecting" not in msg

    def test_wrong_chmod(self, provider, tmp_path, substack_descriptor):
        """Non-0600 permissions → DependencyError."""
        cfg = MagicMock()
        cfg.config_dir = tmp_path
        cred_file = tmp_path / "substack-credentials.json"
        cred_file.write_text(json.dumps({"cookies": [{"name": "sid", "value": "x"}]}))
        os.chmod(cred_file, 0o644)

        with pytest.raises(DependencyError) as exc:
            _load_substack_cookies(provider, cfg, substack_descriptor)
        assert "0600" in str(exc.value)

    def test_empty_cookies(self, provider, tmp_path, substack_descriptor):
        """Empty cookies array → DependencyError."""
        cfg = MagicMock()
        cfg.config_dir = tmp_path
        cred_file = tmp_path / "substack-credentials.json"
        cred_file.write_text(json.dumps({"cookies": []}))
        os.chmod(cred_file, 0o600)

        with pytest.raises(DependencyError) as exc:
            _load_substack_cookies(provider, cfg, substack_descriptor)
        assert "no usable cookies" in str(exc.value)

    def test_non_list_cookies_value(self, provider, tmp_path, substack_descriptor):
        """cookies value that is not a list → DependencyError."""
        cfg = MagicMock()
        cfg.config_dir = tmp_path
        cred_file = tmp_path / "substack-credentials.json"
        cred_file.write_text(json.dumps({"cookies": "not-a-list"}))
        os.chmod(cred_file, 0o600)

        with pytest.raises(DependencyError) as exc:
            _load_substack_cookies(provider, cfg, substack_descriptor)
        assert "cookies" in str(exc.value)


# ── _load_medium_token ─────────────────────────────────────────────────────────

class TestMediumToken:
    def test_oauth_token_preferred(self, provider, tmp_path):
        """OAuth access_token takes precedence over integration token."""
        desc = SessionDescriptor(credential_type="bearer", config_path="<config_dir>/medium-token.json")
        cfg = MagicMock()
        cfg.config_dir = tmp_path
        cfg.medium_integration_token = None

        with patch(
            "backlink_publisher.publishing.session.provider.load_medium_token",
            return_value={"access_token": "oauth_tok", "refresh_token": "refresh_x"},
        ), patch(
            "backlink_publisher.publishing.session.provider.load_medium_integration_token",
            return_value=None,
        ):
            cred = _load_medium_token(provider, cfg, desc)

        assert cred.type == "bearer"
        assert cred.token == "oauth_tok"

    def test_integration_token_fallback(self, provider, tmp_path):
        """When OAuth is absent, falls back to Integration Token."""
        desc = SessionDescriptor(credential_type="bearer", config_path="<config_dir>/medium-token.json")
        cfg = MagicMock()
        cfg.config_dir = tmp_path
        cfg.medium_integration_token = None

        with patch(
            "backlink_publisher.publishing.session.provider.load_medium_token",
            return_value=None,
        ), patch(
            "backlink_publisher.publishing.session.provider.load_medium_integration_token",
            return_value={"integration_token": "it_xyz"},
        ):
            cred = _load_medium_token(provider, cfg, desc)

        assert cred.type == "bearer"
        assert cred.token == "it_xyz"

    def test_no_token_raises(self, provider, tmp_path):
        """No token at all → DependencyError."""
        desc = SessionDescriptor(credential_type="bearer", config_path="<config_dir>/medium-token.json")
        cfg = MagicMock()
        cfg.config_dir = tmp_path
        cfg.medium_integration_token = None

        with patch(
            "backlink_publisher.publishing.session.provider.load_medium_token",
            return_value=None,
        ), patch(
            "backlink_publisher.publishing.session.provider.load_medium_integration_token",
            return_value=None,
        ):
            with pytest.raises(DependencyError) as exc:
                _load_medium_token(provider, cfg, desc)
        assert "not configured" in str(exc.value)


# ── _load_blogger_oauth ───────────────────────────────────────────────────────

class TestBloggerOAuth:
    def test_happy_path(self, provider, tmp_path):
        """Valid token JSON → Credential with oauth data."""
        desc = SessionDescriptor(credential_type="oauth", config_path="<config_dir>/blogger-token.json")
        cfg = MagicMock()
        cfg.config_dir = tmp_path
        token_data = {"token": "tok_abc", "refresh_token": "rtok_x", "expires_at": 9999999999.0}

        with patch(
            "backlink_publisher.publishing.session.provider.load_blogger_token",
            return_value=token_data,
        ):
            cred = _load_blogger_oauth(provider, cfg, desc)

        assert cred.type == "oauth"
        assert cred.token == "tok_abc"
        assert cred.refresh_token == "rtok_x"
        assert cred.expires_at == 9999999999.0

    def test_no_token_raises(self, provider, tmp_path):
        """No token data → DependencyError."""
        desc = SessionDescriptor(credential_type="oauth", config_path="<config_dir>/blogger-token.json")
        cfg = MagicMock()
        cfg.config_dir = tmp_path

        with patch(
            "backlink_publisher.publishing.session.provider.load_blogger_token",
            return_value=None,
        ):
            with pytest.raises(DependencyError) as exc:
                _load_blogger_oauth(provider, cfg, desc)
        assert "not configured" in str(exc.value)


# ── _LOADERS dispatch ──────────────────────────────────────────────────────────

class TestLoadersDispatch:
    def test_velog_loader_registered(self):
        """_LOADERS['velog'] maps to _load_velog_cookies."""
        assert _LOADERS.get("velog") is _load_velog_cookies

    def test_substack_loader_registered(self):
        """_LOADERS['substack'] maps to _load_substack_cookies."""
        assert _LOADERS.get("substack") is _load_substack_cookies

    def test_medium_loader_registered(self):
        """_LOADERS['medium'] maps to _load_medium_token."""
        assert _LOADERS.get("medium") is _load_medium_token

    def test_blogger_loader_registered(self):
        """_LOADERS['blogger'] maps to _load_blogger_oauth."""
        assert _LOADERS.get("blogger") is _load_blogger_oauth

    def test_unknown_channel_raises(self):
        """Calling DefaultCredentialProvider.load with unknown channel raises."""
        provider = DefaultCredentialProvider()
        cfg = MagicMock()
        desc = SessionDescriptor(credential_type="cookie")

        with pytest.raises(DependencyError) as exc:
            provider.load("_unknown_channel_", cfg, desc)
        assert "No credential loader registered" in str(exc.value)
