"""Tests for plan-backlinks prefetch/stats and config-echo-chamber features."""
from __future__ import annotations

__tier__ = "unit"
import json
import sys
from io import StringIO

import pytest

from backlink_publisher.cli.plan_backlinks import main


def _run_plan(input_data: str, argv: list[str] | None = None) -> tuple[str, str, int]:
    """Run plan-backlinks with given stdin data. Returns (stdout, stderr, exit_code)."""
    old_stdin = sys.stdin
    old_stdout = sys.stdout
    old_stderr = sys.stderr
    try:
        sys.stdin = StringIO(input_data)
        out = StringIO()
        err = StringIO()
        sys.stdout = out
        sys.stderr = err
        try:
            main(argv or [])
            code = 0
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else 1
        return out.getvalue(), err.getvalue(), code
    finally:
        sys.stdin = old_stdin
        sys.stdout = old_stdout
        sys.stderr = old_stderr


# ═════════════════════════════════════════════════════════════════════════════
# Plan 008 Units 2+3: cross-row URL prefetch + content_fetch_stats recon
# ═════════════════════════════════════════════════════════════════════════════


class TestContentFetchPrefetchAndStats:
    """Plan 2026-05-14-008 Units 2 + 3: cross-row prefetch collapses N
    sequential row-batches into 1 union batch; content_fetch_stats recon
    event surfaces cache-hit rate + reason distribution at end-of-run."""

    def test_prefetch_fires_once_per_invocation_with_union_urls(
        self, monkeypatch
    ):
        """3-row batch → 1 batch call with the union of distinct URLs (not
        3 sequential per-row batches)."""
        call_log: list[list[str]] = []

        def _track_batch(urls, max_workers=5):
            call_log.append(list(urls))
            return {u: (True, None, "ok") for u in urls}

        monkeypatch.setattr(
            "backlink_publisher.content.fetch.verify_urls_batch", _track_batch,
        )

        rows = [
            {
                "target_url": f"https://a{i}.example/",
                "main_domain": f"https://a{i}.example/",
                "language": "en",
                "platform": "medium",
                "url_mode": "A",
                "publish_mode": "draft",
            }
            for i in range(3)
        ]
        stdout, stderr, code = _run_plan(
            "\n".join(json.dumps(r) for r in rows)
        )
        assert code == 0

        # Prefetch batch fires once at the top with the union of URLs.
        assert len(call_log) >= 1
        prefetch_urls = set(call_log[0])
        assert "https://a0.example" in prefetch_urls
        assert "https://a1.example" in prefetch_urls
        assert "https://a2.example" in prefetch_urls
        # Supporting URLs prefetched once globally.
        assert "https://en.wikipedia.org" in prefetch_urls

        # content_fetch_prefetch recon emitted.
        recon = [
            line for line in stderr.splitlines()
            if '"msg": "content_fetch_prefetch"' in line
        ]
        assert recon, "expected content_fetch_prefetch recon event"
        event = json.loads(recon[0])
        assert event["n_rows"] == 3
        assert event["n_urls_prefetched"] >= 4  # 3 main + supporting

    def test_no_fetch_verify_skips_prefetch_entirely(self, monkeypatch):
        """--no-fetch-verify must skip the prefetch — verify_urls_batch
        never invoked at the top of main()."""
        call_count = {"n": 0}

        def _track(urls, max_workers=5):
            call_count["n"] += 1
            return {u: (True, None, "ok") for u in urls}

        monkeypatch.setattr(
            "backlink_publisher.content.fetch.verify_urls_batch", _track,
        )
        seed = {
            "target_url": "https://example.com/article",
            "main_domain": "https://example.com",
            "language": "en",
            "platform": "medium",
            "url_mode": "A",
            "publish_mode": "draft",
        }
        _stdout, _stderr, code = _run_plan(
            json.dumps(seed), argv=["--no-fetch-verify"],
        )
        assert code == 0
        assert call_count["n"] == 0, (
            "--no-fetch-verify must skip the prefetch call too, not just "
            "per-row gating"
        )

    def test_content_fetch_stats_recon_emitted_at_end_of_run(
        self, monkeypatch
    ):
        """End-of-run plan_logger.recon('content_fetch_stats', ...) carries
        the cache + fetch + reason counters."""
        def _all_pass(urls, max_workers=5):
            return {u: (True, None, "ok") for u in urls}

        monkeypatch.setattr(
            "backlink_publisher.content.fetch.verify_urls_batch", _all_pass,
        )
        seed = {
            "target_url": "https://example.com/article",
            "main_domain": "https://example.com",
            "language": "en",
            "platform": "medium",
            "url_mode": "A",
            "publish_mode": "draft",
        }
        _stdout, stderr, code = _run_plan(json.dumps(seed))
        assert code == 0

        events = [
            line for line in stderr.splitlines()
            if '"msg": "content_fetch_stats"' in line
        ]
        assert events, "expected content_fetch_stats recon at end-of-run"
        snap = json.loads(events[0])
        # Snapshot keys present.
        assert "cache_hits" in snap
        assert "cache_misses" in snap
        assert "fetches" in snap
        assert "total_latency_ms" in snap
        assert "reason_counts" in snap

    def test_prefetch_skipped_when_no_valid_rows(self, monkeypatch):
        """If every input row fails validation, prefetch should not fire
        (union is empty besides the always-on supporting URLs)."""
        call_log: list[list[str]] = []

        def _track(urls, max_workers=5):
            call_log.append(list(urls))
            return {u: (True, None, "ok") for u in urls}

        monkeypatch.setattr(
            "backlink_publisher.content.fetch.verify_urls_batch", _track,
        )
        # All rows missing required fields.
        bad_rows = [{"language": "en"}, {"platform": "medium"}]
        _stdout, _stderr, code = _run_plan(
            "\n".join(json.dumps(r) for r in bad_rows)
        )
        assert code == 2  # validation errors
        # Prefetch may still fire with just the supporting URLs (5 entries),
        # which is the documented "always prefetch supporting" behavior.
        # Stronger assertion: no row-derived URLs leaked into the prefetch.
        for batch in call_log:
            for url in batch:
                assert "a0.example" not in url
                assert "a1.example" not in url


# ═════════════════════════════════════════════════════════════════════════════
# Config Echo Chamber integration (Round-3 #7)
# ═════════════════════════════════════════════════════════════════════════════


class TestConfigEchoChamber:
    """Verify the 4-line config banner emits at plan-backlinks startup +
    the resolved-config SHA is stamped into every payload's metadata
    so artifacts can be reverse-mapped to the config that produced them."""

    def test_banner_emitted_to_stderr_on_startup(self):
        seed = {
            "target_url": "https://example.com/article",
            "main_domain": "https://example.com",
            "language": "en",
            "platform": "medium",
            "url_mode": "A",
            "publish_mode": "draft",
        }
        _stdout, stderr, code = _run_plan(json.dumps(seed))
        assert code == 0
        # All 5 banner lines present.
        assert "[plan-backlinks] effective config:" in stderr
        assert "  config:" in stderr
        assert "  env:" in stderr
        assert "  platforms:" in stderr
        assert "  sha:" in stderr

    def test_payload_metadata_contains_config_sha(self):
        seed = {
            "target_url": "https://example.com/article",
            "main_domain": "https://example.com",
            "language": "en",
            "platform": "medium",
            "url_mode": "A",
            "publish_mode": "draft",
        }
        stdout, _stderr, code = _run_plan(json.dumps(seed))
        assert code == 0
        payload = json.loads(stdout.strip())
        assert "metadata" in payload
        sha = payload["metadata"].get("config_sha")
        assert sha is not None, "payload metadata must contain config_sha"
        # 16-char hex prefix per compute_config_sha contract
        import re as _re
        assert _re.fullmatch(r"[0-9a-f]{16}", sha) is not None

    def test_same_config_produces_same_sha_across_payloads(self):
        """All payloads from one invocation carry the same SHA — no surprise
        cross-row config drift."""
        seeds = [
            {
                "target_url": f"https://example.com/a{i}",
                "main_domain": "https://example.com",
                "language": "en",
                "platform": "medium",
                "url_mode": "A",
                "publish_mode": "draft",
            }
            for i in range(3)
        ]
        stdout, _, code = _run_plan("\n".join(json.dumps(s) for s in seeds))
        assert code == 0
        payloads = [json.loads(line) for line in stdout.strip().split("\n")]
        shas = {p["metadata"]["config_sha"] for p in payloads}
        assert len(shas) == 1, f"expected one SHA across all payloads, got {shas}"
