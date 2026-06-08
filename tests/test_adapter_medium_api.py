"""Tests for MediumAPIAdapter."""
__tier__ = "unit"

from unittest.mock import MagicMock, patch

import pytest
import requests as req

from backlink_publisher.publishing.adapters.medium_api import MediumAPIAdapter
from backlink_publisher.config import Config
from backlink_publisher._util.errors import AuthExpiredError, DependencyError, ExternalServiceError

PAYLOAD = {
    "id": "abc123",
    "title": "Test Post",
    "content_markdown": "# Hello\n\nWorld with [link](https://example.com).",
    "tags": ["tag1", "tag2", "tag3", "tag4", "tag5", "tag6"],
    "seo": {"canonical_url": "https://example.com/article"},
    "publish_mode": "draft",
}

CONFIG = Config()

ME_RESP = {"data": {"id": "user123", "username": "testuser"}}
POST_RESP_DRAFT = {"data": {"id": "post456", "url": "https://medium.com/@testuser/test-post-abc123"}}

_SM = "backlink_publisher.publishing.adapters.medium_api.SessionManager"


def make_mock_get(status=200, json_data=None):
    resp = MagicMock()
    resp.status_code = status
    resp.ok = status < 400
    resp.json.return_value = json_data or ME_RESP
    return resp


def make_mock_post(status=201, json_data=None):
    resp = MagicMock()
    resp.status_code = status
    resp.ok = status < 400
    resp.json.return_value = json_data or POST_RESP_DRAFT
    resp.text = ""
    return resp


def _mock_sm(get_resp=None, post_resp=None):
    """Return (patched SM class, mock session). Session .get/.post pre-configured."""
    mock_cls = MagicMock()
    mock_sess = MagicMock()
    mock_sess.get.return_value = get_resp or make_mock_get()
    mock_sess.post.return_value = post_resp or make_mock_post()
    mock_cls.return_value.get_session.return_value = mock_sess
    return mock_cls, mock_sess


def test_no_token_raises_dependency_error():
    """If SessionManager cannot load credentials, DependencyError propagates."""
    adapter = MediumAPIAdapter()
    with patch(_SM) as MockSM:
        MockSM.return_value.get_session.side_effect = DependencyError("integration token not configured")
        with pytest.raises(DependencyError):
            adapter.publish(PAYLOAD, mode="draft", config=CONFIG)


@patch(_SM)
def test_draft_mode_returns_draft_url(MockSM):
    MockSM.return_value.get_session.return_value = _mock_sm()[1]

    adapter = MediumAPIAdapter()
    result = adapter.publish(PAYLOAD, mode="draft", config=CONFIG)

    assert result.status == "drafted"
    assert result.draft_url == "https://medium.com/@testuser/test-post-abc123"
    assert result.published_url == ""
    assert result.adapter == "medium-api"


@patch(
    "backlink_publisher.publishing.adapters.medium_api.verify_link_attributes",
    return_value={"verification": "skipped", "reason": "test-mock"},
)
@patch(_SM)
def test_publish_mode_sends_public_status(MockSM, _mock_verify):
    mock_cls, mock_sess = _mock_sm()
    pub_resp = {"data": {"id": "post789", "url": "https://medium.com/@testuser/live-post"}}
    mock_sess.post.return_value = make_mock_post(json_data=pub_resp)
    MockSM.return_value.get_session.return_value = mock_sess

    adapter = MediumAPIAdapter()
    result = adapter.publish(PAYLOAD, mode="publish", config=CONFIG)

    assert result.status == "published"
    post_body = mock_sess.post.call_args[1]["json"]
    assert post_body["publishStatus"] == "public"


@patch(_SM)
def test_401_on_me_raises_auth_expired_error(MockSM):
    """Plan 2026-05-19-001 Unit 6: /me 401 → AuthExpiredError (not
    ExternalServiceError). Existing ``except DependencyError`` callers
    still catch this because AuthExpiredError inherits from it."""
    _, mock_sess = _mock_sm(get_resp=make_mock_get(status=401))
    MockSM.return_value.get_session.return_value = mock_sess

    adapter = MediumAPIAdapter()
    with pytest.raises(AuthExpiredError) as exc_info:
        adapter.publish(PAYLOAD, mode="draft", config=CONFIG)
    assert exc_info.value.channel == "medium"
    assert "Medium /me HTTP 401" in (exc_info.value.reason or "")
    assert isinstance(exc_info.value, DependencyError)


@patch("backlink_publisher.publishing.adapters.retry.time.sleep")
@patch(_SM)
def test_429_raises_rate_limited(MockSM, mock_sleep):
    """429 on all retry attempts → ExternalServiceError after retries exhausted."""
    _, mock_sess = _mock_sm(post_resp=make_mock_post(status=429))
    MockSM.return_value.get_session.return_value = mock_sess

    adapter = MediumAPIAdapter()
    with pytest.raises(ExternalServiceError, match="429"):
        adapter.publish(PAYLOAD, mode="draft", config=CONFIG)


@patch("backlink_publisher.publishing.adapters.retry.time.sleep")
@patch(_SM)
def test_posts_429_retried_and_recovers(MockSM, mock_sleep):
    """/posts 429 on first call triggers retry; second call succeeds."""
    _, mock_sess = _mock_sm()
    mock_sess.post.side_effect = [make_mock_post(status=429), make_mock_post()]
    MockSM.return_value.get_session.return_value = mock_sess

    adapter = MediumAPIAdapter()
    result = adapter.publish(PAYLOAD, mode="draft", config=CONFIG)
    assert result.status == "drafted"
    mock_sleep.assert_called_once()


@patch("backlink_publisher.publishing.adapters.retry.time.sleep")
@patch(_SM)
def test_posts_503_not_retried(MockSM, mock_sleep):
    """/posts 503 is NOT retried (no idempotency guarantee from Medium API)."""
    _, mock_sess = _mock_sm(post_resp=make_mock_post(status=503))
    MockSM.return_value.get_session.return_value = mock_sess

    adapter = MediumAPIAdapter()
    with pytest.raises(ExternalServiceError, match="503"):
        adapter.publish(PAYLOAD, mode="draft", config=CONFIG)
    mock_sleep.assert_not_called()


@patch("backlink_publisher.publishing.adapters.retry.time.sleep")
@patch(_SM)
def test_me_429_retried_and_recovers(MockSM, mock_sleep):
    """/me 429 on first call triggers retry; second call succeeds."""
    _, mock_sess = _mock_sm()
    mock_sess.get.side_effect = [make_mock_get(status=429), make_mock_get()]
    MockSM.return_value.get_session.return_value = mock_sess

    adapter = MediumAPIAdapter()
    result = adapter.publish(PAYLOAD, mode="draft", config=CONFIG)
    assert result.status == "drafted"
    mock_sleep.assert_called_once()


@pytest.mark.parametrize("exc_name", ["Timeout", "ConnectionError"])
@patch("backlink_publisher.publishing.adapters.retry.time.sleep")
@patch(_SM)
def test_posts_network_error_not_retried(MockSM, mock_sleep, exc_name):
    """/posts is a non-idempotent create — a Timeout/ConnectionError may mean the
    post was already created server-side, so it is NEVER retried (would duplicate).
    The create-POST is attempted exactly once; the error surfaces as
    ExternalServiceError for the resume/dedup layer to adjudicate."""
    _, mock_sess = _mock_sm()
    mock_sess.post.side_effect = [getattr(req, exc_name)("net"), make_mock_post()]
    MockSM.return_value.get_session.return_value = mock_sess

    adapter = MediumAPIAdapter()
    with pytest.raises(ExternalServiceError, match="unreachable"):
        adapter.publish(PAYLOAD, mode="draft", config=CONFIG)
    assert mock_sess.post.call_count == 1  # create POST sent exactly once
    mock_sleep.assert_not_called()


@patch("backlink_publisher.publishing.adapters.retry.time.sleep")
@patch(_SM)
def test_posts_401_not_retried(MockSM, mock_sleep):
    """Plan 2026-05-19-001 Unit 6: /posts 401 → AuthExpiredError (not
    ExternalServiceError). Still non-retryable — no sleep."""
    _, mock_sess = _mock_sm(post_resp=make_mock_post(status=401))
    MockSM.return_value.get_session.return_value = mock_sess

    adapter = MediumAPIAdapter()
    with pytest.raises(AuthExpiredError) as exc_info:
        adapter.publish(PAYLOAD, mode="draft", config=CONFIG)
    assert exc_info.value.channel == "medium"
    assert "Medium /posts HTTP 401" in (exc_info.value.reason or "")
    mock_sleep.assert_not_called()


@patch("backlink_publisher.publishing.adapters.retry.time.sleep")
@patch(_SM)
def test_user_id_not_refetched_on_posts_retry(MockSM, mock_sleep):
    """user_id from /me is cached — /me called once even on a /posts retry."""
    _, mock_sess = _mock_sm()
    mock_sess.post.side_effect = [make_mock_post(status=429), make_mock_post()]
    MockSM.return_value.get_session.return_value = mock_sess

    adapter = MediumAPIAdapter()
    adapter.publish(PAYLOAD, mode="draft", config=CONFIG)
    assert mock_sess.get.call_count == 1  # /me called exactly once


@patch(_SM)
def test_tags_truncated_to_5(MockSM):
    _, mock_sess = _mock_sm()
    MockSM.return_value.get_session.return_value = mock_sess

    adapter = MediumAPIAdapter()
    adapter.publish(PAYLOAD, mode="draft", config=CONFIG)  # payload has 6 tags

    post_body = mock_sess.post.call_args[1]["json"]
    assert len(post_body["tags"]) == 5


@patch(_SM)
def test_canonical_url_omitted_if_empty(MockSM):
    _, mock_sess = _mock_sm()
    MockSM.return_value.get_session.return_value = mock_sess

    payload = {**PAYLOAD, "seo": {"canonical_url": ""}}
    adapter = MediumAPIAdapter()
    adapter.publish(payload, mode="draft", config=CONFIG)

    post_body = mock_sess.post.call_args[1]["json"]
    assert "canonicalUrl" not in post_body


@patch(_SM)
def test_html_body_is_rendered_markdown(MockSM):
    """The POST body must contain rendered HTML, not raw markdown."""
    _, mock_sess = _mock_sm()
    MockSM.return_value.get_session.return_value = mock_sess

    adapter = MediumAPIAdapter()
    adapter.publish(PAYLOAD, mode="draft", config=CONFIG)

    post_body = mock_sess.post.call_args[1]["json"]
    assert post_body["contentFormat"] == "html"
    assert "<h1>" in post_body["content"]
    assert "https://example.com" in post_body["content"]


def test_auth_expired_propagates():
    """AuthExpiredError from SessionManager propagates directly (no masking)."""
    adapter = MediumAPIAdapter()
    with patch(_SM) as MockSM:
        MockSM.return_value.get_session.side_effect = AuthExpiredError(
            channel="medium", reason="Token expired"
        )
        with pytest.raises(AuthExpiredError):
            adapter.publish(PAYLOAD, mode="draft", config=CONFIG)


def test_external_service_error_not_dependency_for_session_failure():
    """ExternalServiceError from session setup must not be swallowed into DependencyError."""
    adapter = MediumAPIAdapter()
    with patch(_SM) as MockSM:
        MockSM.return_value.get_session.side_effect = ExternalServiceError("probe failed")
        with pytest.raises(ExternalServiceError):
            adapter.publish(PAYLOAD, mode="draft", config=CONFIG)
