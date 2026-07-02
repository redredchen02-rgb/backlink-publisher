#!/usr/bin/env python3
"""CI benchmark diff gate — compare a PR's pytest-benchmark JSON against main's.

Used by the ``benchmark`` job in ``.github/workflows/ci.yml`` (Plan
2026-06-30-001 §C2). Loads two ``--benchmark-json`` result files (one from
main's last successful CI run, one from the current run), diffs the ``mean``
timing per benchmark by ``fullname``, and flags anything that regressed
beyond ``--threshold-pct``.

Warn-only by design: this always exits 0. It mirrors the "advisory
(warn-only)" contract already documented in ``tests/test_benchmarks.py``'s
module docstring, and the threshold itself starts deliberately lenient (see
the ``--threshold-pct`` default and the rationale comment next to its use in
ci.yml) — pytest-benchmark wall-clock timings on shared GitHub-hosted
runners are noisy enough on their own that a strict, hard-failing gate would
punish runner noise rather than real regressions. Tighten (and consider
hard-failing) once real-world variance across several weeks of runs
establishes the noise floor.

Usage:
  compare_benchmarks.py --baseline baseline/benchmark-result.json \\
      --current benchmark-result.json [--threshold-pct 20]

If ``--baseline`` does not exist (e.g. first run after enabling this gate,
or the baseline-artifact fetch step failed), the comparison is skipped with
a warning rather than treated as an error.

Exit code: always 0 (warn-only — see module docstring).
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys


def _load_means(path: Path) -> dict[str, float]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return {b["fullname"]: b["stats"]["mean"] for b in data["benchmarks"]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True, type=Path,
                         help="Path to main's --benchmark-json result file.")
    parser.add_argument("--current", required=True, type=Path,
                         help="Path to this run's --benchmark-json result file.")
    parser.add_argument("--threshold-pct", type=float, default=20.0,
                         help="Warn if a benchmark's mean regresses more than this "
                              "percent vs baseline (default: 20.0).")
    args = parser.parse_args(argv)

    if not args.baseline.exists():
        print("::warning::No main-branch benchmark baseline available for "
              "comparison (first run after enabling C2, or baseline artifact "
              "fetch failed) - skipping regression check.")
        return 0

    if not args.current.exists():
        print(f"::warning::Current benchmark result file {args.current} not "
              f"found - skipping regression check.")
        return 0

    baseline = _load_means(args.baseline)
    current = _load_means(args.current)

    regressions: list[tuple[str, float]] = []
    summary_lines = [
        "| Benchmark | main (mean s) | PR (mean s) | Change |",
        "|---|---|---|---|",
    ]
    for name, pr_mean in current.items():
        base_mean = baseline.get(name)
        if base_mean is None:
            summary_lines.append(f"| `{name}` | n/a (new) | {pr_mean:.6f} | - |")
            continue
        pct_change = (pr_mean - base_mean) / base_mean * 100
        flag = ""
        if pct_change > args.threshold_pct:
            flag = " (regression)"
            regressions.append((name, pct_change))
        summary_lines.append(
            f"| `{name}` | {base_mean:.6f} | {pr_mean:.6f} | {pct_change:+.1f}%{flag} |"
        )

    summary = "\n".join(summary_lines)
    print(summary)

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as f:
            f.write("### Benchmark comparison vs main\n\n" + summary + "\n")

    if regressions:
        for name, pct in regressions:
            print(f"::warning::Benchmark '{name}' regressed {pct:.1f}% vs main "
                  f"baseline (threshold: {args.threshold_pct:.0f}%, warn-only "
                  f"per tests/test_benchmarks.py)")
    else:
        print(f"No benchmarks regressed beyond the {args.threshold_pct:.0f}% "
              f"warn-only threshold.")

    return 0  # warn-only — see module docstring


if __name__ == "__main__":
    sys.exit(main())
