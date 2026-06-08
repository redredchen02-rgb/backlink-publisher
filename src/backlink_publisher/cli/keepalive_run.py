"""keepalive-run — automated keep-alive recovery loop (plan 2026-06-05-004 U1).

Chains: recheck → keepalive-gap → publish → reverify → update-stats.
Safe for unattended launchd scheduling; acquires a cycle-level lock to prevent
concurrent runs. Designed for daily execution.

Exit codes
----------
0 : cycle completed (or skipped — another instance running)
1 : unhandled error
6 : cycle ran but no gaps were filled (all_failed equivalent)
"""
from __future__ import annotations

import json
import sys


def main(argv: list[str] | None = None) -> None:
    import argparse

    parser = argparse.ArgumentParser(
        prog="keepalive-run",
        description="Automated keep-alive recovery loop: recheck → gap → publish → reverify",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show gap plan without publishing or modifying state",
    )
    parser.add_argument(
        "--max-gaps", type=int, default=None, metavar="N",
        help="Limit the number of seeds to publish per cycle (default: unlimited)",
    )
    parser.add_argument(
        "--min-age-days", type=int, default=7, metavar="N",
        help="Minimum age (days) for a target to be eligible for gap fill (default: 7)",
    )
    args = parser.parse_args(argv)

    try:
        from backlink_publisher.keepalive.chain import run_cycle
        result = run_cycle(
            dry_run=args.dry_run,
            max_gaps=args.max_gaps,
            min_age_days=args.min_age_days,
        )
    except Exception as exc:
        print(f"keepalive-run: error — {exc}", file=sys.stderr)
        sys.exit(1)

    if result.get("skipped"):
        print("keepalive-run: cycle already in progress, skipping", file=sys.stderr)
        sys.exit(0)

    if args.dry_run:
        gaps = result.get("gaps_found", 0)
        seeds = result.get("seeds", [])
        print(f"keepalive-run: dry-run — {gaps} gap(s) found", file=sys.stderr)
        if seeds:
            for s in seeds:
                print(json.dumps(s))
        sys.exit(0)

    published = result.get("published", 0)
    gaps = result.get("gaps_found", 0)
    alive = result.get("reverified_alive", 0)
    print(
        f"keepalive-run: gaps={gaps} published={published} "
        f"alive={alive} dead={result.get('reverified_dead', 0)} "
        f"skipped_exhausted={result.get('exhausted_skipped', 0)}",
        file=sys.stderr,
    )
    if gaps > 0 and published == 0:
        sys.exit(6)
    sys.exit(0)


if __name__ == "__main__":
    main()
