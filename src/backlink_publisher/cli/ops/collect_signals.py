"""collect-signals — gather publishing outcome signals for optimization.

Collects survival, dofollow, and drift signals from existing quality gates
(recheck-backlinks, canary_targets, equity_ledger) and writes them into
``optimization_state.json`` for consumption by ``optimize-weights``.
"""

from __future__ import annotations

import argparse
import json
import sys

from backlink_publisher.optimization import OptimizationState
from backlink_publisher.optimization.collector import collect_all_signals


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="collect-signals",
        description="Gather publishing outcome signals into optimization_state.json",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview collected signals without writing to state file",
    )
    parser.add_argument(
        "--source",
        choices=["recheck", "canary", "equity"],
        default=None,
        help="Collect from a single source only (default: all sources)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="Output raw signal data as JSON",
    )

    args = parser.parse_args(argv)

    state = OptimizationState()
    collected = collect_all_signals(
        state,
        dry_run=args.dry_run,
        source_filter=args.source,
    )

    if args.as_json:
        json.dump(collected, sys.stdout, indent=2, ensure_ascii=False)
        sys.stdout.write("\n")
        return

    merged = collected["merged"]
    if not merged:
        print(f"[collect-signals] No signals collected{' (dry-run)' if args.dry_run else ''}")
        return

    summary_lines = []
    for platform, stats in sorted(merged.items()):
        parts = [f"  {platform}:"]
        if stats.get("total_published"):
            parts.append(f"published={stats['total_published']}")
        if stats.get("alive_count"):
            parts.append(f"alive={stats['alive_count']}")
        if stats.get("dofollow_count"):
            parts.append(f"dofollow={stats['dofollow_count']}")
        if stats.get("drift_count"):
            parts.append(f"drift={stats['drift_count']}")
        summary_lines.append("  ".join(parts))

    mode = " (dry-run)" if args.dry_run else ""
    print(f"[collect-signals] Collected signals for {len(merged)} platforms{mode}:")
    for line in summary_lines:
        print(line)

    if not args.dry_run:
        print("[collect-signals] Written to optimization_state.json")


if __name__ == "__main__":
    main()
