"""Performance benchmarks for core pipeline operations.

Thresholds are advisory (warn-only) — they surface regressions in CI's
warning summary without blocking the build. Run locally with:

    pytest tests/test_benchmarks.py --benchmark-only --benchmark-save=baseline

Compare against baseline:

    pytest tests/test_benchmarks.py --benchmark-compare=baseline

See docs/plans/2026-06-26-optimization-phase3-plan.md §M4.
"""
from __future__ import annotations

__tier__ = "unit"

import json
import pytest

from _plan_test_helpers import _run_plan, _make_seed


pytest.importorskip("pytest_benchmark")


# ═════════════════════════════════════════════════════════════════════════════
# plan-backlinks throughput
# ═════════════════════════════════════════════════════════════════════════════

_SEED_1K_ROWS = "\n".join(
    json.dumps(
        _make_seed(
            target_url=f"https://example{i}.com/article",
            main_domain=f"https://example{i}.com",
            language="en" if i % 2 == 0 else "zh-CN",
            platform="medium" if i % 3 == 0 else "blogger",
            url_mode=["A", "B", "C"][i % 3],
        )
    )
    for i in range(100)
)


def test_benchmark_plan_100_rows(benchmark):
    """Measure plan-backlinks throughput: 100-row batch → execution time."""

    def _run():
        stdout, stderr, code = _run_plan(_SEED_1K_ROWS)
        assert code == 0
        lines = stdout.strip().split("\n")
        assert len(lines) == 100
        return len(lines)

    result = benchmark(_run)
    assert result == 100


def test_benchmark_plan_single_row(benchmark):
    """Measure plan-backlinks per-row latency (fast path)."""
    seed = json.dumps(_make_seed())

    def _run():
        stdout, stderr, code = _run_plan(seed)
        assert code == 0
        return len(stdout.strip())

    result = benchmark(_run)
    assert result > 0


# ═════════════════════════════════════════════════════════════════════════════
# JSONL serialization throughput (pipeline hot path)
# ═════════════════════════════════════════════════════════════════════════════

_LARGE_RECORDS = [
    {
        "id": f"test-{i}",
        "title": "x" * 100,
        "content_markdown": "y" * 5000,
        "links": [
            {"url": f"https://example.com/{j}", "anchor": f"anchor-{j}"}
            for j in range(10)
        ],
        "metadata": {"config_sha": "abcd1234", "version": "0.5.0"},
    }
    for i in range(500)
]


def test_benchmark_jsonl_serialize_500_rows(benchmark):
    """Measure JSONL serialization throughput for 500-row batch."""

    def _run():
        return "\n".join(json.dumps(r, ensure_ascii=False) for r in _LARGE_RECORDS)

    result = benchmark(_run)
    # Verify output size is reasonable
    assert len(result) > 100_000

# ═════════════════════════════════════════════════════════════════════════════
# publish-backlinks dry-run throughput (P13 C1)
# ═════════════════════════════════════════════════════════════════════════════

import sys as _sys
import os as _os
from io import StringIO as _StringIO


def _make_publish_payload(url_mode: str = "A", platform: str = "medium") -> dict:
    return {
        "id": "bench-001",
        "platform": platform,
        "language": "en",
        "publish_mode": "draft",
        "target_url": "https://example.com/article",
        "main_domain": "https://example.com",
        "url_mode": url_mode,
        "title": "Benchmark Test Article",
        "slug": "bench-test-article",
        "excerpt": "Benchmark test excerpt.",
        "tags": ["tag1", "tag2"],
        "content_markdown": "Benchmark test content for https://example.com.",
        "links": [
            {"url": "https://example.com", "anchor": "Example",
             "kind": "main_domain", "required": True},
        ],
        "link_count": 1,
        "approved": True,
        "dofollow": True,
    }


def _run_publish_bench(input_data: str) -> tuple[str, str, int]:
    """Run publish-backlinks --dry-run with given stdin."""
    from backlink_publisher.cli.publish_backlinks import main
    old_stdin = _sys.stdin
    old_stdout = _sys.stdout
    old_stderr = _sys.stderr
    try:
        _sys.stdin = _StringIO(input_data)
        out = _StringIO()
        err = _StringIO()
        _sys.stdout = out
        _sys.stderr = err
        try:
            main(["--dry-run"])
            code = 0
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else 1
        return out.getvalue(), err.getvalue(), code
    finally:
        _sys.stdin = old_stdin
        _sys.stdout = old_stdout
        _sys.stderr = old_stderr


_BENCH_PAYLOAD_50 = "\n".join(
    json.dumps(_make_publish_payload(
        platform="medium" if i % 2 == 0 else "blogger",
        url_mode=["A", "B", "C"][i % 3],
    ))
    for i in range(50)
)


def test_benchmark_publish_50_rows_dry_run(benchmark):
    """Measure publish-backlinks --dry-run throughput: 50 rows."""
    def _run():
        stdout, stderr, code = _run_publish_bench(_BENCH_PAYLOAD_50)
        assert code == 0
        lines = [l for l in stdout.strip().split("\n") if l.strip()]
        return len(lines)

    result = benchmark(_run)
    assert result >= 0


# ═════════════════════════════════════════════════════════════════════════════
# webui_store hot-path baselines (Plan 2026-07-06-002 Unit E2, R11)
#
# These establish first-time baselines only -- per K7 ("benchmark only, don't
# optimize"), no code in webui_store/ or the link-attr verifier is changed
# here even where the numbers below look slow. See the plan's E2 section.
# ═════════════════════════════════════════════════════════════════════════════

def _make_history_records(n: int) -> list[dict]:
    return [
        {
            "id": f"hist-{i}",
            "platform": "medium" if i % 3 == 0 else "blogger",
            "status": "published",
            "target_url": f"https://example{i}.com/article",
            "created_at": "2026-07-01T00:00:00+00:00",
            "verified_at": None,
            "verify_error": None,
        }
        for i in range(n)
    ]


def test_benchmark_history_update_item_100_records(benchmark, tmp_path):
    """history.py update_item latency: whole-file load+save at ~100-record scale."""
    from webui_store.history import HistoryStore

    store = HistoryStore(tmp_path / "history_small.json")
    store.save(_make_history_records(100))

    def _run():
        return store.update_item(
            "hist-50", verified_at="2026-07-06T00:00:00+00:00", verify_error=None,
        )

    result = benchmark(_run)
    assert result is True


def test_benchmark_history_update_item_1000_records(benchmark, tmp_path):
    """history.py update_item latency: whole-file load+save at ~1000-record scale.

    Edge-case sibling of the 100-record case above -- compares against it to
    sanity-check the load+save pattern behaves roughly O(n) as file size grows
    (see the plan's E2 edge-case scenario).
    """
    from webui_store.history import HistoryStore

    store = HistoryStore(tmp_path / "history_large.json")
    store.save(_make_history_records(1000))

    def _run():
        return store.update_item(
            "hist-500", verified_at="2026-07-06T00:00:00+00:00", verify_error=None,
        )

    result = benchmark(_run)
    assert result is True


def test_benchmark_campaign_update_seed_status(benchmark, tmp_path):
    """campaign_store.py update_seed_status: single-txn SELECT->mutate->recompute->UPDATE."""
    from webui_store.campaign_store import CampaignSqliteStore
    from webui_store.sqlite_base import WebUIDatabase

    store = CampaignSqliteStore(WebUIDatabase(tmp_path / "webui.db"))
    seeds = [{"seed_text": f"seed {i}"} for i in range(20)]
    campaign_id = store.create(mode="publish", platforms=["medium"], seeds=seeds)
    # Pad the table so the benchmark isn't a trivial single-row table.
    for _ in range(49):
        store.create(mode="draft", platforms=["blogger"], seeds=seeds)

    def _run():
        return store.update_seed_status(
            campaign_id, 0, status="processing", draft_count=1,
        )

    result = benchmark(_run)
    assert result is True


def test_benchmark_batch_ops_update_row(benchmark, tmp_path):
    """batch_ops.py update_row: single-row status patch on the batch-op queue."""
    from webui_store.batch_ops import BatchOpsSqliteStore
    from webui_store.sqlite_base import WebUIDatabase

    store = BatchOpsSqliteStore(WebUIDatabase(tmp_path / "webui.db"))
    ids = store.enqueue_many(
        [f"https://example{i}.com" for i in range(100)], "keep_alive",
    )
    row_id = ids[0]

    def _run():
        store.update_row(row_id, "processing", None)
        return row_id

    result = benchmark(_run)
    assert result == row_id


def test_benchmark_link_attr_verify_medium_content(benchmark):
    """link_attr_verifier.py verify_link_attributes: nested-loop target match +
    repeated full-text regex scan over medium-length HTML (~200 anchors)."""
    from unittest.mock import patch as _patch

    from backlink_publisher.publishing.adapters.link_attr_verifier import (
        verify_link_attributes,
    )

    anchors = "\n".join(
        '<a href="https://example{0}.com/page" rel="{1}">link {0}</a>'.format(
            i, "nofollow" if i % 5 == 0 else "noopener",
        )
        for i in range(200)
    )
    html = f"<html><body>{anchors}</body></html>".encode()
    target_urls = [f"https://example{i}.com/page" for i in range(0, 200, 10)]

    with _patch(
        "backlink_publisher.publishing.adapters.link_attr_verifier."
        "_fetch_body_via_preflight",
        return_value=(html, None),
    ):
        def _run():
            return verify_link_attributes("https://example.com", target_urls=target_urls)

        result = benchmark(_run)
    assert result["verification"] == "ok"
