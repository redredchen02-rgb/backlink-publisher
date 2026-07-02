"""``allow_private`` relaxes the LAN guard but NOT the metadata guard.

Operator self-hosted blog endpoints and local AI gateways live on RFC1918 /
loopback addresses. ``allow_private=True`` lets callers reach those while the
cloud-metadata exfiltration guard (169.254/16, Azure wireserver) and the other
dangerous special ranges stay blocked. The default (False) is unchanged: strict
fail-closed SSRF defence.
"""
from __future__ import annotations

__tier__ = "unit"

import pytest

from backlink_publisher._util.net_safety import _check_url_for_ssrf, _is_blocked_ip

# (ip, blocked_by_default, blocked_under_allow_private)
_CASES = [
    # RFC1918 + loopback: blocked by default, permitted under allow_private.
    ("10.1.2.3", True, False),
    ("172.16.5.5", True, False),
    ("192.168.1.10", True, False),
    ("127.0.0.1", True, False),
    ("::1", True, False),
    # Cloud-metadata / dangerous ranges: blocked in BOTH modes.
    ("169.254.169.254", True, True),   # AWS/GCP metadata
    ("168.63.129.16", True, True),     # Azure wireserver
    ("100.64.0.1", True, True),        # CGNAT
    ("fe80::1", True, True),           # link-local
    ("224.0.0.1", True, True),         # multicast
    # Public address: never blocked.
    ("8.8.8.8", False, False),
]


@pytest.mark.parametrize("ip,default_blocked,private_blocked", _CASES)
def test_is_blocked_ip_allow_private(ip, default_blocked, private_blocked) -> None:
    assert (_is_blocked_ip(ip) is not None) is default_blocked
    assert (_is_blocked_ip(ip, allow_private=True) is not None) is private_blocked


def test_check_url_allow_private_permits_loopback_gateway() -> None:
    assert _check_url_for_ssrf("http://127.0.0.1:1234/models") is not None
    assert _check_url_for_ssrf("http://127.0.0.1:1234/models", allow_private=True) is None


def test_check_url_allow_private_still_blocks_metadata() -> None:
    url = "http://169.254.169.254/latest/meta-data/iam/security-credentials/"
    assert _check_url_for_ssrf(url) is not None
    assert _check_url_for_ssrf(url, allow_private=True) is not None


def test_check_url_degrades_on_idna_encoding_failure_instead_of_raising(monkeypatch) -> None:
    """Code-review finding, 2026-07-02: an IDNA-invalid hostname makes
    ``socket.getaddrinfo`` raise ``UnicodeError`` — a ``ValueError``
    subclass, not ``OSError``. The never-raises contract documented on
    ``_check_url_for_ssrf`` requires this to degrade to a blocked result
    (``dns_failure``), not propagate.
    """
    def _raise_unicode_error(host, *args, **kwargs):
        raise UnicodeError("label too long")

    monkeypatch.setattr(
        "backlink_publisher._util.net_safety.socket.getaddrinfo", _raise_unicode_error
    )
    assert _check_url_for_ssrf("http://evil.example.com/") == "dns_failure"
