"""verify must read enough of <body> to match a deep backlink (audit [07]).

_get_body capped the read at 512KB, but a required backlink can legitimately live
anywhere in <body> (footer / comment area / sidebar) and modern rendered HTML
routinely exceeds 512KB. The sibling comment_outreach fetcher caps at 1.5MB for
exactly this reason; verify was undersized for body-wide link matching.
"""
from __future__ import annotations

__tier__ = "unit"

from unittest.mock import patch

from backlink_publisher.linkcheck.verify import verify_published


def _resp_respecting_cap(body: str):
    data = body.encode("utf-8")

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def getcode(self):
            return 200

        def read(self, size=-1):
            # Unlike a naive fake, honor the size cap so the truncation bug is
            # actually exercised.
            return data if size is None or size < 0 else data[:size]

    def _fake_open(req, **kw):
        return _Resp()

    return _fake_open


def test_verify_finds_required_link_beyond_512kb():
    link = "https://example.com/target"
    # Title up front (matches), link placed ~700KB in — past 512KB, within 1.5MB.
    filler = "x" * (700 * 1024)
    body = (
        "<html><body><h1>My Article Title</h1>"
        + filler
        + f"<footer><a href=\"{link}\">anchor</a></footer></body></html>"
    )
    with patch("backlink_publisher.linkcheck.verify._check_url_for_ssrf", return_value=None), \
         patch("backlink_publisher.linkcheck.verify._open", side_effect=_resp_respecting_cap(body)):
        result = verify_published(
            "https://example.com/post",
            title="My Article Title",
            required_link_urls=[link],
        )
    assert result.ok, f"backlink past 512KB was not matched: reason={result.reason!r}"
