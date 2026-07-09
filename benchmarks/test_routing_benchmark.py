"""Performance regression baselines for hot paths.

These run network-free (routing is pure logic) so they can execute anywhere
and establish a stored baseline under ``.benchmarks/``. Run with::

    pytest benchmarks/ -q

pytest-benchmark compares each run against the previously stored stats, so any
future speed change to these paths is caught as a regression. This is the
foundation called for by plan 2026-07-09-001 (C1) — without it, speed
optimizations (e.g. parallel publish dispatch) cannot be guarded.

Kept OUT of ``tests/`` so the normal ``pytest tests/`` suite is not slowed.
"""

from __future__ import annotations

from backlink_publisher._dispatch_router.routing import route
from backlink_publisher._dispatch_router.signals import PlatformSignal


def _make_signals() -> dict[str, PlatformSignal]:
    return {
        "medium": PlatformSignal(name="medium", dofollow=True, binding="bound", dispatch_weight=1.0),
        "devto": PlatformSignal(name="devto", dofollow=True, binding="bound", dispatch_weight=0.9),
        "telegraph": PlatformSignal(name="telegraph", dofollow=False, binding="bound", referral="high"),
        "hashnode": PlatformSignal(name="hashnode", dofollow=True, binding="expired"),
        "linkedin": PlatformSignal(name="linkedin", dofollow=True, binding="unbound"),
    }


def test_route_balanced_benchmark(benchmark: object) -> None:
    signals = _make_signals()
    row = {"url": "https://example.com/a", "language": "en"}

    def run() -> object:
        return route(row, signals, strategy="balanced")

    result = benchmark(run)
    assert result.platform is not None


def test_route_spread_benchmark(benchmark: object) -> None:
    signals = _make_signals()
    ledger = {"https://example.com/a": {"live_dofollow_platforms": ["medium", "devto"]}}
    row = {"url": "https://example.com/a", "language": "en"}

    def run() -> object:
        return route(row, signals, ledger_map=ledger, strategy="spread")

    result = benchmark(run)
    assert result.platform is not None
