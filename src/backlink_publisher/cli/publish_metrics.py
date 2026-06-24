"""Publish reliability metrics — per-channel success rate + recheck coverage (JSONL).

Surfaces the two Track-B observability metrics (Plan 2026-06-15-001) on the
terminal so operators / monitoring can read them without the WebUI:

* **publish success rate** (B2) — successes / (successes + terminal failures)
  per channel over a rolling window, derived from persisted
  publish.confirmed/unverified (success) and publish.failed (failure) events.
* **recheck coverage** (B1) — fraction of published links with a *fresh*
  liveness verdict (within ``--stale-days``), against the >=50% target.

stdout = data (JSONL): one object per channel (union of both metrics), then a
final ``{"_summary": {...}}`` line with the overall rollup. stderr = the
config-echo banner. Exit 0 on success; with ``--alarm`` exits 6 when within-window
liveness coverage is below target (opt-in, for scheduled freshness monitoring —
the default stays advisory, exit 0). Read-only over events.db.
"""

from __future__ import annotations

import sys
from typing import Any, Iterator

import backlink_publisher.publishing.adapters  # noqa: F401  populate registry before config load
from .. import config_echo
from backlink_publisher._util.errors import emit_envelope_and_exit, emit_error
from backlink_publisher._util.jsonl import write_jsonl
from backlink_publisher.config import load_config
from backlink_publisher.scorecard.coverage import recheck_coverage
from backlink_publisher.scorecard.success_rate import publish_success_rate

#: Advisory domain-alarm exit code (the family recheck-backlinks --fail-on-dead
#: uses). Emitted only with --alarm when within-window coverage is below target.
_COVERAGE_ALARM_EXIT_CODE = 6


def _rows(success: Any, coverage: Any) -> Iterator[dict]:
    sr_by_channel = {c.channel: c for c in success.per_channel}
    cov_by_channel = {c.channel: c for c in coverage.per_channel}

    for channel in sorted(set(sr_by_channel) | set(cov_by_channel)):
        sr = sr_by_channel.get(channel)
        cov = cov_by_channel.get(channel)
        yield {
            "channel": channel,
            # publish success rate (B2)
            "attempts": sr.attempts if sr else 0,
            "successes": sr.successes if sr else 0,
            "failures": sr.failures if sr else 0,
            "success_pct": sr.success_pct if sr else None,
            "small_sample": sr.small_sample if sr else True,
            # recheck coverage (B1)
            "coverage_total": cov.total_links if cov else 0,
            "covered": cov.covered if cov else 0,
            "coverage_pct": cov.coverage_pct if cov else None,
        }

    yield {
        "_summary": {
            "window_days": success.window_days,
            "stale_days": coverage.stale_days,
            "overall_success_pct": success.overall_success_pct,
            "overall_attempts": success.overall_attempts,
            "overall_coverage_pct": coverage.coverage_pct,
            "coverage_target_pct": coverage.target_pct,
            "coverage_meets_target": coverage.meets_target,
        }
    }


def main(argv: list[str] | None = None) -> None:
    import argparse

    parser = argparse.ArgumentParser(
        prog="publish-metrics",
        description=(
            "Per-channel publish success rate (over a rolling window) beside "
            "recheck coverage (fresh-liveness fraction vs the >=50% target). "
            "Emits one JSON object per channel on stdout, then a '_summary' "
            "rollup line. Read-only over events.db. Advisory only."
        ),
    )
    parser.add_argument(
        "--window-days", type=int, default=30, metavar="N",
        help="Success rate is computed over publish events from the last N days "
             "(default: 30).",
    )
    parser.add_argument(
        "--stale-days", type=int, default=30, metavar="N",
        help="A link rechecked longer ago than N days no longer counts as covered "
             "(default: 30).",
    )
    parser.add_argument(
        "--small-sample-max", type=int, default=4, metavar="N",
        help="Channels with N publish attempts or fewer are flagged small_sample "
             "(default: 4).",
    )
    parser.add_argument(
        "--alarm", action="store_true",
        help="Exit 6 (advisory alarm) when overall within-window liveness coverage "
             "is below target — for scheduled freshness monitoring. Default off: "
             "the command stays advisory (exit 0). No alarm on an empty ledger.",
    )
    parser.add_argument(
        "--coverage-fail-under", type=float, default=None, metavar="PCT",
        help="Override the --alarm threshold (0-1). Defaults to the report's target_pct.",
    )
    args = parser.parse_args(argv)

    if args.window_days <= 0:
        emit_error("publish-metrics: --window-days must be a positive integer", exit_code=1)
    if args.stale_days <= 0:
        emit_error("publish-metrics: --stale-days must be a positive integer", exit_code=1)
    if args.small_sample_max < 0:
        emit_error("publish-metrics: --small-sample-max must be >= 0", exit_code=1)
    if args.coverage_fail_under is not None and not (0.0 <= args.coverage_fail_under <= 1.0):
        emit_error("publish-metrics: --coverage-fail-under must be between 0 and 1", exit_code=1)

    cfg = load_config()
    config_echo.emit_banner(cfg, "publish-metrics")

    success = publish_success_rate(
        window_days=args.window_days, small_sample_max=args.small_sample_max
    )
    coverage = recheck_coverage(stale_days=args.stale_days)

    write_jsonl(_rows(success, coverage), sys.stdout)

    if args.alarm:
        threshold = (
            args.coverage_fail_under
            if args.coverage_fail_under is not None
            else coverage.target_pct
        )
        pct = coverage.coverage_pct
        # Empty ledger → coverage_pct is None → not a regression; never false-alarm.
        if pct is not None and pct < threshold:
            emit_envelope_and_exit(
                "LivenessCoverageBelowTarget",
                _COVERAGE_ALARM_EXIT_CODE,
                f"publish-metrics: within-window liveness coverage {pct:.1%} below "
                f"target {threshold:.1%} ({coverage.covered}/{coverage.total_links} "
                f"links fresh within {coverage.stale_days}d)",
            )


if __name__ == "__main__":
    main()
