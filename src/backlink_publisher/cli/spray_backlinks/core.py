"""``spray-backlinks`` CLI shell — argparse + JSONL I/O + exit-code discipline.

Owns all I/O: reads ONE seed from stdin/``--input``, fans it out across the
selected platforms, and writes publish-ready rows to stdout (data only;
diagnostics to stderr; exit 0 on success). The pure kernel lives in
``_engine`` and never touches ``sys.stdout``.

Unit 1 wires the scaffold + seed expansion. Gating/cap (Unit 2), LLM rewrite +
anchor (Unit 3), the diversity audit + ``--dry-run`` preview (Unit 4), and burst
dispatch (Unit 5) layer onto this shell.
"""

from __future__ import annotations

import sys
from typing import Any

# Populate the adapter registry so registered_platforms() is non-empty when
# argparse help / validation runs.
import backlink_publisher.publishing.adapters  # noqa: F401
from backlink_publisher import config_echo
from backlink_publisher._util.errors import (
    PipelineError,
    UsageError,
    emit_envelope_and_exit,
    handle_error,
)
from backlink_publisher._util.jsonl import read_jsonl, write_jsonl
from backlink_publisher._util.logger import set_log_level
from backlink_publisher.config import load_config
from backlink_publisher.publishing.registry import registered_platforms
from backlink_publisher.schema import validate_input_payload

from ._engine import expand_seed, validate_platform_selection

_LOG_LEVELS = {"DEBUG", "INFO", "WARN", "ERROR"}
_DISPATCH_MODES = {"dry-run", "burst"}
_DEFAULT_CAP = 5


def _build_parser() -> Any:
    import argparse

    parser = argparse.ArgumentParser(
        prog="spray-backlinks",
        description=(
            "Fan one seed out to multiple platforms as publish-ready rows "
            "(operator-invoked drafting verb; emits a reviewable JSONL artifact)."
        ),
    )
    parser.add_argument(
        "--input", "-i",
        type=argparse.FileType("r"),
        default=None,
        help="Input seed JSONL (one row; default: stdin)",
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
        "--log-level",
        default="WARN",
        metavar="LEVEL",
        help="Log verbosity: DEBUG|INFO|WARN|ERROR (default: WARN)",
    )
    return parser


def _parse_platforms(raw: str) -> list[str]:
    return [p.strip() for p in raw.split(",") if p.strip()]


def main(argv: list[str] | None = None) -> None:
    args = _build_parser().parse_args(argv)

    try:
        # Closed-set validation post-parse (repo convention: UsageError exit 1,
        # not argparse choices= exit 2). See [[argparse-choices-vs-usage-error]].
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
        if args.cap < 1:
            raise UsageError("spray-backlinks: --cap must be >= 1")
        set_log_level(args.log_level)

        platforms = validate_platform_selection(
            _parse_platforms(args.platforms), registered_platforms()
        )

        rows = list(read_jsonl(args.input))
        # v1 is single-seed scope: exactly one seed row per invocation.
        if len(rows) != 1:
            raise UsageError(
                f"spray-backlinks: expected exactly 1 seed row, got {len(rows)} "
                "(v1 is single-seed; run once per seed)"
            )
        seed = rows[0]
        seed_errors = validate_input_payload(seed, 1)
        if seed_errors:
            for err in seed_errors:
                print(err, file=sys.stderr)
            emit_envelope_and_exit(
                "InputValidationError", 2,
                f"seed validation failed: {len(seed_errors)} errors",
            )

        cfg = load_config()
        config_echo.emit_banner(cfg, "spray-backlinks")

        candidates = expand_seed(seed, platforms)

        # Unit 1 scaffold: emit the expanded per-platform seed clones. Gating
        # (Unit 2), LLM draft (Unit 3), audit (Unit 4), and burst dispatch
        # (Unit 5) replace this pass-through.
        write_jsonl(c.seed for c in candidates)
    except PipelineError as exc:
        handle_error(exc)


if __name__ == "__main__":
    main()
