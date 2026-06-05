"""Tests for ConfigDrivenAdapter (Plan 2026-06-05-005 U2).

Covers both auth paths (form-POST + API key), permalink resolution
(redirect / json_path / regex), challenge detection, and draft mode.
All network is mocked.
"""

from __future__ import annotations

from unittest import mock

import pytest
import requests

from backlink_publisher._util.errors import (
    AntiBotChallengeError,
    DependencyError,
    ExternalServiceError,
)
from backlink_publisher.publishing.adapters.config_driven import (
    ConfigDrivenAdapter,
    _get_api_key,
    _resolve_jsonpath,
    _resolve_permalink,
)


class _FakeRequest:
    """Stand-in for requests.PreparedRequest — callable, str() returns URL."""

    def __init__(self, url: str = "") -> None:
        self.url = url

    def __str__(self) -> str:
        return self.url

    def __call__(self) -> str:
        return self.url


class _MockResp:
    """Minimal requests.Response stand-in for mocking.

    After a redirect ``response.url`` differs from the original request URL;
    pass ``request_url`` to simulate that.  Defaults to ``url`` (= no redirect).
    """

    def __init__(
        self,
        *,
        status_code: int = 200,
        text: str = "",
        url: str = "",
        request_url: str | None = None,
        headers: dict | None = None,
        json_data: dict | None = None,
    ) -> None:
        self.status_code = status_code
        self.text = text
        self.url = url
        self.headers = headers or {}
        self._json_data = json_data
        self.request = _FakeRequest(request_url or url)

    def json(self):
        if self._json_data is not None:
            return self._json_data
        raise ValueError("No JSON data set")


# ── Fixture: a valid form-POST catalog entry ─────────────────────────────

_FORM_ENTRY: dict = {
    "slug": "testform",
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

_API_ENTRY: dict = {
    "slug": "testapi",
    "endpoint": "https://api.example.com/posts",
    "auth_type": "api_key_header",
    "content_field": "content",
    "csrf_prefetch": False,
    "csrf_field_names": [],
    "permalink_via": "json_path",
    "permalink_arg": "$.data.url",
    "min_delay_s": 0.0,
    "dofollow": "uncertain",
    "rationale": "x" * 80,
    "referral_value": "low",
}

_PAYLOAD: dict = {
    "id": "row-001",
    "title": "Test Article",
    "content_markdown": "Hello **world** with [link](https://example.com/)",
}


# ── _resolve_permalink ───────────────────────────────────────────────────

class TestResolvePermalink:
    """permalink resolution via redirect / json_path / regex."""

    def test_redirect_returns_response_url(self):
        resp = _MockResp(
            url="https://test.example.com/view/abc123",
            request_url="https://test.example.com/submit",
        )
        url = _resolve_permalink(resp, "redirect", "Location")
        assert url == "https://test.example.com/view/abc123"

    def test_redirect_no_redirect_raises(self):
        resp = _MockResp(
            url="https://test.example.com/submit",
            request_url="https://test.example.com/submit",
        )
        with pytest.raises(ExternalServiceError, match="redirect"):
            _resolve_permalink(resp, "redirect", "Location")

    def test_json_path_resolves(self):
        resp = _MockResp(json_data={"data": {"url": "https://api.example.com/p/42"}})
        url = _resolve_permalink(resp, "json_path", "$.data.url")
        assert url == "https://api.example.com/p/42"

    def test_json_path_not_json_raises(self):
        resp = _MockResp(text="not json")
        with pytest.raises(ExternalServiceError, match="json_path"):
            _resolve_permalink(resp, "json_path", "$.data.url")

    def test_json_path_missing_key_raises(self):
        resp = _MockResp(json_data={"ok": True})
        with pytest.raises(ExternalServiceError, match="None"):
            _resolve_permalink(resp, "json_path", "$.data.url")

    def test_regex_matches(self):
        resp = _MockResp(text="Here is the URL: https://x.com/p/42\n")
        url = _resolve_permalink(resp, "regex", r"https://\S+")
        assert url == "https://x.com/p/42"

    def test_regex_no_match_raises(self):
        resp = _MockResp(text="no url here")
        with pytest.raises(ExternalServiceError, match="regex"):
            _resolve_permalink(resp, "regex", r"https://\S+")

    def test_unknown_permalink_via_raises(self):
        resp = _MockResp()
        with pytest.raises(ExternalServiceError, match="permalink_via"):
            _resolve_permalink(resp, "unknown", "")


# ── _resolve_jsonpath ────────────────────────────────────────────────────

class TestResolveJsonPath:
    """Dot-delimited JSON path resolution helper."""

    def test_simple_path(self):
        assert _resolve_jsonpath({"a": {"b": "c"}}, "$.a.b") == "c"

    def test_root_only(self):
        assert _resolve_jsonpath(42, "$") == "42"

    def test_missing_segment_returns_none(self):
        assert _resolve_jsonpath({"a": 1}, "$.b") is None

    def test_none_value_returns_none(self):
        assert _resolve_jsonpath({"a": None}, "$.a") is None

    def test_no_dollar_prefix_returns_none(self):
        assert _resolve_jsonpath({"a": 1}, "a") is None

    def test_non_dict_intermediate_returns_none(self):
        assert _resolve_jsonpath({"a": [1, 2]}, "$.a.b") is None


# ── _get_api_key ─────────────────────────────────────────────────────────

class TestGetApiKey:
    """API key resolution from config."""

    def test_key_from_config(self):
        class FakeConfig:
            api_keys = {"testapi": "sk-abc123"}
        entry = {"slug": "testapi"}
        assert _get_api_key(entry, FakeConfig()) == "sk-abc123"

    def test_missing_key_raises_dependency(self):
        class FakeConfig:
            api_keys = {}
        entry = {"slug": "testapi"}
        with pytest.raises(DependencyError, match="API key"):
            _get_api_key(entry, FakeConfig())

    def test_empty_api_keys_raises_dependency(self):
        class FakeConfig:
            api_keys = None  # type: ignore[assignment]
        entry = {"slug": "testapi"}
        with pytest.raises(DependencyError, match="API key"):
            _get_api_key(entry, FakeConfig())


# ═══════════════════════════════════════════════════════════════════════════
# ConfigDrivenAdapter — publish()
# ═══════════════════════════════════════════════════════════════════════════

class _FakeConfig:
    """Minimal config for tests that do not touch the real config system."""
    api_keys: dict = {}
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


@pytest.fixture
def adapter_form():
    return ConfigDrivenAdapter(_FORM_ENTRY)


@pytest.fixture
def adapter_api():
    return ConfigDrivenAdapter(_API_ENTRY)


class TestFormPostAuth:
    """auth_type=none — anonymous form-POST path."""

    def test_happy_path_returns_adapter_result(self, adapter_form):
        """Form POST with redirect returns a published AdapterResult."""
        resp = _MockResp(
            status_code=302,
            url="https://test.example.com/view/abc123",
            request_url="https://test.example.com/submit",
        )
        with mock.patch(
            "backlink_publisher.publishing.adapters.config_driven.submit_form",
            return_value=resp,
        ) as msubmit:
            result = adapter_form.publish(
                _PAYLOAD, mode="publish", config=_FakeConfig()
            )

        assert result.status == "published"
        assert result.platform == "testform"
        assert result.published_url == "https://test.example.com/view/abc123"
        msubmit.assert_called_once()

    @mock.patch(
        "backlink_publisher.publishing.adapters.config_driven.fetch_form"
    )
    @mock.patch(
        "backlink_publisher.publishing.adapters.config_driven.extract_hidden_fields"
    )
    def test_csrf_prefetch_extracts_hidden_fields(
        self, mock_extract, mock_fetch, adapter_form
    ):
        """When csrf_prefetch is True, form is fetched and hidden fields extracted."""
        entry = dict(_FORM_ENTRY)
        entry["csrf_prefetch"] = True
        entry["csrf_field_names"] = ["csrf_token", "form_time"]
        adapter = ConfigDrivenAdapter(entry)

        mock_fetch.return_value = _MockResp(
            status_code=200, text="<form>...</form>"
        )
        mock_extract.return_value = {
            "csrf_token": "abc123",
            "form_time": "1779679194",
        }

        resp = _MockResp(
            status_code=302,
            url="https://test.example.com/view/abc123",
            request_url="https://test.example.com/submit",
        )
        with mock.patch(
            "backlink_publisher.publishing.adapters.config_driven.submit_form",
            return_value=resp,
        ):
            result = adapter.publish(
                _PAYLOAD, mode="publish", config=_FakeConfig()
            )

        assert result.status == "published"
        mock_fetch.assert_called_once()
        mock_extract.assert_called_once()

    def test_missing_content_raises(self, adapter_form):
        """No content_markdown in payload raises ExternalServiceError."""
        with pytest.raises(ExternalServiceError, match="content_markdown"):
            adapter_form.publish(
                {"id": "bad", "title": ""}, mode="publish", config=_FakeConfig()
            )

    def test_draft_mode_returns_draft_status(self, adapter_form):
        """mode='draft' returns AdapterResult with status='drafted'."""
        resp = _MockResp(
            status_code=302,
            url="https://test.example.com/view/draft123",
            request_url="https://test.example.com/submit",
        )
        with mock.patch(
            "backlink_publisher.publishing.adapters.config_driven.submit_form",
            return_value=resp,
        ):
            result = adapter_form.publish(
                _PAYLOAD, mode="draft", config=_FakeConfig()
            )

        assert result.status == "drafted"
        assert result.draft_url == "https://test.example.com/view/draft123"
        assert result.published_url == ""


class TestApiKeyAuth:
    """auth_type=api_key_header / api_key_query — REST API path."""

    def test_api_key_header_happy_path(self, adapter_api):
        """API key header auth returns a published AdapterResult."""
        resp = _MockResp(
            status_code=201,
            json_data={"data": {"url": "https://api.example.com/p/42"}},
        )
        config = _FakeConfig(api_keys={"testapi": "sk-secret-123"})

        with mock.patch(
            "backlink_publisher.publishing.adapters.config_driven.requests.post",
            return_value=resp,
        ) as mpost:
            result = adapter_api.publish(
                _PAYLOAD, mode="publish", config=config
            )

        assert result.status == "published"
        assert result.published_url == "https://api.example.com/p/42"
        _, kwargs = mpost.call_args
        assert "Authorization" in kwargs["headers"]
        assert kwargs["headers"]["Authorization"] == "Bearer sk-secret-123"
        assert kwargs["json"]["content"] == "# Test Article\n\nHello **world** with [link](https://example.com/)"

    def test_api_key_query_appends_key(self):
        """api_key_query appends api_key as query parameter."""
        entry = dict(_API_ENTRY)
        entry["auth_type"] = "api_key_query"
        entry["permalink_via"] = "redirect"
        entry["permalink_arg"] = "Location"
        adapter = ConfigDrivenAdapter(entry)

        resp = _MockResp(
            status_code=201,
            url="https://api.example.com/p/42",
            request_url="https://api.example.com/posts",
        )
        config = _FakeConfig(api_keys={"testapi": "q-key-789"})

        with mock.patch(
            "backlink_publisher.publishing.adapters.config_driven.requests.post",
            return_value=resp,
        ) as mpost:
            result = adapter.publish(
                _PAYLOAD, mode="publish", config=config
            )

        assert result.status == "published"
        args, kwargs = mpost.call_args
        assert "api_key=q-key-789" in args[0]

    def test_missing_api_key_raises_dependency(self, adapter_api):
        """No API key in config raises DependencyError."""
        with pytest.raises(DependencyError, match="API key"):
            adapter_api.publish(
                _PAYLOAD, mode="publish", config=_FakeConfig()
            )

    def test_api_401_raises_external_service(self, adapter_api):
        """HTTP 401 raises ExternalServiceError (not DependencyError)."""
        resp = _MockResp(status_code=401, text="unauthorized")
        config = _FakeConfig(api_keys={"testapi": "sk-bad-key"})

        with mock.patch(
            "backlink_publisher.publishing.adapters.config_driven.requests.post",
            return_value=resp,
        ):
            with pytest.raises(ExternalServiceError, match="401"):
                adapter_api.publish(
                    _PAYLOAD, mode="publish", config=config
                )


class TestPermalinkResolution:
    """Different permalink_via strategies."""

    def test_redirect_permalink(self):
        """permalink_via='redirect' uses the response URL."""
        entry = dict(_FORM_ENTRY)
        entry["permalink_via"] = "redirect"
        entry["permalink_arg"] = "Location"
        adapter = ConfigDrivenAdapter(entry)

        resp = _MockResp(
            status_code=302,
            url="https://test.example.com/p/99",
            request_url="https://test.example.com/submit",
        )
        with mock.patch(
            "backlink_publisher.publishing.adapters.config_driven.submit_form",
            return_value=resp,
        ):
            result = adapter.publish(
                _PAYLOAD, mode="publish", config=_FakeConfig()
            )
        assert result.published_url == "https://test.example.com/p/99"

    def test_json_path_permalink(self):
        """permalink_via='json_path' parses JSON response body."""
        entry = dict(_API_ENTRY)
        entry["auth_type"] = "api_key_header"
        entry["permalink_via"] = "json_path"
        entry["permalink_arg"] = "$.url"
        adapter = ConfigDrivenAdapter(entry)

        resp = _MockResp(
            status_code=201,
            json_data={"url": "https://api.example.com/p/88"},
        )
        config = _FakeConfig(api_keys={"testapi": "sk-key"})

        with mock.patch(
            "backlink_publisher.publishing.adapters.config_driven.requests.post",
            return_value=resp,
        ):
            result = adapter.publish(
                _PAYLOAD, mode="publish", config=config
            )
        assert result.published_url == "https://api.example.com/p/88"

    def test_regex_permalink(self):
        """permalink_via='regex' matches response body."""
        entry = dict(_API_ENTRY)
        entry["auth_type"] = "api_key_header"
        entry["permalink_via"] = "regex"
        entry["permalink_arg"] = r"https://\S+"
        adapter = ConfigDrivenAdapter(entry)

        resp = _MockResp(
            status_code=201,
            text="This is my new post at https://x.com/p/77 check it out",
        )
        config = _FakeConfig(api_keys={"testapi": "sk-key"})

        with mock.patch(
            "backlink_publisher.publishing.adapters.config_driven.requests.post",
            return_value=resp,
        ):
            result = adapter.publish(
                _PAYLOAD, mode="publish", config=config
            )
        assert result.published_url == "https://x.com/p/77"


class TestErrorPaths:
    """Error handling and edge cases."""

    def test_empty_title_does_not_prepend_hash(self, adapter_form):
        """Empty title does not add '# ' prefix to body."""
        resp = _MockResp(
            status_code=302,
            url="https://test.example.com/view/no-title",
            request_url="https://test.example.com/submit",
        )
        payload = {"id": "nt", "title": "", "content_markdown": "Just body"}

        with mock.patch(
            "backlink_publisher.publishing.adapters.config_driven.submit_form",
            return_value=resp,
        ) as msubmit:
            adapter_form.publish(payload, mode="publish", config=_FakeConfig())

        args, _ = msubmit.call_args
        body_data = args[1]
        assert "Just body" in body_data["body"]
        assert "# " not in body_data["body"]

    def test_min_delay_adds_sleep(self):
        """min_delay_s > 0 causes a time.sleep."""
        entry = dict(_FORM_ENTRY)
        entry["min_delay_s"] = 0.01  # small enough for tests
        adapter = ConfigDrivenAdapter(entry)

        resp = _MockResp(
            status_code=302,
            url="https://test.example.com/view/delayed",
            request_url="https://test.example.com/submit",
        )
        with mock.patch(
            "backlink_publisher.publishing.adapters.config_driven.submit_form",
            return_value=resp,
        ), mock.patch(
            "backlink_publisher.publishing.adapters.config_driven.attach_link_verification",
            return_value=None,
        ), mock.patch(
            "backlink_publisher.publishing.adapters.config_driven.time.sleep"
        ) as msleep:
            adapter.publish(
                _PAYLOAD, mode="publish", config=_FakeConfig()
            )
        msleep.assert_called_once_with(0.01)

    def test_adapter_available_always_true(self, adapter_form):
        """available() always returns True — no platform-specific gating."""
        assert adapter_form.available(_FakeConfig())
