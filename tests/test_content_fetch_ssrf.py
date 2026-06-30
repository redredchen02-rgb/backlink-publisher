"""SSRF defence tests for content/fetch (extracted from test_content_fetch.py, P13 A2).

Exercises _check_url_for_ssrf + _SSRFSafeRedirectHandler with real IP-routing
logic (no HTTP fetches). Uses ``pytest.mark.real_ssrf_check`` so it can be
run independently: ``pytest -m real_ssrf_check tests/test_content_fetch_ssrf.py``.
"""

from __future__ import annotations

from unittest.mock import patch
from urllib.error import URLError as _URLError
from urllib.request import Request

import pytest

from backlink_publisher.content.fetch import (
    verify_url_has_content,
)


class TestSSRFDefense:
    """Verify _check_url_for_ssrf + _SSRFSafeRedirectHandler reject
    requests targeting RFC1918 / loopback / link-local / cloud-metadata
    / CGNAT / IPv6-tunnel destinations, plus per-redirect-hop
    re-checks and HTTPS to HTTP downgrade refusal."""

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
        from backlink_publisher.content.fetch import _check_url_for_ssrf
        reason = _check_url_for_ssrf(f"http://{blocked_ip}/")
        assert reason is not None
        assert reason.startswith("blocked_ip:"), reason

    @pytest.mark.parametrize("safe_ip", [
        "8.8.8.8", "1.1.1.1", "151.101.1.140",
    ])
    def test_literal_public_ip_passes(self, safe_ip):
        from backlink_publisher.content.fetch import _check_url_for_ssrf
        assert _check_url_for_ssrf(f"http://{safe_ip}/") is None

    def test_hostname_resolving_to_blocked_ip_rejected(self, monkeypatch):
        from backlink_publisher.content.fetch import _check_url_for_ssrf
        def _fake_getaddrinfo(host, *args, **kwargs):
            return [(2, 1, 6, "", ("169.254.169.254", 0))]
        monkeypatch.setattr(
            "backlink_publisher.content.fetch.socket.getaddrinfo", _fake_getaddrinfo)
        assert _check_url_for_ssrf("https://evil.example.com/").startswith("blocked_ip:")

    def test_redirect_handler_blocks_redirect_to_metadata_ip(self):
        from backlink_publisher._util.net_safety import _SSRFSafeRedirectHandler
        handler = _SSRFSafeRedirectHandler()
        req = Request("https://good.example.com/")
        with pytest.raises(_URLError) as excinfo:
            handler.redirect_request(
                req, None, 302, "Found", {}, "https://169.254.169.254/")
        assert "ssrf_redirect" in str(excinfo.value)

    def test_redirect_handler_blocks_https_to_http_downgrade(self):
        from backlink_publisher._util.net_safety import _SSRFSafeRedirectHandler
        handler = _SSRFSafeRedirectHandler()
        req = Request("https://safe.example.com/")
        with pytest.raises(_URLError) as excinfo:
            handler.redirect_request(
                req, None, 302, "Found", {}, "http://safe.example.com/")
        assert "ssrf_https_downgrade" in str(excinfo.value)

    def test_verify_url_blocked_ssrf_returns_ssrf_blocked(self, monkeypatch):
        call_count = {"n": 0}
        def _track(*args, **kwargs):
            call_count["n"] += 1
            raise AssertionError("opener must not be reached")
        monkeypatch.setattr(
            "backlink_publisher.content.fetch._SSRF_OPENER.open", _track)
        ok, reason, _ = verify_url_has_content("http://169.254.169.254/")
        assert ok is False and reason == "ssrf_blocked" and call_count["n"] == 0

    @pytest.mark.parametrize("bad", ["http://[invalid", "http://[::1"])
    def test_verify_url_malformed_ipv6_returns_invalid_without_network(self, bad, monkeypatch):
        def _track(*a, **k):
            raise AssertionError("opener must not be reached for malformed input")
        monkeypatch.setattr(
            "backlink_publisher.content.fetch._SSRF_OPENER.open", _track)
        ok, reason, _ = verify_url_has_content(bad)
        assert ok is False and reason == "invalid_url"
