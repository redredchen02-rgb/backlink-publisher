"""dispatch-backlinks — Signal-aware platform routing engine (CLI).

Reads plan-backlinks JSONL from stdin, assigns optimal publishing platform
per row based on live signals (registry metadata, channel binding, canary
health, ledger coverage), and outputs platform-annotated JSONL to stdout.

Pipe: plan-backlinks | dispatch-backlinks | publish-backlinks

Plan 2026-06-03-002.
"""

from __future__ import annotations

import sys

import backlink_publisher.publishing.adapters  # noqa: F401  populate registry
from .. import config_echo
from backlink_publisher._util.errors import emit_error
from backlink_publisher._util.jsonl import read_jsonl, write_jsonl
from backlink_publisher._util.logger import publish_logger as log
from backlink_publisher.config import load_config
from backlink_publisher.dispatch import collect_all, route
from webui_store.channel_status import channel_status_store

# Available strategy choices.
_STRATEGY_CHOICES = ("balanced", "quality", "spread")


def _load_ledger_map(path: str | None) -> dict[str, dict] | None:
    """Load pre-computed equity-ledger JSONL from a file path.

    Returns a dict[target_url, LedgerRow dict] or None if no path given.
    """
    if path is None:
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            rows = list(read_jsonl(fh, strict=True))
    except (OSError, ValueError) as exc:
        log.warning(f"dispatch-backlinks: cannot read --equity-ledger: {exc}")
        return None

    if not rows:
        log.warning("dispatch-backlinks: --equity-ledger file is empty")
        return None

    return {row.get("target_url", ""): row for row in rows if row.get("target_url")}


def main(argv: list[str] | None = None) -> None:
    import argparse

    parser = argparse.ArgumentParser(
        prog="dispatch-backlinks",
        description=(
            "Signal-aware platform routing: read plan-backlinks JSONL from stdin "
            "and output platform-annotated JSONL to stdout. Each row gets a "
            "'platform' field assigned by a multi-signal scoring engine. "
            "Compose: plan-backlinks | dispatch-backlinks | publish-backlinks."
        ),
    )
    parser.add_argument(
        "--strategy", choices=_STRATEGY_CHOICES, default="balanced",
        help="Routing strategy: balanced (default), quality, or spread.",
    )
    parser.add_argument(
        "--platform", default=None, metavar="NAME",
        help="Override: assign ALL rows to this platform (skip routing).",
    )
    parser.add_argument(
        "--equity-ledger", default=None, metavar="FILE",
        help="Path to pre-computed equity-ledger JSONL for spread analysis.",
    )
    parser.add_argument(
        "--canary-stale-days", type=int, default=None, metavar="N",
        help="Downgrade dofollow confidence if canary data is older than N days "
             "(default: 7; 0 = disable).",
    )
    parser.add_argument("--log-level", default="WARN",
                        help="Set log level (DEBUG, INFO, WARN; default: WARN).")
    args = parser.parse_args(argv)

    from backlink_publisher._util.logger import set_log_level
    set_log_level(args.log_level)

    # --platform override: skip routing entirely
    if args.platform is not None:
        from backlink_publisher.schema import reject_unsupported_platform
        msg = reject_unsupported_platform(args.platform)
        if msg is not None:
            emit_error(f"dispatch-backlinks: {msg}", exit_code=1)

    cfg = load_config()
    config_echo.emit_banner(cfg, "dispatch-backlinks")

    # Buffer stdin for empty-input handling
    lines = sys.stdin.read().split("\n")
    if not any(line.strip() for line in lines):
        log.info("dispatch-backlinks: empty input (no rows to dispatch)")
        return  # Nothing to process — exit 0 with no stdout

    rows = list(read_jsonl(lines, strict=True))
    if not rows:
        log.info("dispatch-backlinks: empty input (no rows to dispatch)")
        return

    log.info(f"dispatch-backlinks: {len(rows)} row(s) to process on stdin")

    # ── Resolve signals ──────────────────────────────────────────────
    channel_data = channel_status_store.load() or {}
    signals = collect_all(channel_data=channel_data)
    log.info(
        f"dispatch-backlinks: collected signals for "
        f"{len(signals)} active platform(s)"
    )

    ledger_map = _load_ledger_map(args.equity_ledger)
    if ledger_map is None:
        log.warning(
            "dispatch-backlinks: no equity-ledger data — "
            "spread/spread bonuses will use round-robin within tiers"
        )

    if not ledger_map and args.strategy in ("balanced", "spread"):
        log.warning(
            f"dispatch-backlinks: --strategy is '{args.strategy}' but no "
            f"equity-ledger data available. Spread analysis is degraded to "
            f"round-robin within tiers."
        )

    # ── Route each row ───────────────────────────────────────────────
    output_rows: list[dict] = []
    total_platforms: dict[str, int] = {}
    total_errors = 0

    for idx, row in enumerate(rows):
        if args.platform is not None:
            # --platform override: skip routing logic entirely
            out = dict(row)
            out["platform"] = args.platform
            out["_dispatch"] = {
                "strategy": "manual",
                "engine_version": 1,
                "reason": f"--platform={args.platform} override",
            }
            output_rows.append(out)
            total_platforms[args.platform] = total_platforms.get(args.platform, 0) + 1
            continue

        result = route(
            row,
            signals=signals,
            ledger_map=ledger_map,
            strategy=args.strategy,
            canary_stale_days=args.canary_stale_days,
        )

        out = dict(row)
        if result.platform is not None:
            out["platform"] = result.platform
            total_platforms[result.platform] = (
                total_platforms.get(result.platform, 0) + 1
            )
        else:
            total_errors += 1
        out["_dispatch"] = result.dispatch
        output_rows.append(out)

    # ── Emit output ──────────────────────────────────────────────────
    write_jsonl(output_rows, sys.stdout)

    # ── Stderr summary ───────────────────────────────────────────────
    if total_errors == len(rows):
        # All rows failed — exit 6
        print(
            f"dispatch-backlinks: ERROR — no suitable platform for any of "
            f"{len(rows)} row(s). Check channel binding, canary health, "
            f"and language configuration.",
            file=sys.stderr,
        )
        raise SystemExit(6)

    summary_parts = [
        f"dispatch-backlinks: assigned {len(rows)} row(s) across "
        f"{len(total_platforms)} platform(s)"
    ]
    if total_errors:
        summary_parts.append(f"{total_errors} row(s) had no suitable platform")
    if total_platforms:
        parts = ", ".join(
            f"{name}={count}" for name, count in
            sorted(total_platforms.items(), key=lambda x: -x[1])
        )
        summary_parts.append(f"({parts})")
    print("; ".join(summary_parts), file=sys.stderr)
