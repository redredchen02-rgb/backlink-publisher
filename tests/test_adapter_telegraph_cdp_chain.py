"""Fallback-chain tests for the telegraph adapter pair.

Chain order (adapters/__init__.py):
  1. TelegraphAPIAdapter   — primary (no Chrome dependency)
  2. TelegraphCdpAdapter   — fallback (requires Chrome binary / CDP port)

Dispatch contract (publishing/_registry_dispatch.py):
  - available() → False          : silently skip, no error stored
  - DependencyError from publish : fall-through to next adapter
  - AuthExpiredError             : propagate immediately (DependencyError subclass)
  - ExternalServiceError         : propagate immediately, no fall-through
  - All adapters exhausted       : re-raise last DependencyError
"""

from __future__ import annotations

__tier__ = "unit"


from unittest.mock import MagicMock, patch

import pytest

from backlink_publisher._util.errors import (
    AuthExpiredError,
    DependencyError,
    ExternalServiceError,
)
from backlink_publisher.config import Config
from backlink_publisher.publishing.adapters import publish
from backlink_publisher.publishing.adapters.base import AdapterResult
from backlink_publisher.publishing.registry import _REGISTRY


# Chain order: API first, CDP second.
_API_PATH = "backlink_publisher.publishing.adapters.TelegraphAPIAdapter.publish"
_CDP_PUBLISH_PATH = "backlink_publisher.publishing.adapters.TelegraphCdpAdapter.publish"
_CDP_AVAIL_PATH = "backlink_publisher.publishing.adapters.TelegraphCdpAdapter.available"


def _payload() -> dict:
    return {
        "id": "tg-chain-test",
        "platform": "telegraph",
        "title": "Chain Test",
        "content_markdown": "Hello from chain test.",
        "tags": [],
        "main_domain": "https://x.example.com/",
        "seo": {"canonical_url": ""},
    }


def _ok(adapter: str = "telegraph-api") -> AdapterResult:
    return AdapterResult(
        status="published",
        adapter=adapter,
        platform="telegraph",
        published_url="https://telegra.ph/ok-01",
    )


CONFIG = Config()


# ── Chain registration ────────────────────────────────────────────────────────


def test_telegraph_chain_contains_both_adapters():
    """TelegraphAPIAdapter precedes TelegraphCdpAdapter in the chain."""
    import backlink_publisher.publishing.adapters  # noqa: F401  ensure registry is populated

    from backlink_publisher.publishing.adapters.instant_web import TelegraphCdpAdapter
    from backlink_publisher.publishing.adapters.telegraph_api import TelegraphAPIAdapter

    entry = _REGISTRY["telegraph"]
    names = [type(p).__name__ if not isinstance(p, type) else p.__name__
             for p in entry.publishers]
    assert "TelegraphAPIAdapter" in names
    assert "TelegraphCdpAdapter" in names
    assert names.index("TelegraphAPIAdapter") < names.index("TelegraphCdpAdapter"), (
        "TelegraphAPIAdapter must precede TelegraphCdpAdapter in the chain"
    )


# ── Happy path ────────────────────────────────────────────────────────────────


def test_api_success_does_not_call_cdp():
    """When TelegraphAPIAdapter succeeds, TelegraphCdpAdapter is never called.

    CDP available() is patched to True so the test is environment-independent:
    the skip must be caused by API success, not by CDP unavailability on the
    test runner.
    """
    # Chain order: API first, CDP second.
    with patch(_API_PATH, return_value=_ok("telegraph-api")) as mock_api, \
         patch(_CDP_AVAIL_PATH, return_value=True), \
         patch(_CDP_PUBLISH_PATH) as mock_cdp:
        result = publish(_payload(), "published", CONFIG)

    assert result.status == "published"
    assert result.adapter == "telegraph-api"
    mock_api.assert_called_once()
    mock_cdp.assert_not_called()


# ── Skip via available() ──────────────────────────────────────────────────────


def test_cdp_skipped_when_not_available():
    """When TelegraphCdpAdapter.available() returns False, it is silently skipped.
    If API also fails with DependencyError, the chain re-raises that error."""
    # CDP unavailable → skip; API raises DependencyError → chain exhausted → re-raise
    with patch(_CDP_AVAIL_PATH, return_value=False), \
         patch(_API_PATH, side_effect=DependencyError("no token")):
        with pytest.raises(DependencyError):
            publish(_payload(), "published", CONFIG)


def test_cdp_skipped_when_not_available_api_succeeds():
    """When CDP is unavailable but API succeeds, the result is the API result."""
    with patch(_CDP_AVAIL_PATH, return_value=False), \
         patch(_API_PATH, return_value=_ok("telegraph-api")):
        result = publish(_payload(), "published", CONFIG)

    assert result.adapter == "telegraph-api"


# ── Fall-through via DependencyError ─────────────────────────────────────────


def test_api_dependency_error_falls_through_to_cdp():
    """When TelegraphAPIAdapter raises DependencyError, CDP is tried next."""
    # Chain order: API first, CDP second.
    with patch(_API_PATH, side_effect=DependencyError("no api token")), \
         patch(_CDP_AVAIL_PATH, return_value=True), \
         patch(_CDP_PUBLISH_PATH, return_value=_ok("telegraph-cdp")) as mock_cdp:
        result = publish(_payload(), "published", CONFIG)

    assert result.status == "published"
    assert result.adapter == "telegraph-cdp"
    mock_cdp.assert_called_once()


# ── ExternalServiceError does NOT fall through ────────────────────────────────


def test_api_external_service_error_propagates_no_cdp():
    """ExternalServiceError from TelegraphAPIAdapter propagates immediately;
    TelegraphCdpAdapter must never be called."""
    with patch(_API_PATH, side_effect=ExternalServiceError("503")), \
         patch(_CDP_PUBLISH_PATH) as mock_cdp:
        with pytest.raises(ExternalServiceError):
            publish(_payload(), "published", CONFIG)

    mock_cdp.assert_not_called()


# ── AuthExpiredError does NOT fall through ────────────────────────────────────


def test_api_auth_expired_propagates_no_cdp():
    """AuthExpiredError (DependencyError subclass) propagates without fall-through.

    telegraph is not a bindable channel (token rotates via createAccount API),
    so AuthExpiredError requires a valid channel name ('blogger', 'medium', 'velog').
    We use 'blogger' here — the test verifies the dispatch contract, not the channel.
    """
    with patch(_API_PATH,
               side_effect=AuthExpiredError(channel="blogger", reason="expired")), \
         patch(_CDP_PUBLISH_PATH) as mock_cdp:
        with pytest.raises(AuthExpiredError):
            publish(_payload(), "published", CONFIG)

    mock_cdp.assert_not_called()


# ── All adapters fail ─────────────────────────────────────────────────────────


def test_all_adapters_dependency_error_reraises_last():
    """When both API and CDP raise DependencyError, the last error is re-raised."""
    with patch(_API_PATH, side_effect=DependencyError("api fail")), \
         patch(_CDP_AVAIL_PATH, return_value=True), \
         patch(_CDP_PUBLISH_PATH, side_effect=DependencyError("cdp fail")):
        with pytest.raises(DependencyError, match="cdp fail"):
            publish(_payload(), "published", CONFIG)


# ── CDP ExternalServiceError propagates ───────────────────────────────────────


def test_cdp_external_service_error_propagates():
    """ExternalServiceError from TelegraphCdpAdapter propagates; no further adapters."""
    with patch(_API_PATH, side_effect=DependencyError("api no token")), \
         patch(_CDP_AVAIL_PATH, return_value=True), \
         patch(_CDP_PUBLISH_PATH, side_effect=ExternalServiceError("cdp 500")):
        with pytest.raises(ExternalServiceError, match="cdp 500"):
            publish(_payload(), "published", CONFIG)
