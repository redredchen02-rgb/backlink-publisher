"""Cache, TTL, and stats tests for ``content_fetch``.

Extracted from ``test_content_fetch.py`` (Plan 2026-06-23-005).

See ``test_content_fetch.py`` for module-level docstring context.
"""
from __future__ import annotations

__tier__ = "e2e"
from concurrent.futures import ThreadPoolExecutor, as_completed
from io import BytesIO
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError

import pytest

from backlink_publisher.content.fetch import (
    HEAD_SCAN_BYTES,
    _CACHE,
    reset_cache,
    reset_stats,
    set_default_max_age,
    stats_snapshot,
    verify_url_has_content,
    verify_urls_batch,
)

pytestmark = pytest.mark.real_content_fetch


@pytest.fixture(autouse=True)
def _clear_cache():
    reset_cache()
    yield
    reset_cache()


@pytest.fixture(autouse=True)
def _bypass_ssrf_check(monkeypatch, request):
    if request.node.get_closest_marker("real_ssrf_check"):
        return
    monkeypatch.setattr(
        "backlink_publisher.content.fetch._check_url_for_ssrf",
        lambda _url: None,
    )


@pytest.fixture(autouse=True)
def _clear_stats_and_ttl():
    """Reset module-level TTL + stats so each test is isolated."""
    reset_stats()
    set_default_max_age(None)
    yield
    reset_stats()
    set_default_max_age(None)


def _mock_response(status: int, body: bytes) -> MagicMock:
    """Build a urlopen() return value with .getcode() and .read()."""
    resp = MagicMock()
    resp.getcode.return_value = status
    resp.read.side_effect = lambda *args: body[: args[0]] if args else body
    resp.close = MagicMock()
    return resp


# ── cache behaviour ──


def test_cache_hit_skips_second_fetch():
    body = b"<html><head><title>Cached</title></head><body>x</body></html>"
    call_count = {"n": 0}

    def _once(*args, **kwargs):
        call_count["n"] += 1
        return _mock_response(200, body)

    with patch("backlink_publisher.content.fetch._SSRF_OPENER.open", side_effect=_once):
        ok1, _, t1 = verify_url_has_content("https://example.com/cached")
        ok2, _, t2 = verify_url_has_content("https://example.com/cached")

    assert (ok1, t1) == (True, "Cached")
    assert (ok2, t2) == (True, "Cached")
    assert call_count["n"] == 1, "second call should hit cache, not network"


def test_cache_stores_failures_too():
    err = HTTPError("https://example.com/", 404, "Not Found", {}, BytesIO(b""))
    call_count = {"n": 0}

    def _raise(*args, **kwargs):
        call_count["n"] += 1
        raise err

    with patch("backlink_publisher.content.fetch._SSRF_OPENER.open", side_effect=_raise):
        verify_url_has_content("https://example.com/missing")
        verify_url_has_content("https://example.com/missing")
    assert call_count["n"] == 1, "failed result must be cached, not re-fetched"


def test_reset_cache_clears_state():
    body = b"<html><head><title>X</title></head><body>x</body></html>"
    with patch("backlink_publisher.content.fetch._SSRF_OPENER.open", return_value=_mock_response(200, body)) as mock:
        verify_url_has_content("https://example.com/")
        reset_cache()
        verify_url_has_content("https://example.com/")
    assert mock.call_count == 2, "after reset, second call must re-fetch"


# ── canonical cache key (collapses equivalent URL representations) ─────────


def test_cache_key_collapses_utm_params():
    body = b"<html><head><title>X</title></head><body>x</body></html>"
    call_count = {"n": 0}

    def _once(*args, **kwargs):
        call_count["n"] += 1
        return _mock_response(200, body)

    with patch("backlink_publisher.content.fetch._SSRF_OPENER.open", side_effect=_once):
        verify_url_has_content("https://example.com/post?utm_source=newsletter")
        ok, _, title = verify_url_has_content("https://example.com/post")

    assert (ok, title) == (True, "X")
    assert call_count["n"] == 1, "utm-only variant must hit the canonical cache key"


def test_cache_key_collapses_fragment_and_trailing_slash():
    body = b"<html><head><title>X</title></head><body>x</body></html>"
    call_count = {"n": 0}

    def _once(*args, **kwargs):
        call_count["n"] += 1
        return _mock_response(200, body)

    with patch("backlink_publisher.content.fetch._SSRF_OPENER.open", side_effect=_once):
        verify_url_has_content("https://example.com/page/#section")
        verify_url_has_content("https://example.com/page")

    assert call_count["n"] == 1, "fragment/trailing-slash variants share a cache key"


def test_batch_collapses_equivalent_urls_to_single_fetch():
    body = b"<html><head><title>X</title></head><body>x</body></html>"
    call_count = {"n": 0}

    def _once(*args, **kwargs):
        call_count["n"] += 1
        return _mock_response(200, body)

    originals = [
        "https://a.example/p?utm_source=x",
        "https://a.example/p",
        "https://a.example/p#frag",
    ]
    with patch("backlink_publisher.content.fetch._SSRF_OPENER.open", side_effect=_once):
        results = verify_urls_batch(originals)

    assert set(results) == set(originals), "every original URL must get its own entry"
    assert all(results[u][0] is True for u in originals)
    assert call_count["n"] == 1, "equivalent URLs collapse to a single fetch"


def test_cache_key_falls_back_on_malformed_url_without_raising():
    from backlink_publisher.content.fetch import _cache_key

    assert _cache_key("http://[invalid") == "http://[invalid"
    ok, reason, _ = verify_url_has_content("http://[invalid")
    assert (ok, reason) == (False, "invalid_url")


def test_concurrent_verify_writes_cache_without_corruption():
    from backlink_publisher.content.fetch import _CACHE

    body = b"<html><head><title>X</title></head><body>x</body></html>"
    urls = [f"https://host{i}.example/p" for i in range(48)]

    with patch("backlink_publisher.content.fetch._SSRF_OPENER.open", return_value=_mock_response(200, body)):
        with ThreadPoolExecutor(max_workers=12) as pool:
            futures = [pool.submit(verify_url_has_content, u) for u in urls]
            results = [f.result() for f in as_completed(futures)]

    assert all(ok for ok, _, _ in results)
    assert len(_CACHE) == len(urls), "each distinct URL cached exactly once, no lost writes"


def test_batch_larger_than_cache_cap_keeps_true_results(monkeypatch):
    monkeypatch.setattr("backlink_publisher.content.fetch._MAX_CACHE_ENTRIES", 8)
    body = b"<html><head><title>X</title></head><body>x</body></html>"
    urls = [f"https://host{i}.example/p" for i in range(20)]

    with patch("backlink_publisher.content.fetch._SSRF_OPENER.open", return_value=_mock_response(200, body)):
        results = verify_urls_batch(urls)

    assert set(results) == set(urls)
    bad = {u: r for u, r in results.items() if r != (True, None, "X")}
    assert not bad, f"evicted successes must not become network_error: {bad}"


# ═════════════════════════════════════════════════════════════════════════════
# Cache TTL
# ═════════════════════════════════════════════════════════════════════════════


class TestCacheTTL:
    def test_default_no_ttl_keeps_cache_forever(self):
        body = b"<html><head><title>X</title></head><body>x</body></html>"
        call_count = {"n": 0}

        def _once(*args, **kwargs):
            call_count["n"] += 1
            return _mock_response(200, body)

        with patch("backlink_publisher.content.fetch._SSRF_OPENER.open", side_effect=_once):
            verify_url_has_content("https://example.com/")
            import time as _time
            _time.sleep(0.05)
            verify_url_has_content("https://example.com/")
        assert call_count["n"] == 1

    def test_per_call_max_age_zero_forces_refetch(self):
        body = b"<html><head><title>X</title></head><body>x</body></html>"
        call_count = {"n": 0}

        def _each(*args, **kwargs):
            call_count["n"] += 1
            return _mock_response(200, body)

        with patch("backlink_publisher.content.fetch._SSRF_OPENER.open", side_effect=_each):
            verify_url_has_content("https://example.com/")
            verify_url_has_content("https://example.com/", max_age_seconds=0)
        assert call_count["n"] == 2, "max_age_seconds=0 must force a fresh fetch"

    def test_module_default_ttl_expires_cache(self):
        body = b"<html><head><title>X</title></head><body>x</body></html>"
        call_count = {"n": 0}

        def _each(*args, **kwargs):
            call_count["n"] += 1
            return _mock_response(200, body)

        set_default_max_age(0.05)
        with patch("backlink_publisher.content.fetch._SSRF_OPENER.open", side_effect=_each):
            verify_url_has_content("https://example.com/")
            import time as _time
            _time.sleep(0.1)
            verify_url_has_content("https://example.com/")
        assert call_count["n"] == 2

    def test_set_default_max_age_none_disables_ttl(self):
        body = b"<html><head><title>X</title></head><body>x</body></html>"
        call_count = {"n": 0}

        def _each(*args, **kwargs):
            call_count["n"] += 1
            return _mock_response(200, body)

        set_default_max_age(0.01)
        with patch("backlink_publisher.content.fetch._SSRF_OPENER.open", side_effect=_each):
            verify_url_has_content("https://example.com/")
            set_default_max_age(None)
            import time as _time
            _time.sleep(0.05)
            verify_url_has_content("https://example.com/")
        assert call_count["n"] == 1

    def test_explicit_max_age_overrides_module_default(self):
        body = b"<html><head><title>X</title></head><body>x</body></html>"
        call_count = {"n": 0}

        def _each(*args, **kwargs):
            call_count["n"] += 1
            return _mock_response(200, body)

        set_default_max_age(60.0)
        with patch("backlink_publisher.content.fetch._SSRF_OPENER.open", side_effect=_each):
            verify_url_has_content("https://example.com/")
            verify_url_has_content("https://example.com/", max_age_seconds=0)
        assert call_count["n"] == 2

    def test_batch_respects_module_ttl_for_expired_entries(self):
        body = b"<html><head><title>X</title></head><body>x</body></html>"
        call_count = {"n": 0}

        def _each(*args, **kwargs):
            call_count["n"] += 1
            return _mock_response(200, body)

        set_default_max_age(0.05)
        with patch("backlink_publisher.content.fetch._SSRF_OPENER.open", side_effect=_each):
            verify_urls_batch(["https://a.example/"])
            import time as _time
            _time.sleep(0.1)
            verify_urls_batch(["https://a.example/"])
        assert call_count["n"] == 2


# ═════════════════════════════════════════════════════════════════════════════
# Stats counters
# ═════════════════════════════════════════════════════════════════════════════


class TestStats:
    def test_stats_zero_at_start(self):
        snap = stats_snapshot()
        assert snap == {
            "cache_hits": 0,
            "cache_misses": 0,
            "fetches": 0,
            "total_latency_ms": 0,
            "reason_counts": {},
        }

    def test_stats_record_success_and_miss(self):
        body = b"<html><head><title>X</title></head><body>x</body></html>"
        with patch("backlink_publisher.content.fetch._SSRF_OPENER.open", return_value=_mock_response(200, body)):
            verify_url_has_content("https://example.com/")
        snap = stats_snapshot()
        assert snap["cache_hits"] == 0
        assert snap["cache_misses"] == 1
        assert snap["fetches"] == 1
        assert snap["reason_counts"]["ok"] == 1

    def test_stats_record_cache_hit(self):
        body = b"<html><head><title>X</title></head><body>x</body></html>"
        with patch("backlink_publisher.content.fetch._SSRF_OPENER.open", return_value=_mock_response(200, body)):
            verify_url_has_content("https://example.com/")
            verify_url_has_content("https://example.com/")
        snap = stats_snapshot()
        assert snap["cache_hits"] == 1
        assert snap["cache_misses"] == 1
        assert snap["fetches"] == 1
        assert snap["reason_counts"]["ok"] == 1

    def test_stats_record_failure_reasons(self):
        from urllib.error import HTTPError
        from io import BytesIO

        def _raise_404(*args, **kwargs):
            raise HTTPError("https://example.com/", 404, "NF", {}, BytesIO(b""))

        with patch("backlink_publisher.content.fetch._SSRF_OPENER.open", side_effect=_raise_404):
            verify_url_has_content("https://example.com/missing")
        snap = stats_snapshot()
        assert snap["reason_counts"].get("http_404") == 1
        assert "ok" not in snap["reason_counts"]

    def test_stats_records_latency_for_fetch_not_hit(self):
        body = b"<html><head><title>X</title></head><body>x</body></html>"
        with patch("backlink_publisher.content.fetch._SSRF_OPENER.open", return_value=_mock_response(200, body)):
            verify_url_has_content("https://example.com/")
            verify_url_has_content("https://example.com/")
        snap = stats_snapshot()
        assert snap["total_latency_ms"] >= 0
        assert isinstance(snap["total_latency_ms"], int)

    def test_stats_reset_clears_counters(self):
        body = b"<html><head><title>X</title></head><body>x</body></html>"
        with patch("backlink_publisher.content.fetch._SSRF_OPENER.open", return_value=_mock_response(200, body)):
            verify_url_has_content("https://example.com/")
        reset_stats()
        snap = stats_snapshot()
        assert snap["fetches"] == 0
        assert snap["cache_misses"] == 0
        assert snap["reason_counts"] == {}

    def test_stats_snapshot_is_independent_copy(self):
        body = b"<html><head><title>X</title></head><body>x</body></html>"
        with patch("backlink_publisher.content.fetch._SSRF_OPENER.open", return_value=_mock_response(200, body)):
            verify_url_has_content("https://example.com/")
        snap1 = stats_snapshot()
        snap1["fetches"] = 999
        snap1["reason_counts"]["ok"] = 42
        snap2 = stats_snapshot()
        assert snap2["fetches"] == 1
        assert snap2["reason_counts"]["ok"] == 1

    def test_stats_invalid_url_counted_as_invalid_url(self):
        verify_url_has_content("not-a-url")
        snap = stats_snapshot()
        assert snap["reason_counts"].get("invalid_url") == 1
        assert snap["fetches"] == 0
