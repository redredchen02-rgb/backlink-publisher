"""Unit tests for module-level helpers extracted from MediumAPIAdapter.

Covers _fetch_medium_user_id and _create_medium_post (session-based).
All tests run without I/O — HTTP calls are mocked via patch.
"""
from __future__ import annotations

__tier__ = "integration"
from unittest.mock import MagicMock, patch

import pytest
import requests

from backlink_publisher._util.errors import (
    AuthExpiredError,
    ExternalServiceError,
)
from backlink_publisher.publishing.adapters.medium_api import (
    _create_medium_post,
    _fetch_medium_user_id,
)

_HEADERS = {"Authorization": "Bearer tok", "Content-Type": "application/json"}
_BODY = {"title": "T", "contentFormat": "html", "content": "<p>hi</p>", "tags": [], "publishStatus": "draft"}


def _make_session(get_resp=None, post_resp=None) -> MagicMock:
    session = MagicMock(name="session")
    if get_resp is not None:
        session.get.return_value = get_resp
    if post_resp is not None:
        session.post.return_value = post_resp
    return session


def _make_resp(status: int, json_data=None, text="") -> MagicMock:
    r = MagicMock()
    r.status_code = status
    r.ok = status < 400
    r.json.return_value = json_data or {}
    r.text = text
    return r


# ── _fetch_medium_user_id ───────────────────────────────────────────────────


class TestFetchMediumUserId:
    def test_happy_path_returns_user_id(self):
        resp = _make_resp(200, {"data": {"id": "user123"}})
        session = _make_session(get_resp=resp)
        uid = _fetch_medium_user_id(session)
        assert uid == "user123"

    def test_401_raises_auth_expired(self):
        resp = _make_resp(401)
        session = _make_session(get_resp=resp)
        with pytest.raises(AuthExpiredError, match="medium"):
            _fetch_medium_user_id(session)

    def test_500_raises_external_service_error(self):
        resp = _make_resp(500)
        session = _make_session(get_resp=resp)
        with pytest.raises(ExternalServiceError, match="/me returned HTTP 500"):
            _fetch_medium_user_id(session)

    def test_connection_error_raises_external_service_error(self):
        session = MagicMock(name="session")
        session.get.side_effect = requests.ConnectionError("no route")
        with pytest.raises(ExternalServiceError, match="unreachable"):
            _fetch_medium_user_id(session)

    def test_429_retried_then_succeeds(self):
        rate_resp = _make_resp(429)
        ok_resp = _make_resp(200, {"data": {"id": "u99"}})
        session = MagicMock(name="session")
        session.get.side_effect = [rate_resp, ok_resp]
        with patch("backlink_publisher.publishing.adapters.retry.time.sleep"):
            uid = _fetch_medium_user_id(session)
        assert uid == "u99"


# ── _create_medium_post ─────────────────────────────────────────────────────


class TestCreateMediumPost:
    def test_happy_201_returns_response(self):
        resp = _make_resp(201, {"data": {"url": "https://medium.com/@u/p"}})
        session = _make_session(post_resp=resp)
        result = _create_medium_post("u1", session, _BODY)
        assert result.status_code == 201

    def test_401_raises_auth_expired(self):
        resp = _make_resp(401)
        session = _make_session(post_resp=resp)
        with pytest.raises(AuthExpiredError, match="medium"):
            _create_medium_post("u1", session, _BODY)

    def test_429_exhausts_retries_and_raises(self):
        resp = _make_resp(429)
        session = _make_session(post_resp=resp)
        with patch("backlink_publisher.publishing.adapters.retry.time.sleep"):
            with pytest.raises(ExternalServiceError, match="429"):
                _create_medium_post("u1", session, _BODY)

    def test_503_raises_not_retried(self):
        resp = _make_resp(503, text="down")
        session = _make_session(post_resp=resp)
        with patch("backlink_publisher.publishing.adapters.retry.time.sleep") as mock_sleep:
            with pytest.raises(ExternalServiceError, match="/posts returned HTTP 503"):
                _create_medium_post("u1", session, _BODY)
        mock_sleep.assert_not_called()

    def test_network_error_not_retried(self):
        session = MagicMock(name="session")
        session.post.side_effect = requests.ConnectionError("reset")
        with patch("backlink_publisher.publishing.adapters.retry.time.sleep") as mock_sleep:
            with pytest.raises(ExternalServiceError, match="unreachable"):
                _create_medium_post("u1", session, _BODY)
        mock_sleep.assert_not_called()

    def test_429_retried_then_succeeds(self):
        rate_resp = _make_resp(429)
        ok_resp = _make_resp(201, {"data": {"url": "https://medium.com/@u/post"}})
        session = MagicMock(name="session")
        session.post.side_effect = [rate_resp, ok_resp]
        with patch("backlink_publisher.publishing.adapters.retry.time.sleep"):
            result = _create_medium_post("u1", session, _BODY)
        assert result.status_code == 201
