"""``weights`` — dispatch-weight optimisation CLI (single console_script).

Consolidates the three former console scripts into subcommands:

    weights collect    gather publishing-outcome signals  (was collect-signals)
    weights optimize   run the rules engine, adjust weights (was optimize-weights)
    weights show       display the current state summary   (was show-optimization-state)

``click-track`` stays a separate console script (different concern).

Each subcommand is a thin passthrough: the dispatcher routes the residual
argv to the underlying module's ``main()`` (lazy-imported), which owns its own
argparse (so ``--source``/``--rule`` ``choices=`` validation and ``--help``
behave identically to the old scripts). The old modules stay importable and
``python -m backlink_publisher.cli.<name>`` runnable; only their
``[project.scripts]`` lines are dropped.

The lazy imports below are written as module-level-style ``from ... import``
statements (inside handlers) so the orphan-code scanner — which matches import
text, not runtime imports — still sees the three modules as referenced.
"""

from __future__ import annotations

import argparse
import sys

EXIT_OK = 0


def _handle_collect(rest: list[str]) -> int:
    from backlink_publisher.cli import collect_signals

    return collect_signals.main(rest) or EXIT_OK


def _handle_optimize(rest: list[str]) -> int:
    from backlink_publisher.cli import optimize_weights

    return optimize_weights.main(rest) or EXIT_OK


def _handle_show(rest: list[str]) -> int:
    from backlink_publisher.cli import show_optimization_state

    return show_optimization_state.main(rest) or EXIT_OK


_HANDLERS = {
    "collect": _handle_collect,
    "optimize": _handle_optimize,
    "show": _handle_show,
}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="weights",
        description=(
            "Dispatch-weight optimisation. Subcommands collect signals, run the "
            "rules engine, and show state. (click-track is a separate command.)"
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)
    # add_help=False so `weights <sub> --help` is forwarded to the underlying
    # module's own --help rather than being swallowed by an empty subparser.
    sub.add_parser("collect", add_help=False,
                   help="Gather publishing-outcome signals into optimization_state.json")
    sub.add_parser("optimize", add_help=False,
                   help="Run the rules engine and update platform weights")
    sub.add_parser("show", add_help=False,
                   help="Display the current optimization state summary")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Argparse dispatcher; returns an exit code (no ``sys.exit``) for in-process
    tests. Unknown subcommands / missing subcommand exit 2 (argparse usage)."""
    parser = _build_parser()
    args, rest = parser.parse_known_args(argv)
    return _HANDLERS[args.command](rest)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
