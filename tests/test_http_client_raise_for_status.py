"""HttpClient ``raise_for_status`` opt-out contract.

The opt-out lets status-inspecting callers (publish adapters that map 401/403
to their own domain errors) route through the SSRF-safe client without the
client pre-empting them by raising on the first non-2xx. SSRF, timeout, and
retry still apply — only the terminal ``raise_for_status()`` is skipped.
"""
from __future__ import annotations

__tier__ = "unit"

from unittest.mock import MagicMock, patch

import pytest
import requests

from backlink_publisher._util.errors import ExternalServiceError
from backlink_publisher._util.http_client import HttpClient


def _resp(status: int) -> MagicMock:
    resp = MagicMock(spec=requests.Response)
    resp.status_code = status
    resp.raise_for_status.side_effect = (
        requests.HTTPError(f"{status}") if status >= 400 else None
    )
    return resp


@patch("backlink_publisher._util.http_client._check_url_for_ssrf", return_value=None)
def test_raise_for_status_false_returns_non_2xx_without_raising(_ssrf) -> None:
    client = HttpClient()
    resp = _resp(403)
    with patch.object(client._session, "request", return_value=resp) as req:
        out = client.post("https://api.example.com/x", raise_for_status=False)
    assert out is resp
    assert out.status_code == 403
    resp.raise_for_status.assert_not_called()
    # SSRF/timeout still wired: timeout default injected into the call.
    assert req.call_args.kwargs["timeout"] == client._timeout


@patch("backlink_publisher._util.http_client._check_url_for_ssrf", return_value=None)
def test_default_still_raises_on_non_2xx(_ssrf) -> None:
    client = HttpClient(max_retries=0)
    resp = _resp(500)
    with patch.object(client._session, "request", return_value=resp):
        with pytest.raises(ExternalServiceError):
            client.post("https://api.example.com/x")


def test_ssrf_check_runs_even_with_opt_out() -> None:
    client = HttpClient()
    with patch(
        "backlink_publisher._util.http_client._check_url_for_ssrf",
        return_value="blocked-metadata",
    ):
        with pytest.raises(ExternalServiceError):
            client.get("http://169.254.169.254/latest/meta-data", raise_for_status=False)


def test_allow_private_threads_to_ssrf_check() -> None:
    """allow_private must reach _check_url_for_ssrf so loopback gateways pass."""
    client = HttpClient()
    resp = _resp(200)
    with patch(
        "backlink_publisher._util.http_client._check_url_for_ssrf", return_value=None
    ) as ssrf, patch.object(client._session, "request", return_value=resp):
        client.get("http://127.0.0.1:1234/models", allow_private=True)
    assert ssrf.call_args.kwargs["allow_private"] is True
