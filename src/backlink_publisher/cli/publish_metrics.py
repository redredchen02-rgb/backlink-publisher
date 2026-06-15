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
config-echo banner. Exit 0 on success. Read-only, advisory — never gates anything.
"""

from __future__ import annotations

import sys

import backlink_publisher.publishing.adapters  # noqa: F401  populate registry before config load
from .. import config_echo
from backlink_publisher._util.errors import emit_error
from backlink_publisher._util.jsonl import write_jsonl
from backlink_publisher.config import load_config
from backlink_publisher.scorecard.coverage import recheck_coverage
from backlink_publisher.scorecard.success_rate import publish_success_rate


def _rows(*, window_days: int, stale_days: int, small_sample_max: int):
    success = publish_success_rate(
        window_days=window_days, small_sample_max=small_sample_max
    )
    coverage = recheck_coverage(stale_days=stale_days)

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
    args = parser.parse_args(argv)

    if args.window_days <= 0:
        emit_error("publish-metrics: --window-days must be a positive integer", exit_code=1)
    if args.stale_days <= 0:
        emit_error("publish-metrics: --stale-days must be a positive integer", exit_code=1)
    if args.small_sample_max < 0:
        emit_error("publish-metrics: --small-sample-max must be >= 0", exit_code=1)

    cfg = load_config()
    config_echo.emit_banner(cfg, "publish-metrics")

    write_jsonl(
        _rows(
            window_days=args.window_days,
            stale_days=args.stale_days,
            small_sample_max=args.small_sample_max,
        ),
        sys.stdout,
    )


if __name__ == "__main__":
    main()
