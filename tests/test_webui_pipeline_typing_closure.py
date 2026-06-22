"""Unit 8 — WebUI pipeline payload round-trip and error surfacing (plan 2026-06-04-004).

Typed error prefix present; error messages bounded and HTML-escaped; session
guard prevents KeyError on missing session keys.
"""
from __future__ import annotations

__tier__ = "integration"

import json
from unittest import mock

import pytest
import webui


@pytest.fixture
def client(disable_csrf):
    return webui.app.test_client()


def _publish_envelope(error_class: str, message: str, exit_code: int = 1) -> str:
    """Produce a properly-formatted __BLP_ERR__ envelope for testing."""
    from backlink_publisher._util.error_envelope import ErrorEnvelope
    _BANNER = (
        "[publish-backlinks] effective config:\n"
        "  config:    /tmp/cfg\n"
        "  platforms: blogger\n"
    )
    return _BANNER + ErrorEnvelope(error_class, exit_code, message).serialize() + "\n"


# ── Typed publish error prefix ────────────────────────────────────────────────

def test_typed_payload_validation_error_shows_prefix(client):
    """PayloadValidationError envelope → rendered HTML contains '[PayloadValidationError]' prefix."""
    stderr = _publish_envelope("PayloadValidationError", "url_mode='D' not in valid set")

    with mock.patch(
        "backlink_publisher.sdk.api.run_pipe_capture",
        side_effect=Exception(stderr),
    ):
        with client.session_transaction() as sess:
            sess["validated"] = [{"main_domain": "example.com", "platform": "blogger",
                                   "language": "zh-CN"}]

        resp = client.post("/ce:publish", data={
            "plans": json.dumps([{"main_domain": "example.com", "platform": "blogger",
                                   "language": "zh-CN", "content_markdown": "body"}]),
        })
    body = resp.data.decode()
    assert "[PayloadValidationError]" in body, (
        f"Typed error prefix missing from rendered page; got: {body[:500]}"
    )


# ── Plain non-envelope stderr (QUARANTINE) ───────────────────────────────────

def test_plain_stderr_shows_no_typed_prefix(client):
    """Plain (non-envelope) stderr → the specific plain error text in the page
    is NOT wrapped with a [ClassName] bracket prefix immediately before it.

    Note: the page may contain '[PayloadValidationError]' elsewhere (e.g. history
    entries from previous tests). This test specifically checks that the injected
    plain message itself doesn't get a bracket prefix.
    """
    marker = "PLAIN_STDERR_TEST_MARKER_XQ9"  # unique sentinel
    stderr = f"something went wrong: {marker}"

    with mock.patch(
        "backlink_publisher.sdk.api.run_pipe_capture",
        side_effect=Exception(stderr),
    ):
        with client.session_transaction() as sess:
            sess["validated"] = [{"main_domain": "example.com", "platform": "blogger",
                                   "language": "zh-CN"}]

        resp = client.post("/ce:publish", data={
            "plans": json.dumps([{"main_domain": "example.com", "platform": "blogger",
                                   "language": "zh-CN", "content_markdown": "body"}]),
        })
    body = resp.data.decode()
    # If the marker appears in the page, check its context
    if marker in body:
        import re
        idx = body.index(marker)
        # Look at ~100 chars before the marker for a bracket-typed prefix
        context = body[max(0, idx - 100):idx]
        assert not re.search(r'\[\w+Error\]', context), (
            f"Plain error should not have [ClassName] prefix, context: {context!r}"
        )


# ── Error length bound ────────────────────────────────────────────────────────

def test_oversized_error_message_is_truncated(client):
    """5000-char error → rendered publish_error ≤ 4000 chars (+ truncation marker)."""
    long_stderr = "x" * 5000

    with mock.patch(
        "backlink_publisher.sdk.api.run_pipe_capture",
        side_effect=Exception(long_stderr),
    ):
        with client.session_transaction() as sess:
            sess["validated"] = [{"main_domain": "example.com", "platform": "blogger",
                                   "language": "zh-CN"}]

        resp = client.post("/ce:publish", data={
            "plans": json.dumps([{"main_domain": "example.com", "platform": "blogger",
                                   "language": "zh-CN", "content_markdown": "body"}]),
        })
    body = resp.data.decode()
    # Count consecutive x chars in body (rough proxy for error display length)
    import re
    chunks = re.findall(r"x{10,}", body)
    if chunks:
        max_chunk = max(len(c) for c in chunks)
        assert max_chunk <= 4100, f"Error message chunk too long: {max_chunk} chars"


# ── HTML escaping ─────────────────────────────────────────────────────────────

def test_error_message_html_escaped(client):
    """Error containing <script>alert(1)</script> → HTML has &lt;script&gt;, NOT bare tag."""
    xss_stderr = "error: <script>alert(1)</script>"

    with mock.patch(
        "backlink_publisher.sdk.api.run_pipe_capture",
        side_effect=Exception(xss_stderr),
    ):
        with client.session_transaction() as sess:
            sess["validated"] = [{"main_domain": "example.com", "platform": "blogger",
                                   "language": "zh-CN"}]

        resp = client.post("/ce:publish", data={
            "plans": json.dumps([{"main_domain": "example.com", "platform": "blogger",
                                   "language": "zh-CN", "content_markdown": "body"}]),
        })
    body = resp.data.decode()
    # Bare script tag must NOT appear — Jinja autoescape must be active
    assert "<script>alert(1)</script>" not in body, (
        "XSS: bare <script> tag found in rendered error — autoescape failure"
    )
    # The escaped form should be present (or the message truncated/redacted)
    # Accept either escaped form or no script mention at all
    if "script" in body.lower():
        assert "&lt;script&gt;" in body or "&#60;script&#62;" in body, (
            "Script tag must be HTML-escaped if present"
        )


# ── Session guard: no KeyError on missing plans ───────────────────────────────

def test_validate_without_session_plans_no_keyerror(client):
    """/ce:validate without session['plans'] → redirect or 4xx, not KeyError/500."""
    resp = client.post("/ce:validate", data={"platform": "blogger", "language": "zh-CN"})
    # Any status except 500 is acceptable
    assert resp.status_code != 500, (
        f"/ce:validate without session plans raised 500 (possible KeyError)"
    )


def test_publish_without_session_validated_no_keyerror(client):
    """/ce:publish without session['validated'] → redirect or 4xx, not KeyError/500."""
    resp = client.post("/ce:publish", data={
        "plans": json.dumps([{"main_domain": "example.com"}]),
    })
    assert resp.status_code != 500, (
        f"/ce:publish without session validated raised 500 (possible KeyError)"
    )
