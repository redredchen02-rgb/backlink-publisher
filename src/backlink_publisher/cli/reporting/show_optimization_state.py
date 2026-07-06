"""show-optimization-state — display the current optimization state summary.
"""

from __future__ import annotations

import argparse
import json
import sys

from backlink_publisher.optimization import OptimizationState


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="show-optimization-state",
        description="Display the current optimization state",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output raw state as JSON",
    )
    parser.add_argument(
        "--platform",
        type=str,
        default=None,
        help="Filter to a single platform (default: all platforms)",
    )

    args = parser.parse_args(argv)

    state = OptimizationState()
    summary = state.to_summary()
    platforms = summary.get("platforms", [])

    if args.platform:
        platforms = [p for p in platforms if p.get("name") == args.platform]

    if args.json:
        json.dump(summary, sys.stdout, indent=2, ensure_ascii=False)
        sys.stdout.write("\n")
        return

    if not platforms:
        print("[show-optimization-state] No platform data")
        return

    print(f"[show-optimization-state] {len(platforms)} platform(s) tracked")
    for p in sorted(platforms, key=lambda x: x.get("name", "")):
        name = p.get("name", "?")
        cur = p.get("current", "N/A")
        base = p.get("base", "N/A")
        delta = p.get("delta_pct", 0)
        adj = p.get("adjustment_count", 0)
        s = p.get("stats", {})
        alive = s.get("alive_count", 0)
        total = s.get("total_published", 0)
        drifts = s.get("drift_count", 0)
        updated = p.get("updated_at", "-")[:19]  # trim microseconds
        print(
            f"  {name:20s}  weight={cur:>6}  "
            f"(base={base}, Δ={delta:+.1f}%, adj={adj})  "
            f"alive={alive}  total={total}  drift={drifts}  [{updated}]"
        )
    lu = summary.get("last_updated")
    if lu:
        print(f"  last_updated: {lu[:19]}")
    print(f"  state file: {state.path}")


if __name__ == "__main__":
    main()
