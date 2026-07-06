"""optimize-weights — apply optimisation rules to adjust platform weights.

Evaluates Rule 1 (canary_drift) and Rule 2 (recheck_survival) against the
current ``optimization_state.json`` and writes any weight changes.
"""

from __future__ import annotations

import argparse
import sys

from backlink_publisher.optimization import OptimizationState
from backlink_publisher.optimization.rules import (
    apply_results,
    evaluate_rules,
    RULE_AGGREGATED_STATS,
    RULE_CANARY_DRIFT,
    RULE_RECHECK_SURVIVAL,
)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="optimize-weights",
        description="Run rules engine and update platform weights",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview weight changes without writing to state file",
    )
    parser.add_argument(
        "--rule",
        type=str,
        choices=[RULE_CANARY_DRIFT, RULE_RECHECK_SURVIVAL, RULE_AGGREGATED_STATS],
        default=None,
        help="Run a specific rule only (default: all enabled rules)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="Output results as JSON",
    )

    args = parser.parse_args(argv)

    state = OptimizationState()
    data = state.load()
    results = evaluate_rules(data, rule_filter=args.rule)

    if args.as_json:
        import json
        json.dump(
            [r.__dict__ for r in results],
            sys.stdout, indent=2, ensure_ascii=False,
        )
        sys.stdout.write("\n")
        return

    if not results:
        print("[optimize-weights] No rules evaluated (no platforms with data)")
        return

    applied_count = 0
    for r in results:
        symbol = "✓" if r.applied else "–"
        print(f"  {symbol} {r.platform:20s}  {r.rule_name:20s}  {r.old_weight:>5.2f} → {r.new_weight:>5.2f}  ({r.reason})")
        if r.applied:
            applied_count += 1

    if args.dry_run:
        print(f"[optimize-weights] dry-run: {applied_count} changes previewed (not applied)")
    else:
        applied = apply_results(state, results)
        print(f"[optimize-weights] {applied} weight changes applied")


if __name__ == "__main__":
    main()
