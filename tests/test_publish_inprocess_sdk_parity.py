"""U5a-2 (plan 2026-06-22-001): PipelineAPI.publish()/publish_seed() now run the
publish loop IN-PROCESS for API-tier platforms instead of shelling out to the
``publish-backlinks`` CLI. These tests pin that the in-process ``PipeResult`` is
byte-for-byte consistent with the CLI golden contract (``test_publish_engine_
golden.py`` drives the same scenarios through ``main()``), plus the three U5a-2
invariants the subprocess path could not express: browser-tier routing stays on
the subprocess, a process-level lock serializes concurrent in-process runs, and
leases are released in try/finally (no atexit leak).
"""

from __future__ import annotations

__tier__ = "unit"

import json
import threading
import time
from unittest.mock import patch

import pytest

from backlink_publisher._util.errors import (
    AuthExpiredError,
    DependencyError,
    ExternalServiceError,
)
from backlink_publisher.linkcheck.verify import VerificationResult
from backlink_publisher.publishing.adapters.base import AdapterResult
from backlink_publisher.sdk.api import PipelineAPI

# ── isolation ──────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _sandbox(tmp_path, monkeypatch):
    """Point config/cache (and thus events.db + checkpoint cache) at tmp, mock the
    publish-time reachability re-check pass, mock verification pass, and isolate
    the channel-status store the auth-abort side effect writes to."""
    cfg = tmp_path / "config"
    cache = tmp_path / "cache"
    cfg.mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(cfg))
    monkeypatch.setenv("BACKLINK_PUBLISHER_CACHE_DIR", str(cache))

    from webui_store.channel_status import channel_status_store as _store
    monkeypatch.setattr(_store, "path", cfg / "channel-status.json")

    with patch(
        "backlink_publisher.cli.publish._publish_helpers._check_row_reachability",
        return_value=(True, None),
    ), patch(
        "backlink_publisher.cli.publish._publish_helpers.verify_published",
        return_value=VerificationResult(ok=True, reason=""),
    ), patch(
        "backlink_publisher.cli.publish._publish_helpers._medium_throttle_sleep",
    ):
        yield


# ── payload / adapter result builders (mirror test_publish_engine_golden) ────


def _payload(row_id="char-1", platform="blogger"):
    return {
        "id": row_id, "platform": platform, "language": "en", "publish_mode": "draft",
        "target_url": "https://example.com/article", "main_domain": "https://example.com",
        "url_mode": "A", "title": "Test Article", "slug": "test-article",
        "excerpt": "An excerpt.", "tags": ["tag1"],
        "content_markdown": "Content about https://example.com page.",
        "links": [
            {"url": "https://example.com", "anchor": "Example", "kind": "main_domain", "required": True},
            {"url": "https://example.com/article", "anchor": "Article", "kind": "target", "required": True},
            {"url": "https://wikipedia.org", "anchor": "Wiki", "kind": "supporting", "required": False},
            {"url": "https://mdn.dev", "anchor": "MDN", "kind": "supporting", "required": False},
            {"url": "https://stackoverflow.com", "anchor": "SO", "kind": "supporting", "required": False},
            {"url": "https://github.com", "anchor": "GH", "kind": "supporting", "required": False},
        ],
        "seo": {"title": "T", "description": "D", "canonical_url": "https://example.com/article"},
    }


def _ok_result(platform="blogger"):
    return AdapterResult(
        status="drafted", adapter=f"{platform}-api", platform=platform,
        draft_url=f"https://{platform}.example.com/p/1",
    )


def _seed(n_rows, platform="blogger"):
    return "\n".join(json.dumps(_payload(row_id=f"r{i}", platform=platform)) for i in range(n_rows))


def _publish(side_effect, n_rows, *, platform="blogger", mode="draft", tier_1=False):
    """Drive PipelineAPI().publish() in-process with a patched adapter seam."""
    with patch("backlink_publisher.cli.publish_backlinks.verify_adapter_setup"), \
         patch("backlink_publisher.cli.publish_backlinks.adapter_publish") as mock_pub:
        mock_pub.side_effect = side_effect
        return PipelineAPI().publish(_seed(n_rows, platform), platform, mode, tier_1=tier_1)


# ── golden parity: exit code + stdout-rows contract via the SDK ──────────────


def test_inprocess_single_success_exit0():
    res = _publish([_ok_result()], 1)
    assert res.success is True and res.exit_code == 0
    assert len(res.rows) == 1 and res.rows[0]["status"] == "drafted"
    assert res.rows[0]["error"] is None


def test_inprocess_two_successes_exit0():
    res = _publish([_ok_result(), _ok_result()], 2)
    assert res.success is True and res.exit_code == 0
    assert len(res.rows) == 2 and all(r["status"] == "drafted" for r in res.rows)


def test_inprocess_partial_external_error_exit4_carries_only_success():
    res = _publish([_ok_result(), ExternalServiceError("svc down")], 2)
    assert res.success is False and res.exit_code == 4
    assert res.error_class == "ExternalServiceError"
    assert len(res.rows) == 1 and res.rows[0]["error"] is None, "only the success row on stdout"


def test_inprocess_single_external_error_exit4_empty_stdout():
    res = _publish([ExternalServiceError("svc down")], 1)
    assert res.success is False and res.exit_code == 4
    assert res.rows == []


def test_inprocess_dependency_error_aborts_exit3_empty_stdout():
    res = _publish([DependencyError("missing config")], 1)
    assert res.success is False and res.exit_code == 3
    assert res.error_class == "DependencyError"
    assert res.rows == []


def test_inprocess_ok_then_dependency_aborts_before_writing_success():
    res = _publish([_ok_result(), DependencyError("missing config")], 2)
    assert res.success is False and res.exit_code == 3
    assert res.rows == [], "abort skips the epilogue -> row1 success not emitted"


def test_inprocess_auth_expired_aborts_exit3():
    res = _publish([AuthExpiredError(channel="blogger", reason="HTTP 401")], 1)
    assert res.success is False and res.exit_code == 3
    assert res.error_class == "AuthExpiredError"
    assert res.rows == []


def test_inprocess_external_error_gives_generic_envelope_message():
    """An ExternalServiceError continue-path failure surfaces the GENERIC epilogue
    envelope message (``N payload(s) failed to publish``), NOT the raw adapter
    text — identical to the old subprocess path (the raw text lives on the failed
    row, which the epilogue does not write to stdout). Pinned so the in-process
    switch can't silently start leaking raw per-row text into result.error."""
    res = _publish([ExternalServiceError("Blogger API rate-limited (HTTP 429)")], 1)
    assert res.success is False and res.exit_code == 4
    assert res.error == "1 payload(s) failed to publish"


def test_inprocess_dependency_abort_preserves_raw_error_text():
    """The abort family (auth/dependency) is the path that DOES preserve the raw
    exception message in result.error — this is the ``.error 保原文`` contract the
    scheduler's ``"429" in result.error`` backoff relies on. main() raises
    ``emit_error(state.dependency_error, exit_code=3)`` with the raw text; the
    in-process mapper carries the same ``state.dependency_error`` verbatim."""
    res = _publish([DependencyError("provider rate limited: HTTP 429 Too Many Requests")], 1)
    assert res.success is False and res.exit_code == 3
    assert "429" in (res.error or "") and "Too Many Requests" in (res.error or "")


# ── pre-loop gate parity ─────────────────────────────────────────────────────


def test_inprocess_unsupported_platform_exit2():
    res = PipelineAPI().publish(_seed(1, "blogger"), "not-a-real-platform", "draft")
    assert res.success is False and res.exit_code == 2
    assert res.error_class == "InputValidationError"


def test_inprocess_verify_setup_dependency_error_exit3():
    with patch(
        "backlink_publisher.cli.publish_backlinks.verify_adapter_setup",
        side_effect=DependencyError("blogger: missing OAuth token"),
    ), patch("backlink_publisher.cli.publish_backlinks.adapter_publish") as mock_pub:
        mock_pub.side_effect = [_ok_result()]
        res = PipelineAPI().publish(_seed(1, "blogger"), "blogger", "draft")
    assert res.success is False and res.exit_code == 3
    assert res.error_class == "DependencyError"
    assert mock_pub.call_count == 0, "verify gate fires before any dispatch"


def test_inprocess_json_array_input_exit2_parity():
    """A top-level JSON array (the shape scheduler builds via json.dumps([seed]))
    must produce the SAME exit-2 InputValidationError the CLI's strict read_jsonl
    did — not a silent exit-0 no-op. Pins parity with the old subprocess path,
    which rejects ``[{...}]`` with 'expected a JSON object, got list'."""
    res = PipelineAPI().publish_seed('[{"target_url":"https://x/y","platform":"blogger"}]')
    assert res.success is False and res.exit_code == 2
    assert res.error_class == "InputValidationError"
    assert "expected a JSON object, got list" in (res.error or "")


def test_inprocess_empty_input_exit2_parity():
    """Empty publish input → exit-2 'empty input' (read_jsonl strict parity).
    e.g. _keepalive_engine.publish('') when there is nothing to publish."""
    res = PipelineAPI().publish("", "blogger", "draft")
    assert res.success is False and res.exit_code == 2
    assert res.error_class == "InputValidationError"
    assert "empty input" in (res.error or "")


def test_inprocess_tier1_all_filtered_returns_empty_success():
    # notion is dofollow=False -> tier-1 filter drops it -> clean exit 0, empty.
    with patch("backlink_publisher.cli.publish_backlinks.adapter_publish") as mock_pub:
        res = PipelineAPI().publish(_seed(1, "notion"), "notion", "draft", tier_1=True)
    assert res.success is True and res.exit_code == 0 and res.rows == []
    assert mock_pub.call_count == 0


# ── publish_seed (self-describing rows) ──────────────────────────────────────


def test_publish_seed_inprocess_success():
    with patch("backlink_publisher.cli.publish_backlinks.verify_adapter_setup"), \
         patch("backlink_publisher.cli.publish_backlinks.adapter_publish") as mock_pub:
        mock_pub.side_effect = [_ok_result()]
        res = PipelineAPI().publish_seed(_seed(1, "blogger"))
    assert res.success is True and res.exit_code == 0
    assert len(res.rows) == 1 and res.rows[0]["status"] == "drafted"


# ── browser-tier routing: stays on the subprocess ───────────────────────────


def test_browser_tier_publish_routes_to_subprocess():
    captured = {"returncode": 0, "stdout": '{"published_url":"https://m/p","status":"drafted"}', "stderr": ""}
    with patch("backlink_publisher.sdk.api.run_pipe_capture", return_value=captured) as mock_rp:
        res = PipelineAPI().publish(_seed(1, "medium"), "medium", "draft")
    assert mock_rp.call_count == 1, "browser-tier must use the CLI subprocess"
    assert mock_rp.call_args[0][0] == ["publish-backlinks", "--platform", "medium", "--mode", "draft"]
    assert res.success is True


def test_browser_tier_publish_seed_routes_to_subprocess():
    captured = {"returncode": 0, "stdout": '{"published_url":"https://m/p","status":"drafted"}', "stderr": ""}
    with patch("backlink_publisher.sdk.api.run_pipe_capture", return_value=captured) as mock_rp:
        res = PipelineAPI().publish_seed(_seed(1, "devto"))
    assert mock_rp.call_count == 1, "a browser-tier seed row keeps the subprocess path"
    assert mock_rp.call_args[0][0] == ["publish-backlinks"]
    assert res.success is True


def test_api_tier_publish_never_spawns_subprocess():
    with patch("backlink_publisher.sdk.api.run_pipe_capture") as mock_rp, \
         patch("backlink_publisher.cli.publish_backlinks.verify_adapter_setup"), \
         patch("backlink_publisher.cli.publish_backlinks.adapter_publish") as mock_pub:
        mock_pub.side_effect = [_ok_result()]
        PipelineAPI().publish(_seed(1, "blogger"), "blogger", "draft")
    assert mock_rp.call_count == 0, "API-tier publish must run in-process, no subprocess"


# ── concurrency: the process lock serializes in-process runs ─────────────────


def test_concurrent_inprocess_publish_serialized_by_lock():
    """Two concurrent publish() calls on DIFFERENT API-tier platforms (blogger +
    telegraph — distinct leases, so only the process lock can serialize them) must
    not interleave their dispatch. Mirrors plan U5 hard acceptance: no overlap, no
    double-publish, leases released after each."""
    max_active = {"n": 0}
    cur_active = {"n": 0}
    guard = threading.Lock()

    def _slow_adapter(*args, **kwargs):
        with guard:
            cur_active["n"] += 1
            max_active["n"] = max(max_active["n"], cur_active["n"])
        time.sleep(0.05)
        with guard:
            cur_active["n"] -= 1
        return _ok_result(platform=kwargs.get("payload", {}).get("platform", "blogger"))

    results = {}

    def _worker(platform):
        results[platform] = PipelineAPI().publish(_seed(1, platform), platform, "draft")

    # ONE shared patch around both threads — mock.patch is not thread-safe, so a
    # per-thread `with patch` would let one thread's teardown restore the real
    # adapter while the other is mid-dispatch. The single patch isolates the test
    # from that artifact; the process lock under test still serializes the runs.
    with patch("backlink_publisher.cli.publish_backlinks.verify_adapter_setup"), \
         patch("backlink_publisher.cli.publish_backlinks.adapter_publish", side_effect=_slow_adapter):
        threads = [threading.Thread(target=_worker, args=(p,)) for p in ("blogger", "telegraph")]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    assert max_active["n"] == 1, "process lock must serialize concurrent in-process publishes"
    assert all(r.success for r in results.values()), "both runs succeed once serialized"


def test_lease_released_after_run_allows_resubmit():
    """A second publish() to the same platform after the first returns must
    succeed — proving the lease was released in try/finally (not held for the
    1h TTL / leaked to atexit)."""
    with patch("backlink_publisher.cli.publish_backlinks.verify_adapter_setup"), \
         patch("backlink_publisher.cli.publish_backlinks.adapter_publish") as mock_pub:
        mock_pub.side_effect = [_ok_result(), _ok_result()]
        first = PipelineAPI().publish(_seed(1, "blogger"), "blogger", "draft")
        second = PipelineAPI().publish(_seed(1, "blogger"), "blogger", "draft")
    assert first.success is True and second.success is True
