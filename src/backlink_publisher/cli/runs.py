"""``bp runs`` — list incomplete checkpoint runs.

Surfaces the same data as ``publish-backlinks --list-runs`` but as a
standalone entrypoint so operators can inspect state without remembering
which sub-command holds the flag.

Exit codes:
  0 — success (even if zero runs found)
  1 — unexpected error reading checkpoint directory
"""
from __future__ import annotations

import json
import sys


def _print_table(runs: list[dict]) -> None:
    print(f"{'RUN_ID':<32}  {'STARTED':<26}  {'PENDING':>7}  {'FAILED':>7}")
    print("-" * 76)
    for run in runs:
        pending = sum(1 for i in run.get("items", []) if i.get("status") == "pending")
        failed = sum(1 for i in run.get("items", []) if i.get("status") == "failed")
        print(
            f"{run.get('run_id', ''):<32}  "
            f"{run.get('started_at', ''):<26}  "
            f"{pending:>7}  {failed:>7}"
        )


def main(argv: list[str] | None = None) -> None:
    import argparse
    from backlink_publisher import checkpoint

    parser = argparse.ArgumentParser(
        prog="bp-runs",
        description="List incomplete (resumable) publish-backlinks runs.",
    )
    parser.add_argument(
        "--jsonl",
        action="store_true",
        help="Emit one JSON object per run to stdout instead of a table.",
    )
    parser.add_argument(
        "--all",
        dest="all_runs",
        action="store_true",
        help="Include completed runs (default: incomplete only).",
    )
    args = parser.parse_args(argv)

    try:
        if args.all_runs:
            runs = checkpoint.list_all_runs()
        else:
            runs = checkpoint.list_incomplete()
    except Exception as exc:
        print(f"error reading checkpoints: {exc}", file=sys.stderr)
        raise SystemExit(1)

    if not runs:
        if not args.jsonl:
            print("No incomplete runs." if not args.all_runs else "No runs found.")
        raise SystemExit(0)

    if args.jsonl:
        for run in runs:
            summary = {
                "run_id": run.get("run_id"),
                "started_at": run.get("started_at"),
                "platform": run.get("platform"),
                "mode": run.get("mode"),
                "pending": sum(1 for i in run.get("items", []) if i.get("status") == "pending"),
                "failed": sum(1 for i in run.get("items", []) if i.get("status") == "failed"),
                "resume_cmd": f"resume {run.get('run_id')}",
            }
            print(json.dumps(summary))
    else:
        _print_table(runs)
        print(
            f"\nResume a run: resume <run_id>  "
            f"(or: publish-backlinks --resume <run_id>)"
        )

    raise SystemExit(0)
