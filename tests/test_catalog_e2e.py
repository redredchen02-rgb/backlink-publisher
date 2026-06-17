"""Catalog framework end-to-end tests (Plan 2026-06-16-004 Unit 5).

Proves ConfigDrivenAdapter dispatch works end-to-end for the none-auth
form-POST path: build entry → publish() → AdapterResult.published_url resolved.

verify-dofollow write-back is tested in test_adapter_catalog_registration.py.
"""

from __future__ import annotations

__tier__ = "integration"

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from backlink_publisher._util.errors import ExternalServiceError
from backlink_publisher.publishing.adapters.config_driven import ConfigDrivenAdapter


def _entry(overrides: dict | None = None) -> dict:
    """Minimal valid none-auth form-POST catalog entry."""
    base = {
        "slug": "testplatform",
        "endpoint": "https://test.example.com/submit",
        "auth_type": "none",
        "content_field": "body",
        "csrf_prefetch": False,
        "csrf_field_names": [],
        "permalink_via": "redirect",
        "permalink_arg": "Location",
        "min_delay_s": 0.0,
        "dofollow": True,
    }
    if overrides:
        base.update(overrides)
    return base


def _mock_config() -> MagicMock:
    cfg = MagicMock()
    cfg.api_keys = {}
    return cfg


def _mock_submit_resp(url: str = "https://test.example.com/posts/abc123") -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.url = url
    resp.text = ""
    resp.headers = {}
    return resp


class TestConfigDrivenAdapterE2E:
    """End-to-end dispatch through ConfigDrivenAdapter.publish()."""

    def test_happy_path_redirect_permalink(self):
        """none-auth form-POST: mock submit returns final URL via redirect."""
        entry = _entry()
        adapter = ConfigDrivenAdapter(entry)
        payload = {
            "id": "test-001",
            "title": "Test Title",
            "content_markdown": "Hello world backlink content.",
        }
        expected_url = "https://test.example.com/posts/abc123"
        mock_resp = _mock_submit_resp(expected_url)

        with patch(
            "backlink_publisher.publishing.adapters.http_form_post.requests.post",
            return_value=mock_resp,
        ), patch(
            "backlink_publisher.publishing.adapters.http_form_post.verify_link_attributes",
            return_value={"dofollow": True},
        ):
            result = adapter.publish(payload, mode="live", config=_mock_config())

        assert result.status == "published"
        assert result.published_url == expected_url
        assert result.platform == "testplatform"
        assert result.adapter == "testplatform-config-driven"

    def test_happy_path_draft_mode(self):
        """Draft mode returns status='drafted' and draft_url instead."""
        entry = _entry()
        adapter = ConfigDrivenAdapter(entry)
        payload = {
            "content_markdown": "Draft content here.",
        }
        expected_url = "https://test.example.com/posts/draft123"
        mock_resp = _mock_submit_resp(expected_url)

        with patch(
            "backlink_publisher.publishing.adapters.http_form_post.requests.post",
            return_value=mock_resp,
        ):
            result = adapter.publish(payload, mode="draft", config=_mock_config())

        assert result.status == "drafted"
        assert result.draft_url == expected_url

    def test_5xx_raises_external_service_error(self):
        """5xx from the form-POST endpoint raises ExternalServiceError."""
        entry = _entry()
        adapter = ConfigDrivenAdapter(entry)
        payload = {"content_markdown": "Some content."}

        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = ""
        mock_resp.headers = {}

        with patch(
            "backlink_publisher.publishing.adapters.http_form_post.requests.post",
            return_value=mock_resp,
        ):
            with pytest.raises(ExternalServiceError):
                adapter.publish(payload, mode="live", config=_mock_config())

    def test_missing_content_markdown_raises(self):
        """Payload with no content_markdown raises ExternalServiceError immediately."""
        entry = _entry()
        adapter = ConfigDrivenAdapter(entry)
        payload = {"id": "no-content", "title": "Title only"}

        with pytest.raises(ExternalServiceError, match="no content_markdown"):
            adapter.publish(payload, mode="live", config=_mock_config())

    def test_empty_content_markdown_raises(self):
        """Payload with whitespace-only content raises ExternalServiceError."""
        entry = _entry()
        adapter = ConfigDrivenAdapter(entry)
        payload = {"content_markdown": "   "}

        with pytest.raises(ExternalServiceError, match="no content_markdown"):
            adapter.publish(payload, mode="live", config=_mock_config())

    def test_json_path_permalink(self):
        """json_path permalink_via resolves published_url from JSON body."""
        entry = _entry({
            "permalink_via": "json_path",
            "permalink_arg": "$.data.url",
        })
        adapter = ConfigDrivenAdapter(entry)
        payload = {"content_markdown": "Hello json path."}

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.url = "https://test.example.com/submit"
        mock_resp.text = ""
        mock_resp.headers = {}
        mock_resp.json.return_value = {"data": {"url": "https://test.example.com/posts/json1"}}

        with patch(
            "backlink_publisher.publishing.adapters.http_form_post.requests.post",
            return_value=mock_resp,
        ), patch(
            "backlink_publisher.publishing.adapters.http_form_post.verify_link_attributes",
            return_value={},
        ):
            result = adapter.publish(payload, mode="live", config=_mock_config())

        assert result.published_url == "https://test.example.com/posts/json1"
