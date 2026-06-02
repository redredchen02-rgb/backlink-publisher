"""Flask-free unit tests for webui_app.services.oauth_service (U5).

No Flask app context required.
"""
from __future__ import annotations

import os
import pytest

from webui_app.services.oauth_service import (
    build_blogger_client_config,
    is_loopback_uri,
    oauthlib_insecure_transport,
)

_OAUTH_ENV = "OAUTHLIB_INSECURE_TRANSPORT"


class TestIsLoopbackUri:
    @pytest.mark.parametrize("uri", [
        "http://localhost/cb",
        "http://127.0.0.1:8888/cb",
        "http://::1/cb",
        "http://LOCALHOST/cb",
    ])
    def test_loopback_uris_return_true(self, uri):
        assert is_loopback_uri(uri) is True

    @pytest.mark.parametrize("uri", [
        "http://example.com/cb",
        "http://10.0.0.5/cb",
        "",
        "not-a-uri",
    ])
    def test_non_loopback_uris_return_false(self, uri):
        assert is_loopback_uri(uri) is False


class TestOauthlibInsecureTransport:
    def test_sets_env_var_inside_block(self):
        os.environ.pop(_OAUTH_ENV, None)
        with oauthlib_insecure_transport("http://localhost/cb"):
            assert os.environ.get(_OAUTH_ENV) == "1"
        assert _OAUTH_ENV not in os.environ

    def test_restores_prior_value(self):
        os.environ[_OAUTH_ENV] = "0"
        with oauthlib_insecure_transport("http://127.0.0.1/cb"):
            assert os.environ.get(_OAUTH_ENV) == "1"
        assert os.environ[_OAUTH_ENV] == "0"
        del os.environ[_OAUTH_ENV]

    def test_restores_on_exception(self):
        os.environ.pop(_OAUTH_ENV, None)
        with pytest.raises(ValueError):
            with oauthlib_insecure_transport("http://localhost/cb"):
                raise ValueError("boom")
        assert _OAUTH_ENV not in os.environ

    def test_non_loopback_raises(self):
        with pytest.raises(RuntimeError, match="not loopback"):
            with oauthlib_insecure_transport("https://example.com/cb"):
                pass  # should not reach here

    def test_non_loopback_does_not_set_env(self):
        os.environ.pop(_OAUTH_ENV, None)
        try:
            with oauthlib_insecure_transport("https://example.com/cb"):
                pass
        except RuntimeError:
            pass
        assert _OAUTH_ENV not in os.environ


class TestBuildBloggerClientConfig:
    def test_structure(self):
        cfg = build_blogger_client_config(
            "my-id", "my-secret", "http://localhost:8888/cb"
        )
        installed = cfg["installed"]
        assert installed["client_id"] == "my-id"
        assert installed["client_secret"] == "my-secret"
        assert "http://localhost:8888/cb" in installed["redirect_uris"]
        assert "http://localhost" in installed["redirect_uris"]
        assert installed["auth_uri"] == "https://accounts.google.com/o/oauth2/auth"
        assert installed["token_uri"] == "https://oauth2.googleapis.com/token"

    def test_different_uris_produce_different_configs(self):
        cfg1 = build_blogger_client_config("id", "sec", "http://localhost:8888/cb")
        cfg2 = build_blogger_client_config("id", "sec", "http://localhost:9000/cb")
        assert cfg1 != cfg2
        assert "http://localhost:9000/cb" in cfg2["installed"]["redirect_uris"]
