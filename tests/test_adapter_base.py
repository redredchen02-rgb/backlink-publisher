"""Tests for adapter base functionality (Stage 1 enhanced)."""
__tier__ = "unit"

from backlink_publisher.publishing.adapters.base import (
    AdapterResult,
    classify_http_status,
    PermanentError,
    TransientError,
)


def test_adapter_result_defaults():
    r = AdapterResult(status="drafted", adapter="blogger-api", platform="blogger")
    assert r.draft_url == ""
    assert r.published_url == ""
    assert r.error is None
    assert r._dry_run is False


def test_adapter_result_failed_allows_empty_urls():
    r = AdapterResult(
        status="failed",
        adapter="medium-api",
        platform="medium",
        draft_url="",
        published_url="",
        error="something went wrong",
    )
    assert r.error == "something went wrong"
    assert r.draft_url == ""


def test_to_publish_output_shape():
    r = AdapterResult(
        status="drafted",
        adapter="blogger-api",
        platform="blogger",
        draft_url="https://blog.example.com/p/123",
    )
    row = {"id": "abc123", "title": "My Post"}
    out = r.to_publish_output(row, "2026-05-11T00:00:00+00:00")
    assert out["id"] == "abc123"
    assert out["title"] == "My Post"
    assert out["status"] == "drafted"
    assert out["draft_url"] == "https://blog.example.com/p/123"
    assert out["adapter"] == "blogger-api"
    assert out["error"] is None


def test_to_publish_output_emits_link_attr_verification_when_present():
    """Happy path: an attached link-attr verdict is surfaced in the output."""
    verdict = {
        "verification": "ok",
        "total_anchors": 12,
        "nofollow_anchors": 0,
        "nofollow_detected": False,
        "nofollow_reason": None,
    }
    r = AdapterResult(
        status="published",
        adapter="txtfyi-form",
        platform="txtfyi",
        published_url="https://txt.fyi/abc",
        _provider_meta={"link_attr_verification": verdict},
    )
    out = r.to_publish_output({"id": "x1"}, "2026-05-25T00:00:00+00:00")
    assert out["link_attr_verification"] == verdict


def test_to_publish_output_emits_skipped_verdict():
    """A 'skipped' verdict is still surfaced — the operator needs to see skips."""
    verdict = {"verification": "skipped", "reason": "non-200"}
    r = AdapterResult(
        status="published",
        adapter="livejournal-api",
        platform="livejournal",
        published_url="https://x.livejournal.com/1",
        _provider_meta={"link_attr_verification": verdict},
    )
    out = r.to_publish_output({"id": "x2"}, "2026-05-25T00:00:00+00:00")
    assert out["link_attr_verification"] == verdict


def test_to_publish_output_omits_key_when_provider_meta_none():
    """Draft mode / non-verifying adapters: output shape is unchanged."""
    r = AdapterResult(
        status="drafted", adapter="blogger-api", platform="blogger",
        draft_url="https://blog.example.com/p/1",
    )
    out = r.to_publish_output({"id": "x3"}, "2026-05-25T00:00:00+00:00")
    assert "link_attr_verification" not in out


def test_to_publish_output_omits_key_when_meta_lacks_verification():
    """_provider_meta present but without the verification key → key omitted."""
    r = AdapterResult(
        status="published", adapter="medium-api", platform="medium",
        published_url="https://medium.com/p/1",
        _provider_meta={"something_else": 1},
    )
    out = r.to_publish_output({"id": "x4"}, "2026-05-25T00:00:00+00:00")
    assert "link_attr_verification" not in out


# ---------------------------------------------------------------------------
# TransientError / PermanentError classification (Stage 1)
# ---------------------------------------------------------------------------


def test_transient_error_is_subclass_of_exception():
    """TransientError is a proper exception."""
    exc = TransientError("test transient error")
    assert isinstance(exc, Exception)


def test_permanent_error_is_subclass_of_exception():
    """PermanentError is a proper exception."""
    exc = PermanentError("test permanent error")
    assert isinstance(exc, Exception)


def test_classify_http_status_transient():
    """HTTP status codes 429 and 502-504 should be classified as TransientError."""
    assert classify_http_status(429) == TransientError
    assert classify_http_status(502) == TransientError
    assert classify_http_status(503) == TransientError
    assert classify_http_status(504) == TransientError
    assert classify_http_status(500) == TransientError
    assert classify_http_status(501) == TransientError
    assert classify_http_status(599) == TransientError


def test_classify_http_status_permanent():
    """HTTP status codes 401, 403, 404 should be classified as PermanentError."""
    assert classify_http_status(401) == PermanentError
    assert classify_http_status(403) == PermanentError
    assert classify_http_status(404) == PermanentError


def test_classify_http_status_other():
    """Other HTTP status codes return None (not classified)."""
    assert classify_http_status(200) is None
    assert classify_http_status(201) is None
    assert classify_http_status(301) is None
    assert classify_http_status(302) is None
