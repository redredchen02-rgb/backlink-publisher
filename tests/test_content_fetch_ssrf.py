"""SSRF defence tests for ``content_fetch``.

Extracted from ``test_content_fetch.py`` (Plan 2026-06-23-005).

See ``test_content_fetch.py`` for module-level docstring context.
"""
from __future__ import annotations

__tier__ = "e2e"
from io import BytesIO
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError
from urllib.request import Request

import pytest

from backlink_publisher._util.net_safety import _SSRFSafeRedirectHandler
from backlink_publisher.content.fetch import (
    _check_url_for_ssrf,
    reset_cache,
    verify_url_has_content,
)

pytestmark = pytest.mark.real_content_fetch


@pytest.fixture(autouse=True)
def _clear_cache():
    reset_cache()
    yield
    reset_cache()


def _mock_response(status: int, body: bytes) -> MagicMock:
    """Build a urlopen() return value with .getcode() and .read()."""
    resp = MagicMock()
    resp.getcode.return_value = status
    resp.read.side_effect = lambda *args: body[: args[0]] if args else body
    resp.close = MagicMock()
    return resp


# ═════════════════════════════════════════════════════════════════════════════
# SSRF defence
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.real_ssrf_check
class TestSSRFDefense:
    """Verify _check_url_for_ssrf + _SSRFSafeRedirectHandler reject
    requests targeting RFC1918 / loopback / link-local / cloud-metadata
    /  CGNAT / IPv6-tunnel destinations, plus per-redirect-hop
    re-checks and HTTPS->HTTP downgrade refusal."""

    @pytest.mark.parametrize("blocked_ip", [
        "127.0.0.1",
        "127.0.0.53",
        "10.0.0.5",
        "10.255.255.1",
        "172.16.5.10",
        "172.31.0.1",
        "192.168.1.1",
        "169.254.169.254",
        "168.63.129.16",
        "100.64.1.2",
        "0.0.0.0",
    ])
    def test_literal_blocked_ip_in_url_rejected(self, blocked_ip):
        reason = _check_url_for_ssrf(f"http://{blocked_ip}/")
        assert reason is not None
        assert reason.startswith("blocked_ip:"), reason

    @pytest.mark.parametrize("safe_ip", [
        "8.8.8.8",
        "1.1.1.1",
        "151.101.1.140",
    ])
    def test_literal_public_ip_passes(self, safe_ip):
        assert _check_url_for_ssrf(f"http://{safe_ip}/") is None

    @pytest.mark.parametrize("ipv6", [
        "::1",
        "fe80::1234",
        "ff02::1",
    ])
    def test_ipv6_blocked_ranges_rejected(self, ipv6):
        reason = _check_url_for_ssrf(f"http://[{ipv6}]/")
        assert reason is not None
        assert reason.startswith("blocked_ip:")

    def test_hostname_resolving_to_blocked_ip_rejected(self, monkeypatch):

        def _fake_getaddrinfo(host, *args, **kwargs):
            return [(2, 1, 6, "", ("169.254.169.254", 0))]

        monkeypatch.setattr(
            "backlink_publisher.content.fetch.socket.getaddrinfo",
            _fake_getaddrinfo,
        )
        reason = _check_url_for_ssrf("https://evil.example.com/")
        assert reason is not None
        assert reason.startswith("blocked_ip:")

    def test_hostname_resolving_to_public_ip_passes(self, monkeypatch):

        def _fake_getaddrinfo(host, *args, **kwargs):
            return [(2, 1, 6, "", ("8.8.8.8", 0))]

        monkeypatch.setattr(
            "backlink_publisher.content.fetch.socket.getaddrinfo",
            _fake_getaddrinfo,
        )
        assert _check_url_for_ssrf("https://good.example.com/") is None

    def test_dns_failure_classified_as_network_error(self, monkeypatch):

        def _fake_getaddrinfo(host, *args, **kwargs):
            raise __import__("socket").gaierror("no such host")

        monkeypatch.setattr(
            "backlink_publisher.content.fetch.socket.getaddrinfo",
            _fake_getaddrinfo,
        )
        assert _check_url_for_ssrf("https://nx.example/") == "dns_failure"

    def test_verify_url_blocked_ssrf_returns_ssrf_blocked(self, monkeypatch):
        call_count = {"n": 0}

        def _track(*args, **kwargs):
            call_count["n"] += 1
            raise AssertionError("opener must not be reached")

        monkeypatch.setattr(
            "backlink_publisher.content.fetch._SSRF_OPENER.open", _track,
        )
        ok, reason, _ = verify_url_has_content("http://169.254.169.254/")
        assert ok is False
        assert reason == "ssrf_blocked"
        assert call_count["n"] == 0

    def test_verify_url_dns_failure_surfaces_network_error(self, monkeypatch):
        def _fake_getaddrinfo(host, *args, **kwargs):
            raise __import__("socket").gaierror("nope")

        monkeypatch.setattr(
            "backlink_publisher.content.fetch.socket.getaddrinfo",
            _fake_getaddrinfo,
        )
        ok, reason, _ = verify_url_has_content("https://nx.example/")
        assert ok is False
        assert reason == "network_error"

    def test_invalid_host_classified_as_invalid_url(self, monkeypatch):
        assert _check_url_for_ssrf("http:///path") == "invalid_host"

    def test_redirect_handler_blocks_redirect_to_metadata_ip(self):

        handler = _SSRFSafeRedirectHandler()
        req = Request("https://good.example.com/")
        with pytest.raises(URLError) as excinfo:
            handler.redirect_request(
                req, None, 302, "Found", {}, "https://169.254.169.254/",
            )
        assert "ssrf_redirect" in str(excinfo.value)

    def test_redirect_handler_blocks_https_to_http_downgrade(self):

        handler = _SSRFSafeRedirectHandler()
        req = Request("https://safe.example.com/")
        with pytest.raises(URLError) as excinfo:
            handler.redirect_request(
                req, None, 302, "Found", {}, "http://safe.example.com/",
            )
        assert "ssrf_https_downgrade" in str(excinfo.value)

    def test_redirect_handler_allows_redirect_to_public_ip(self, monkeypatch):

        def _fake_getaddrinfo(host, *args, **kwargs):
            return [(2, 1, 6, "", ("8.8.8.8", 0))]

        monkeypatch.setattr(
            "backlink_publisher._util.net_safety.socket.getaddrinfo",
            _fake_getaddrinfo,
        )
        handler = _SSRFSafeRedirectHandler()
        req = Request("https://from.example/")
        result = handler.redirect_request(
            req, None, 302, "Found", {"location": "https://to.example/"},
            "https://to.example/",
        )
        assert result is not None

    @pytest.mark.parametrize("bad", ["http://[invalid", "http://[::1", "http://["])
    def test_check_url_for_ssrf_malformed_returns_invalid_host_not_raises(self, bad, monkeypatch):

        def _boom(*a, **k):
            raise AssertionError("getaddrinfo must not be called for malformed input")

        monkeypatch.setattr(
            "backlink_publisher._util.net_safety.socket.getaddrinfo", _boom,
        )
        assert _check_url_for_ssrf(bad) == "invalid_host"

    @pytest.mark.parametrize("bad", ["http://[invalid", "http://[::1"])
    def test_verify_url_malformed_ipv6_returns_invalid_without_network(self, bad, monkeypatch):
        def _track(*a, **k):
            raise AssertionError("opener must not be reached for malformed input")

        monkeypatch.setattr(
            "backlink_publisher.content.fetch._SSRF_OPENER.open", _track,
        )
        ok, reason, _ = verify_url_has_content(bad)
        assert ok is False
        assert reason == "invalid_url"

    @pytest.mark.parametrize("bad", ["http://[invalid", "http://[::1", "http://["])
    def test_redirect_handler_malformed_location_blocks_not_raises(self, bad, monkeypatch):

        def _boom(*a, **k):
            raise AssertionError("getaddrinfo must not be called for malformed redirect")

        monkeypatch.setattr(
            "backlink_publisher._util.net_safety.socket.getaddrinfo", _boom,
        )
        handler = _SSRFSafeRedirectHandler()
        req = Request("https://from.example/")
        with pytest.raises(URLError):
            handler.redirect_request(req, None, 302, "Found", {}, bad)
