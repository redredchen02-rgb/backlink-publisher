"""Unit 5 — burst dispatch with platform-agnostic jitter.

publish_fn / sleep_fn / rng are all injected: no network, no real sleeps,
reproducible jitter. Covers happy path, non-uniform spacing, continue-on-failure
(incl. AuthExpired), and seeded reproducibility.
"""
from __future__ import annotations

__tier__ = "unit"
from dataclasses import dataclass
import random

import pytest

from backlink_publisher._util.errors import AuthExpiredError
from backlink_publisher.cli.spray_backlinks._dispatch import dispatch_burst


@dataclass
class _FakeResult:
    status: str
    error: str | None = None


def _rows(n: int) -> list[dict]:
    return [{"platform": f"p{i}", "content_markdown": f"body {i}"} for i in range(n)]


def test_burst_publishes_all_and_sleeps_between_shots():
    sleeps: list[float] = []
    calls: list[str] = []

    def pub(row, mode, cfg):
        calls.append(row["platform"])
        return _FakeResult(status="published")

    summary = dispatch_burst(
        _rows(3), cfg=None, mode="draft",
        publish_fn=pub, sleep_fn=sleeps.append, rng=random.Random(0),
    )
    assert summary.n_succeeded == 3
    assert summary.n_failed == 0
    assert calls == ["p0", "p1", "p2"]
    assert len(sleeps) == 2  # N-1 gaps


def test_jitter_is_non_uniform():
    sleeps: list[float] = []
    dispatch_burst(
        _rows(4), cfg=None, mode="draft",
        publish_fn=lambda r, m, c: _FakeResult("published"),
        sleep_fn=sleeps.append, rng=random.Random(123),
    )
    assert len(sleeps) == 3
    assert len(set(sleeps)) > 1  # not fixed-interval


def test_seeded_jitter_is_reproducible():
    a: list[float] = []
    b: list[float] = []
    for sink in (a, b):
        dispatch_burst(
            _rows(4), cfg=None, mode="draft",
            publish_fn=lambda r, m, c: _FakeResult("published"),
            sleep_fn=sink.append, rng=random.Random(7),
        )
    assert a == b


def test_continue_on_failure_mid_batch():
    def pub(row, mode, cfg):
        if row["platform"] == "p1":
            return _FakeResult(status="failed", error="boom")
        return _FakeResult(status="published")

    summary = dispatch_burst(
        _rows(4), cfg=None, mode="draft",
        publish_fn=pub, sleep_fn=lambda s: None, rng=random.Random(0),
    )
    assert summary.n_succeeded == 3  # p0, p2, p3
    assert summary.n_failed == 1
    assert summary.failed[0][0] == "p1"


def test_auth_expired_fails_shot_not_burst():
    def pub(row, mode, cfg):
        if row["platform"] == "p0":
            raise AuthExpiredError("cookie expired")
        return _FakeResult(status="published")

    summary = dispatch_burst(
        _rows(3), cfg=None, mode="draft",
        publish_fn=pub, sleep_fn=lambda s: None, rng=random.Random(0),
    )
    # p0 AuthExpired → fails just that shot; p1, p2 still dispatch.
    assert summary.n_succeeded == 2
    assert summary.n_failed == 1
    assert "AuthExpiredError" in summary.failed[0][1]
