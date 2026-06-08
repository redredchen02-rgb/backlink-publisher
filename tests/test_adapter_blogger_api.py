"""Tests for BloggerAPIAdapter (plan016 U6 — SessionManager-based auth)."""
__tier__ = "unit"

from unittest.mock import MagicMock, patch

import pytest

from backlink_publisher.publishing.adapters.blogger_api import BloggerAPIAdapter
from backlink_publisher.config import Config, BloggerOAuthConfig
from backlink_publisher._util.errors import AuthExpiredError, DependencyError, ExternalServiceError

PAYLOAD = {
    "id": "abc123",
    "title": "Test Post",
    "content_markdown": "# Hello\n\nWorld.",
    "tags": ["tag1", "tag2"],
    "main_domain": "https://myblog.com/",
    "publish_mode": "draft",
}

CONFIG = Config(
    blogger_blog_ids={"https://myblog.com": "999"},
    blogger_oauth=BloggerOAuthConfig("cid", "csecret"),
)

_POST_URL = "https://myblog.blogspot.com/2026/05/post.html"


def _mock_session(post_result=None, status_code=200):
    mock_resp = MagicMock()
    mock_resp.ok = 200 <= status_code < 300
    mock_resp.status_code = status_code
    mock_resp.text = "error body"
    mock_resp.json.return_value = post_result or {"url": _POST_URL, "id": "12345"}
    session = MagicMock()
    session.post.return_value = mock_resp
    return session


def _patch_session(session):
    return patch(
        "backlink_publisher.publishing.adapters.blogger_api.SessionManager.get_session",
        return_value=session,
    )


# ── basic happy paths ─────────────────────────────────────────────────────────

def test_draft_mode_returns_draft_url():
    with _patch_session(_mock_session()):
        result = BloggerAPIAdapter().publish(PAYLOAD, mode="draft", config=CONFIG)
    assert result.status == "drafted"
    assert result.draft_url == _POST_URL
    assert result.published_url == ""
    assert result.adapter == "blogger-api"


def test_publish_mode_returns_published_url():
    with _patch_session(_mock_session()):
        result = BloggerAPIAdapter().publish(PAYLOAD, mode="publish", config=CONFIG)
    assert result.status == "published"
    assert result.published_url == _POST_URL
    assert result.draft_url == ""


def test_missing_blog_id_raises_dependency_error():
    with pytest.raises(DependencyError, match="https://myblog.com"):
        BloggerAPIAdapter().publish(PAYLOAD, mode="draft", config=Config(blogger_blog_ids={}))


# ── HTTP error handling ───────────────────────────────────────────────────────

def test_http_401_raises_auth_expired_error():
    with _patch_session(_mock_session(status_code=401)):
        with pytest.raises(AuthExpiredError) as exc_info:
            BloggerAPIAdapter().publish(PAYLOAD, mode="draft", config=CONFIG)
    assert exc_info.value.channel == "blogger"
    assert "Blogger HTTP 401" in (exc_info.value.reason or "")
    assert isinstance(exc_info.value, DependencyError)


def test_http_403_raises_auth_expired_error():
    with _patch_session(_mock_session(status_code=403)):
        with pytest.raises(AuthExpiredError) as exc_info:
            BloggerAPIAdapter().publish(PAYLOAD, mode="draft", config=CONFIG)
    assert exc_info.value.channel == "blogger"
    assert "Blogger HTTP 403" in (exc_info.value.reason or "")


@patch("backlink_publisher.publishing.adapters.retry.time.sleep")
def test_http_429_raises_rate_limited(mock_sleep):
    with _patch_session(_mock_session(status_code=429)):
        with pytest.raises(ExternalServiceError, match="rate-limited"):
            BloggerAPIAdapter().publish(PAYLOAD, mode="draft", config=CONFIG)


@patch("backlink_publisher.publishing.adapters.retry.time.sleep")
def test_429_retried_and_recovers(mock_sleep):
    session = MagicMock()
    resp_429 = MagicMock(ok=False, status_code=429, text="rate limited")
    resp_429.json.return_value = {}
    resp_ok = MagicMock(ok=True, status_code=200, text="")
    resp_ok.json.return_value = {"url": _POST_URL}
    session.post.side_effect = [resp_429, resp_ok]

    with _patch_session(session):
        result = BloggerAPIAdapter().publish(PAYLOAD, mode="draft", config=CONFIG)
    assert result.status == "drafted"
    mock_sleep.assert_called_once()


@patch("backlink_publisher.publishing.adapters.retry.time.sleep")
def test_429_exhaustion_raises_external_service_error(mock_sleep):
    with _patch_session(_mock_session(status_code=429)):
        with pytest.raises(ExternalServiceError, match="rate-limited"):
            BloggerAPIAdapter().publish(PAYLOAD, mode="draft", config=CONFIG)
    assert mock_sleep.call_count == 2  # 2 retries → 2 sleeps


@patch("backlink_publisher.publishing.adapters.retry.time.sleep")
def test_401_not_retried(mock_sleep):
    with _patch_session(_mock_session(status_code=401)):
        with pytest.raises(AuthExpiredError):
            BloggerAPIAdapter().publish(PAYLOAD, mode="draft", config=CONFIG)
    mock_sleep.assert_not_called()


@patch("backlink_publisher.publishing.adapters.retry.time.sleep")
def test_5xx_not_retried(mock_sleep):
    with _patch_session(_mock_session(status_code=503)):
        with pytest.raises(ExternalServiceError, match="503"):
            BloggerAPIAdapter().publish(PAYLOAD, mode="draft", config=CONFIG)
    mock_sleep.assert_not_called()


# ── body construction ─────────────────────────────────────────────────────────

def test_tags_truncated_to_20():
    session = MagicMock()
    resp = MagicMock(ok=True, status_code=200)
    resp.json.return_value = {"url": _POST_URL}
    session.post.return_value = resp

    with _patch_session(session):
        BloggerAPIAdapter().publish({**PAYLOAD, "tags": [f"t{i}" for i in range(30)]},
                                    mode="draft", config=CONFIG)

    call_kwargs = session.post.call_args[1]
    assert len(call_kwargs["json"]["labels"]) == 20


def test_draft_mode_sends_isDraft_true():
    session = MagicMock()
    resp = MagicMock(ok=True, status_code=200)
    resp.json.return_value = {"url": _POST_URL}
    session.post.return_value = resp

    with _patch_session(session):
        BloggerAPIAdapter().publish(PAYLOAD, mode="draft", config=CONFIG)

    call_kwargs = session.post.call_args[1]
    assert call_kwargs["params"] == {"isDraft": "true"}


def test_publish_mode_sends_no_isDraft():
    session = MagicMock()
    resp = MagicMock(ok=True, status_code=200)
    resp.json.return_value = {"url": _POST_URL}
    session.post.return_value = resp

    with _patch_session(session):
        BloggerAPIAdapter().publish(PAYLOAD, mode="publish", config=CONFIG)

    call_kwargs = session.post.call_args[1]
    assert call_kwargs["params"] == {}
