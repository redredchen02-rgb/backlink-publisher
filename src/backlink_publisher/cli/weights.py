"""``weights`` — Optimization-weight management CLI (single console_script, subparsers).

Subcommands:
    weights collect   gather publishing outcome signals into optimization_state.json
    weights optimize  apply rules engine and update platform weights
    weights show      display current optimization state summary

``click-track`` stays a separate console_script (distinct concern).
"""

from __future__ import annotations

import argparse
import sys

EXIT_OK = 0


# ---------------------------------------------------------------------------
# Handlers — thin shims; bodies live in the three dedicated CLI modules.
# ---------------------------------------------------------------------------

def _handle_collect(args: argparse.Namespace) -> int:
    from backlink_publisher.cli.collect_signals import main as _collect_main
    argv: list[str] = []
    if args.dry_run:
        argv.append("--dry-run")
    if args.source:
        argv += ["--source", args.source]
    if args.as_json:
        argv.append("--json")
    _collect_main(argv)
    return EXIT_OK


def _handle_optimize(args: argparse.Namespace) -> int:
    from backlink_publisher.cli.optimize_weights import main as _optimize_main
    argv: list[str] = []
    if args.dry_run:
        argv.append("--dry-run")
    if args.rule:
        argv += ["--rule", args.rule]
    if args.as_json:
        argv.append("--json")
    _optimize_main(argv)
    return EXIT_OK


def _handle_show(args: argparse.Namespace) -> int:
    from backlink_publisher.cli.show_optimization_state import main as _show_main
    argv: list[str] = []
    if args.as_json:
        argv.append("--json")
    if args.platform:
        argv += ["--platform", args.platform]
    _show_main(argv)
    return EXIT_OK


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    from backlink_publisher.optimization.rules import (
        RULE_AGGREGATED_STATS,
        RULE_CANARY_DRIFT,
        RULE_RECHECK_SURVIVAL,
    )

    parser = argparse.ArgumentParser(
        prog="weights",
        description=(
            "Optimization-weight management — collect signals, run rules engine, "
            "and inspect current platform weights."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # --- collect ---
    collect_p = sub.add_parser(
        "collect",
        help="Gather publishing outcome signals into optimization_state.json",
    )
    collect_p.add_argument("--dry-run", action="store_true",
                           help="Preview without writing to state file")
    collect_p.add_argument("--source", choices=["recheck", "canary", "equity"],
                           default=None, help="Collect from a single source only")
    collect_p.add_argument("--lang", default=None,
                           help="Filter signals to a specific language (e.g. zh-CN, en)")
    collect_p.add_argument("--json", action="store_true", dest="as_json",
                           help="Output raw signal data as JSON")
    collect_p.set_defaults(handler=_handle_collect)

    # --- optimize ---
    optimize_p = sub.add_parser(
        "optimize",
        help="Run rules engine and update platform weights",
    )
    optimize_p.add_argument("--dry-run", action="store_true",
                            help="Preview weight changes without writing")
    optimize_p.add_argument("--lang", default=None,
                            help="Filter optimization to a specific language (e.g. zh-CN, en)")
    optimize_p.add_argument(
        "--rule",
        choices=[RULE_CANARY_DRIFT, RULE_RECHECK_SURVIVAL, RULE_AGGREGATED_STATS],
        default=None,
        help="Run a specific rule only (default: all enabled rules)",
    )
    optimize_p.add_argument("--json", action="store_true", dest="as_json",
                            help="Output results as JSON")
    optimize_p.set_defaults(handler=_handle_optimize)

    # --- show ---
    show_p = sub.add_parser(
        "show",
        help="Display current optimization state summary",
    )
    show_p.add_argument("--json", action="store_true", dest="as_json",
                        help="Output raw state as JSON")
    show_p.add_argument("--lang", default=None,
                        help="Filter display to a specific language (e.g. zh-CN, en)")
    show_p.add_argument("--platform", default=None,
                        help="Filter to a single platform")
    show_p.set_defaults(handler=_handle_show)

    return parser


def main(argv: list[str] | None = None) -> int:
    """Argparse dispatcher. Returns an exit code (never calls sys.exit directly)."""
    parser = _build_parser()
    args = parser.parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
