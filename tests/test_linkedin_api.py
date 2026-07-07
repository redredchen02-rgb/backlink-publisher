"""LinkedIn adapter tests — P1#6 post-URN-from-header regression.

POST /v2/posts returns 201 with an EMPTY body; the created post URN is in
the ``x-restli-id`` response header. The adapter previously read
resp.json()["id"] and raised on every success.
"""
from __future__ import annotations

__tier__ = "unit"
import json
import os
from unittest.mock import MagicMock, patch

import pytest

from backlink_publisher._util.errors import DependencyError, ExternalServiceError
from backlink_publisher.publishing.adapters.base import AdapterResult
from backlink_publisher.publishing.adapters.linkedin_api import LinkedInAPIAdapter


@pytest.fixture
def config(tmp_path):
    cfg = MagicMock()
    cfg.token_path.return_value = tmp_path / "linkedin-token.json"
    cfg.config_dir = tmp_path
    return cfg


@pytest.fixture
def config_with_token(config):
    config.token_path.return_value.write_text(
        json.dumps({"token": "tok123", "person_id": "urn:li:person:abc"})
    )
    os.chmod(config.token_path.return_value, 0o600)
    return config


def _payload():
    return {"id": "a1", "title": "Hi", "content_markdown": "body", "tags": []}


def _resp(status=201, headers=None, body=None):
    resp = MagicMock()
    resp.status_code = status
    resp.headers = headers or {}
    resp.text = ""
    if body is None:
        resp.json.side_effect = ValueError("empty body")
    else:
        resp.json.return_value = body
    return resp


def test_post_url_built_from_x_restli_id_header(config_with_token):
    urn = "urn:li:share:7890123"
    resp = _resp(status=201, headers={"x-restli-id": urn}, body=None)
    with patch(
        "backlink_publisher.publishing.adapters.linkedin_api.http_client.post",
        return_value=resp,
    ):
        result = LinkedInAPIAdapter().publish(_payload(), "publish", config_with_token)
    assert isinstance(result, AdapterResult)
    assert result.published_url == f"https://www.linkedin.com/feed/update/{urn}"


def test_missing_urn_header_and_body_raises(config_with_token):
    resp = _resp(status=201, headers={}, body=None)
    with patch(
        "backlink_publisher.publishing.adapters.linkedin_api.http_client.post",
        return_value=resp,
    ):
        with pytest.raises(ExternalServiceError):
            LinkedInAPIAdapter().publish(_payload(), "publish", config_with_token)


def test_missing_token_raises_dependency_error(config):
    with pytest.raises(DependencyError):
        LinkedInAPIAdapter().publish(_payload(), "publish", config)


def test_draft_mode_reports_drafted(config_with_token):
    """P1#13: draft mode sets lifecycleState=DRAFT, so the result must
    report 'drafted', not 'published'."""
    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None, **kwargs):
        captured["body"] = json
        return _resp(status=201, headers={"x-restli-id": "urn:li:share:1"}, body=None)

    with patch(
        "backlink_publisher.publishing.adapters.linkedin_api.http_client.post",
        side_effect=fake_post,
    ):
        result = LinkedInAPIAdapter().publish(_payload(), "draft", config_with_token)
    assert captured["body"]["lifecycleState"] == "DRAFT"
    assert result.status == "drafted"


# ─── Unit 3 (2026-07-07-003): unexpected internal exceptions must propagate ───
#
# docs/solutions/correctness/adapter-silent-exceptions-resolution.md's
# audited pattern for adapters is "wrap-and-propagate, never swallow into a
# fake success". linkedin_api.py's `except Exception as exc:` around the
# retry_transient_call(execute, ...) call (~line 194) already does this —
# this test locks in that an unexpected internal failure (e.g. the HTTP
# client raising something that isn't already ExternalServiceError/
# DependencyError) is never turned into a reported "published"/"drafted"
# result; it propagates as ExternalServiceError, correctly classified so the
# caller sees a real failure instead of silently-swallowed success.
def test_unexpected_internal_exception_is_classified_as_external_service_error(config_with_token):
    with patch(
        "backlink_publisher.publishing.adapters.linkedin_api.http_client.post",
        side_effect=RuntimeError("connection reset by peer"),
    ):
        with pytest.raises(ExternalServiceError, match="connection reset by peer"):
            LinkedInAPIAdapter().publish(_payload(), "publish", config_with_token)
