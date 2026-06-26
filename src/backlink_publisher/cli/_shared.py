"""Shared CLI utilities — argparse boilerplate, log setup, and config echo.

Extracted from the ~55 CLI entrypoints, many of which independently defined
``_LOG_LEVELS`` and ``set_log_level`` + ``config_echo.emit_banner`` in the same
``if __name__ == '__main__'`` section. This module is the single source of
truth for those patterns.

Usage::

    from backlink_publisher.cli._shared import (
        LOG_LEVELS,
        add_log_level_arg,
        validate_log_level,
        setup_logging,
    )

    def main(argv: list[str] | None = None) -> None:
        import argparse

        parser = argparse.ArgumentParser(prog="my-command")
        add_log_level_arg(parser)
        args = parser.parse_args(argv)
        validate_log_level(args, "my-command")

        cfg = load_config()
        config_sha = setup_logging(args, cfg, "my-command")
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from backlink_publisher._util.errors import UsageError
from backlink_publisher._util.logger import set_log_level

if TYPE_CHECKING:
    import argparse

    from backlink_publisher.config import Config

#: Canonical log-level set shared by all CLI entrypoints.
#: Always use ``LOG_LEVELS`` instead of redefining ``_LOG_LEVELS`` in each file.
LOG_LEVELS: frozenset[str] = frozenset({"DEBUG", "INFO", "WARN", "ERROR"})

_DEFAULT_LOG_LEVEL = "WARN"


def add_log_level_arg(parser: argparse.ArgumentParser) -> None:
    """Add a ``--log-level`` argument without argparse-level ``choices``.

    Uses ``metavar`` only — validation is deferred to :func:`validate_log_level`
    so the codebase's convention of ``UsageError`` (exit 1) is preserved instead
    of argparse's built-in ``ArgumentTypeError`` (exit 2).

    The ``choices`` parameter is deliberately omitted; see
    ``canary_targets.py`` for the rationale.

    Files that previously defined ``_LOG_LEVELS = {"DEBUG", "INFO", "WARN", "ERROR"}``
    can remove that constant and import from here instead.
    """
    parser.add_argument(
        "--log-level",
        default=_DEFAULT_LOG_LEVEL,
        metavar="LEVEL",
        help=f"Log verbosity: {'|'.join(sorted(LOG_LEVELS))} (default: {_DEFAULT_LOG_LEVEL})",
    )


def validate_log_level(args: argparse.Namespace, cli_name: str) -> None:
    """Validate ``args.log_level`` against ``LOG_LEVELS``; raise ``UsageError``
    on mismatch. This mirrors the codebase convention of exit 1 (UsageError)
    instead of argparse's default exit 2.
    """
    if hasattr(args, "log_level") and args.log_level not in LOG_LEVELS:
        raise UsageError(
            f"{cli_name}: --log-level must be one of {sorted(LOG_LEVELS)}; "
            f"got {args.log_level!r}"
        )


def setup_logging(
    args: argparse.Namespace,
    config: Config,
    cli_name: str,
) -> str:
    """Apply ``--log-level`` and emit the config banner.

    Call this after ``load_config()``. Returns the config SHA for downstream
    stamping (e.g. into JSONL metadata).
    """
    if hasattr(args, "log_level") and args.log_level:
        set_log_level(args.log_level)

    from backlink_publisher.config_echo import emit_banner

    return emit_banner(config, cli_name)
