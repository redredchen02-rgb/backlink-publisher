"""Recheck coverage measurement (Plan 2026-06-15-001, Unit B1).

Makes the ">=50% liveness coverage" target *measurable* and aligned to the
scorecard's staleness window. Coverage is a freshness property, not a cumulative
count: a link counts as covered only while its last definitive recheck is within
``stale_days``. This is what distinguishes "we rechecked 50% of links once" (which
silently regresses) from "50% of links have a fresh recheck signal right now".

Reuses :func:`build_channel_scorecard` verbatim so coverage, the scorecard, and
the equity-ledger can never disagree on what "live"/"stale" means. A link is
**covered-within-window** when its liveness is ``live`` (verified within
``stale_days``) or ``failed`` (a definitive verify verdict exists); it is
**uncovered** when ``stale`` (verified but older than the window) or
``unverified`` (never definitively rechecked).

Read-only; no writes, no network. Prioritisation of *which* links to recheck
already lives in :mod:`backlink_publisher.recheck.selection` (oldest-first over
the same confirmed/unverified universe the scorecard counts); this module only
*measures* the resulting coverage so an operator/CI can see whether the target
is met and held.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backlink_publisher.events import EventStore

from .engine import build_channel_scorecard

#: Default coverage target (operator decision 2026-06-15): >=50% of all links
#: covered within the staleness window.
DEFAULT_TARGET_PCT = 0.5

# Liveness statuses that count as a fresh/definitive recheck signal.
_COVERED_KEYS = ("live", "failed")
# Liveness statuses that do NOT count toward within-window coverage.
_UNCOVERED_KEYS = ("stale", "unverified")


@dataclass(frozen=True)
class ChannelCoverage:
    channel: str
    total_links: int
    covered: int
    coverage_pct: float | None  # None when total == 0


@dataclass(frozen=True)
class CoverageReport:
    total_links: int
    covered: int
    coverage_pct: float | None
    target_pct: float
    meets_target: bool
    stale_days: int
    per_channel: list[ChannelCoverage]


def _covered_of(breakdown: dict[str, int]) -> int:
    return sum(breakdown.get(k, 0) for k in _COVERED_KEYS)


def recheck_coverage(
    *,
    stale_days: int = 30,
    target_pct: float = DEFAULT_TARGET_PCT,
    store: EventStore | None = None,
    history: list[dict[str, Any]] | None = None,
) -> CoverageReport:
    """Measure within-window recheck coverage overall and per channel.

    ``stale_days`` MUST match the scorecard window the coverage is being judged
    against (default 30) so "covered" means the same thing in both places.
    """
    rows = build_channel_scorecard(
        stale_days=stale_days, store=store, history=history
    )

    per_channel: list[ChannelCoverage] = []
    total = 0
    covered = 0
    for row in rows:
        if row.total_links == 0:
            continue  # declared-only channels contribute no denominator
        ch_covered = _covered_of(row.liveness_breakdown)
        total += row.total_links
        covered += ch_covered
        per_channel.append(
            ChannelCoverage(
                channel=row.channel,
                total_links=row.total_links,
                covered=ch_covered,
                coverage_pct=round(ch_covered / row.total_links, 3),
            )
        )

    coverage_pct = round(covered / total, 3) if total else None
    # Lowest-coverage channels first — the work queue for hitting the target.
    per_channel.sort(key=lambda c: (c.coverage_pct if c.coverage_pct is not None else 0.0, c.channel))
    return CoverageReport(
        total_links=total,
        covered=covered,
        coverage_pct=coverage_pct,
        target_pct=target_pct,
        meets_target=(coverage_pct is not None and coverage_pct >= target_pct),
        stale_days=stale_days,
        per_channel=per_channel,
    )
