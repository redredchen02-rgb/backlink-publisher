"""notes.io form-POST adapter — Plan 2026-06-02-002 Unit 2.

Covers publish happy/draft paths, missing content, redirect failure,
anti-bot challenge propagation, network error, and the fire-and-forget
link verification hook. All HTTP is mocked — no real network.
"""
from __future__ import annotations

__tier__ = "unit"
from unittest import mock

import pytest

from backlink_publisher._util.errors import AntiBotChallengeError, ExternalServiceError
from backlink_publisher.config import Config
from backlink_publisher.publishing.adapters.notesio_api import NotesioFormPostAdapter

_ADAPTER = "backlink_publisher.publishing.adapters.notesio_api"

_PAYLOAD = {
    "id": "notesio-1",
    "title": "Hello notes.io",
    "content_markdown": "# Hi\n\nA [link](https://example.com) here.\n",
    "target_url": "https://example.com",
    "main_domain": "https://example.com/",
}


def _mock_response(*, status=200, text="", url="https://notes.io/"):
    resp = mock.MagicMock()
    resp.status_code = status
    resp.text = text
    resp.url = url
    resp.headers = {}
    return resp


# ── happy paths ────────────────────────────────────────────────────────────


def test_publish_happy_returns_published_url():
    submit_resp = _mock_response(url="https://notes.io/abc123")

    with mock.patch(
        f"{_ADAPTER}.submit_form", return_value=submit_resp
    ) as mock_submit, mock.patch(
        f"{_ADAPTER}.attach_link_verification",
        return_value={"link_attr_verification": {"ok": True}},
    ):
        res = NotesioFormPostAdapter().publish(_PAYLOAD, mode="publish", config=Config())

    assert res.status == "published"
    assert res.published_url == "https://notes.io/abc123"
    assert res.adapter == "notesio-form-post"
    assert res.platform == "notesio"
    assert res._provider_meta["link_attr_verification"]["ok"] is True

    call_args = mock_submit.call_args
    assert call_args.args[0] == "https://notes.io/"
    data = call_args.args[1]
    assert "text" in data
    assert "# Hello notes.io" in data["text"]
    assert data["token"] == ""


def test_publish_draft_mode_returns_draft_url():
    submit_resp = _mock_response(url="https://notes.io/draft456")

    with mock.patch(
        f"{_ADAPTER}.submit_form", return_value=submit_resp
    ), mock.patch(
        f"{_ADAPTER}.attach_link_verification",
    ) as mock_verify:
        res = NotesioFormPostAdapter().publish(_PAYLOAD, mode="draft", config=Config())

    assert res.status == "drafted"
    assert res.draft_url == "https://notes.io/draft456"
    assert res.published_url == ""
    assert res._provider_meta is None
    mock_verify.assert_not_called()


def test_publish_without_title_no_heading_prefix():
    submit_resp = _mock_response(url="https://notes.io/notitle")
    payload_no_title = dict(_PAYLOAD, title="")

    with mock.patch(f"{_ADAPTER}.submit_form", return_value=submit_resp) as mock_submit:
        NotesioFormPostAdapter().publish(payload_no_title, mode="publish", config=Config())

    sent_body = mock_submit.call_args.args[1]["text"]
    assert not sent_body.startswith("# \n"), "empty title must not add '# ' prefix"
    assert "# Hi" in sent_body


# ── error paths ────────────────────────────────────────────────────────────


def test_empty_content_raises_external_service_error():
    payload_empty = dict(_PAYLOAD, content_markdown="")
    with pytest.raises(ExternalServiceError, match="has no content_markdown"):
        NotesioFormPostAdapter().publish(payload_empty, mode="publish", config=Config())


def test_no_redirect_raises_external_service_error():
    submit_resp = _mock_response(url="https://notes.io/")

    with mock.patch(f"{_ADAPTER}.submit_form", return_value=submit_resp):
        with pytest.raises(ExternalServiceError, match="did not redirect"):
            NotesioFormPostAdapter().publish(_PAYLOAD, mode="publish", config=Config())


def test_anti_bot_challenge_on_submit_propagates():
    with mock.patch(
        f"{_ADAPTER}.submit_form",
        side_effect=AntiBotChallengeError("bot challenge on POST notes.io"),
    ):
        with pytest.raises(AntiBotChallengeError):
            NotesioFormPostAdapter().publish(_PAYLOAD, mode="publish", config=Config())


def test_network_error_on_submit_propagates():
    with mock.patch(
        f"{_ADAPTER}.submit_form",
        side_effect=ExternalServiceError("HTTP 503 from notes.io"),
    ):
        with pytest.raises(ExternalServiceError):
            NotesioFormPostAdapter().publish(_PAYLOAD, mode="publish", config=Config())


# ── credential / setup ─────────────────────────────────────────────────────


def test_verify_adapter_setup_offline_is_ok():
    """verify_adapter_setup(offline) must not raise — no credential needed."""
    from backlink_publisher.publishing.adapters import verify_adapter_setup

    verify_adapter_setup("notesio", Config(), mode="offline")
