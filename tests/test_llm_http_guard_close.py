"""Regression: safe_post_json must release the pooled connection on every path.

Audit finding [34]: safe_post_json posts with stream=True but never closed the
response on its three early-exit ValueError branches (3xx redirect, non-JSON
content-type, oversize body). An unconsumed streamed requests.Response holds its
urllib3 connection, defeating connection reuse for guard-violating responses.
"""

from __future__ import annotations

from unittest import mock

import pytest

from backlink_publisher.llm import http_guard


def _mock_response(**attrs):
    resp = mock.MagicMock()
    # requests.Response.__enter__ returns self; __exit__ calls self.close().
    resp.__enter__.return_value = resp
    for k, v in attrs.items():
        setattr(resp, k, v)
    return resp


def _post_returning(resp):
    return mock.patch.object(http_guard._SESSION, "post", return_value=resp)


def test_redirect_closes_response():
    resp = _mock_response(status_code=302, headers={"Content-Type": "application/json"})
    with _post_returning(resp):
        with pytest.raises(ValueError, match="redirect_not_allowed"):
            http_guard.safe_post_json("https://x.example/v1", {}, {})
    resp.close.assert_called()


def test_bad_content_type_closes_response():
    resp = _mock_response(status_code=200, headers={"Content-Type": "text/html"})
    with _post_returning(resp):
        with pytest.raises(ValueError, match="bad_content_type"):
            http_guard.safe_post_json("https://x.example/v1", {}, {})
    resp.close.assert_called()


def test_oversize_body_closes_response():
    big = b"x" * (http_guard.LLM_MAX_RESPONSE_BYTES + 1)
    resp = _mock_response(
        status_code=200,
        headers={"Content-Type": "application/json"},
    )
    resp.iter_content.return_value = iter([big])
    with _post_returning(resp):
        with pytest.raises(ValueError, match="response_too_large"):
            http_guard.safe_post_json("https://x.example/v1", {}, {})
    resp.close.assert_called()
