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
