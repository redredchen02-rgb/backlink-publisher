"""linkcheck must fetch via the SSRF-safe opener, not bare urlopen (audit [22][24]).

Bare urllib.request.urlopen uses the process-global opener whose stdlib
HTTPRedirectHandler follows 30x redirects with NO SSRF re-check, so linkcheck's
one-shot _check_url_for_ssrf was defeated by a single 302 to an internal /
cloud-metadata host. The fix routes both fetchers through
net_safety._make_ssrf_opener, whose _SSRFSafeRedirectHandler re-validates every
hop and refuses https->http downgrades (the pattern content/fetch already uses).
"""
from __future__ import annotations

__tier__ = "unit"

from backlink_publisher._util.net_safety import _SSRFSafeRedirectHandler


class _FakeResp:
    def __init__(self, code: int = 200, body: bytes = b"<html>hi</html>") -> None:
        self._code, self._body = code, body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def getcode(self) -> int:
        return self._code

    def read(self, n: int = -1) -> bytes:
        return self._body


class _FakeOpener:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def open(self, req, timeout=None):
        self.calls.append(req.full_url)
        return _FakeResp()


def test_verify_get_body_routes_through_ssrf_safe_opener(monkeypatch):
    from backlink_publisher.linkcheck import verify

    fake = _FakeOpener()
    monkeypatch.setattr(verify, "_make_ssrf_opener", lambda **kw: fake)
    monkeypatch.setattr(verify, "_check_url_for_ssrf", lambda u: None)

    code, body = verify._get_body("https://example.com/x")

    assert code == 200 and "hi" in body
    assert fake.calls and fake.calls[0].startswith("https://example.com")


def test_http_check_url_once_routes_through_ssrf_safe_opener(monkeypatch):
    from backlink_publisher.linkcheck import http as lchttp

    fake = _FakeOpener()
    monkeypatch.setattr(lchttp, "_make_ssrf_opener", lambda **kw: fake)
    monkeypatch.setattr(lchttp, "_check_url_for_ssrf", lambda u: None)

    ok, err = lchttp._check_url_once("https://example.com/y")

    assert ok is True and err is None
    assert fake.calls  # the fetch went through the SSRF-safe opener


def test_linkcheck_openers_carry_the_ssrf_redirect_handler():
    from backlink_publisher.linkcheck.http import _make_ssrf_opener as h_opener
    from backlink_publisher.linkcheck.verify import _make_ssrf_opener as v_opener

    for make in (v_opener, h_opener):
        opener = make()
        assert any(isinstance(h, _SSRFSafeRedirectHandler) for h in opener.handlers)


def test_check_url_once_rejects_non_http_scheme():
    # ftp:// (and other non-web schemes) must never reach the opener (audit [24]).
    from backlink_publisher.linkcheck import http as lchttp

    ok, err = lchttp._check_url_once("ftp://ftp.example.com/x")
    assert ok is False
    assert err is not None
