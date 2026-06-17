"""``resume <run_id>`` — resume an interrupted publish-backlinks run.

Thin wrapper around ``publish-backlinks --resume <run_id>``.  Exists so
operators have a memorable, tab-completable entrypoint without needing to
recall which sub-command owns the --resume flag.

Exit codes match publish-backlinks: 0 success, 1 failure, 2 usage error.
"""
from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> None:
    import argparse
    from backlink_publisher import checkpoint
    from backlink_publisher._util.errors import emit_error

    parser = argparse.ArgumentParser(
        prog="resume",
        description="Resume an interrupted publish-backlinks run.",
    )
    parser.add_argument(
        "run_id",
        help="Run ID to resume (from `bp runs` or `publish-backlinks --list-runs`).",
    )
    args = parser.parse_args(argv)

    # Validate run_id format and existence before delegating.
    try:
        checkpoint._validate_run_id(args.run_id)
    except ValueError as exc:
        emit_error(str(exc), exit_code=2)

    path = checkpoint.checkpoint_path(args.run_id)
    if not path.exists():
        emit_error(
            f"no checkpoint found for run_id {args.run_id!r} "
            f"(expected: {path})",
            exit_code=2,
        )

    # Delegate to the full publish-backlinks dispatch layer which owns all the
    # retry / auth-refresh / gate logic.  Pass through any remaining argv so
    # operators can still supply e.g. --dry-run on a resume.
    from backlink_publisher.cli.publish_backlinks import main as pub_main

    pub_main(["--resume", args.run_id] + sys.argv[2:])
