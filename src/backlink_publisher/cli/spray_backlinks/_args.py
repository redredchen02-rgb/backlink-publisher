"""Argparse construction and post-parse validation for ``spray-backlinks``.

Extracted from ``core.py`` (plan 2026-07-06-003 U6, completing the Wave 3
Unit 1 split). Self-contained: builds the parser, parses comma-separated
platform lists, and enforces the closed-set flag contract via ``UsageError``
(exit-code discipline) rather than argparse ``choices=``.
"""

from __future__ import annotations

from typing import Any

from backlink_publisher._util.errors import UsageError

_LOG_LEVELS = {"DEBUG", "INFO", "WARN", "ERROR"}
_DISPATCH_MODES = {"dry-run", "burst"}
_DEFAULT_CAP = 5
_DEFAULT_MAX_SEEDS = 10


def _build_parser() -> Any:
    import argparse

    parser = argparse.ArgumentParser(
        prog="spray-backlinks",
        description=(
            "Fan one or more seeds out to multiple platforms as publish-ready rows "
            "(operator-invoked drafting verb)."
        ),
    )
    parser.add_argument(
        "--input", "-i",
        type=argparse.FileType("r"),
        default=None,
        help="Input seed JSONL (one or more rows; default: stdin)",
    )
    parser.add_argument(
        "--max-seeds",
        type=int,
        default=_DEFAULT_MAX_SEEDS,
        metavar="N",
        help=f"Max seeds to accept (default: {_DEFAULT_MAX_SEEDS})",
    )
    parser.add_argument(
        "--seed-delay-min",
        type=int,
        default=None,
        metavar="SECONDS",
        help="Min inter-seed delay in seconds (opt-in; default: no delay)",
    )
    parser.add_argument(
        "--seed-delay-max",
        type=int,
        default=None,
        metavar="SECONDS",
        help="Max inter-seed delay in seconds (opt-in; default: no delay)",
    )
    parser.add_argument(
        "--platforms",
        default="",
        metavar="A,B,C",
        help="Comma-separated platforms to fan out to (operator selection)",
    )
    parser.add_argument(
        "--cap",
        type=int,
        default=_DEFAULT_CAP,
        metavar="N",
        help=f"Hard max platforms per seed (blast-radius cap; default: {_DEFAULT_CAP})",
    )
    parser.add_argument(
        "--dispatch",
        default="dry-run",
        metavar="MODE",
        help="dry-run (preview only, no side effects) | burst (default: dry-run)",
    )
    parser.add_argument(
        "--mode",
        default="draft",
        metavar="MODE",
        help="Publish mode for burst dispatch: draft | publish (default: draft)",
    )
    parser.add_argument(
        "--force",
        default="",
        metavar="A,B",
        help=(
            "Comma-separated platforms to keep despite a soft health/quality "
            "gate warning (the override reason is recorded). The hard cap and "
            "cell gate are NOT overridable."
        ),
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        metavar="DIR",
        help="Per-seed output directory (one JSONL file per seed; default: stdout)",
    )
    parser.add_argument(
        "--resume",
        default=None,
        metavar="RUN_ID",
        help="Resume a previous run by run_id (skips completed seeds, retries failures)",
    )
    parser.add_argument(
        "--list-checkpoints",
        action="store_true",
        default=False,
        help="List recent spray-backlinks checkpoints and exit",
    )
    parser.add_argument(
        "--no-fetch-verify",
        action="store_true",
        default=False,
        help="Skip the plan-time URL content gate (dev/replay/offline targets)",
    )
    parser.add_argument(
        "--log-level",
        default="WARN",
        metavar="LEVEL",
        help="Log verbosity: DEBUG|INFO|WARN|ERROR (default: WARN)",
    )
    parser.add_argument(
        "--profile",
        action="store_true",
        default=False,
        help="Enable cProfile profiling (saved to ~/.cache/backlink-publisher/profiles/)",
    )
    return parser


def _parse_platforms(raw: str) -> list[str]:
    return [p.strip() for p in raw.split(",") if p.strip()]


def _validate_args(args: Any) -> None:
    """Post-parse closed-set validation. Raises UsageError on violations."""
    if args.log_level not in _LOG_LEVELS:
        raise UsageError(
            f"spray-backlinks: --log-level must be one of {sorted(_LOG_LEVELS)}; "
            f"got {args.log_level!r}"
        )
    if args.dispatch not in _DISPATCH_MODES:
        raise UsageError(
            f"spray-backlinks: --dispatch must be one of {sorted(_DISPATCH_MODES)}; "
            f"got {args.dispatch!r}"
        )
    if args.mode not in {"draft", "publish"}:
        raise UsageError(
            f"spray-backlinks: --mode must be draft|publish; got {args.mode!r}"
        )
    if args.cap < 1:
        raise UsageError("spray-backlinks: --cap must be >= 1")
    if args.max_seeds < 1:
        raise UsageError("spray-backlinks: --max-seeds must be >= 1")
    if args.seed_delay_min is not None and args.seed_delay_min < 1:
        raise UsageError("spray-backlinks: --seed-delay-min must be >= 1")
    if args.seed_delay_max is not None and args.seed_delay_max < 1:
        raise UsageError("spray-backlinks: --seed-delay-max must be >= 1")
    if (
        args.seed_delay_min is not None
        and args.seed_delay_max is not None
        and args.seed_delay_min > args.seed_delay_max
    ):
        raise UsageError(
            "spray-backlinks: --seed-delay-min must be <= --seed-delay-max"
        )
