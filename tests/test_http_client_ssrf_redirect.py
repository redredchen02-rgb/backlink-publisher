"""HttpClient must re-check SSRF on every redirect hop (audit finding [25]).

HttpClient advertised 'SSRF protection' but ran _check_ssrf once on the input URL
then let requests follow 30x redirects with the default allow_redirects=True and
NO per-hop re-validation — so a 302 Location to 127.0.0.1 / 169.254.169.254 was
followed from inside the trust boundary, defeating the one-shot gate. The fix
follows redirects manually with allow_redirects=False, re-checking each hop.
"""
from __future__ import annotations

__tier__ = "unit"

import requests

import pytest

from backlink_publisher._util.errors import ExternalServiceError
from backlink_publisher._util.http_client import HttpClient


# Literal IPs so _check_url_for_ssrf never does DNS (pytest-socket blocks it):
# 93.184.216.34 / 1.1.1.1 are public (pass); 169.254.169.254 is cloud-metadata.
_PUBLIC = "https://93.184.216.34/"
_PUBLIC2 = "https://1.1.1.1/final"
_INTERNAL = "http://169.254.169.254/latest/meta-data/"


def _redirect(location: str, status: int = 302, url: str = _PUBLIC) -> requests.Response:
    r = requests.Response()
    r.status_code = status
    r.headers["Location"] = location
    r.url = url
    return r


def _ok(url: str, body: bytes = b"ok") -> requests.Response:
    r = requests.Response()
    r.status_code = 200
    r.url = url
    r._content = body
    return r


def test_redirect_to_internal_is_blocked_and_never_requested(monkeypatch):
    client = HttpClient()
    requested: list[str] = []

    def fake_request(method, url, **kwargs):
        requested.append(url)
        if url == _PUBLIC:
            return _redirect(_INTERNAL)
        raise AssertionError(f"internal redirect target must never be requested: {url}")

    monkeypatch.setattr(client._session, "request", fake_request)

    with pytest.raises(ExternalServiceError) as exc:
        client.get(_PUBLIC, raise_for_status=False)

    assert "SSRF" in str(exc.value) or "block" in str(exc.value).lower()
    # The internal metadata endpoint must never have been contacted.
    assert requested == [_PUBLIC]


def test_safe_redirect_is_followed_after_recheck(monkeypatch):
    client = HttpClient()

    def fake_request(method, url, **kwargs):
        if url == _PUBLIC:
            return _redirect(_PUBLIC2, url=_PUBLIC)
        return _ok(url)

    monkeypatch.setattr(client._session, "request", fake_request)

    resp = client.get(_PUBLIC, raise_for_status=False)

    assert resp.status_code == 200
    assert resp.url == _PUBLIC2
