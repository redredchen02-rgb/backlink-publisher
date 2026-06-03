"""platform-health CLI verb — Plan 2026-06-03-004 Unit 3.

Prints a per-platform health table to stdout. Reads from
``build_platform_health()`` — no network calls, no side effects.

Usage:
    platform-health
    platform-health --json
    platform-health --platform medium
"""

from __future__ import annotations

import argparse
import json
import sys

from backlink_publisher.config import load_config
from backlink_publisher.health.aggregate import build_platform_health


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="platform-health",
        description="Show per-platform publishing health state.",
    )
    p.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="Emit JSONL (one record per platform) to stdout instead of a table.",
    )
    p.add_argument(
        "--platform",
        metavar="NAME",
        default=None,
        help="Show only the named platform.",
    )
    return p


def _fmt_ts(ts: str | None) -> str:
    if ts is None:
        return "—"
    # Trim microseconds for display.
    return ts[:19].replace("T", " ")


def _print_table(records: list) -> None:
    header = (
        f"{'Platform':<20} {'Last Success':<22} {'Last Failure':<22}"
        f" {'Fails':<7} {'Circuit':<9} {'Paused'}"
    )
    print(header)
    print("-" * len(header))
    for rec in records:
        circuit = "OPEN" if rec.circuit_tripped else "closed"
        paused = "YES" if rec.paused else "no"
        print(
            f"{rec.platform:<20} {_fmt_ts(rec.last_success_at):<22}"
            f" {_fmt_ts(rec.last_failure_at):<22}"
            f" {rec.consecutive_failures:<7} {circuit:<9} {paused}"
        )


def _print_json(records: list) -> None:
    for rec in records:
        obj = {
            "platform": rec.platform,
            "last_success_at": rec.last_success_at,
            "last_failure_at": rec.last_failure_at,
            "last_error_msg": rec.last_error_msg,
            "consecutive_failures": rec.consecutive_failures,
            "circuit_tripped": rec.circuit_tripped,
            "circuit_tripped_at": rec.circuit_tripped_at,
            "paused": rec.paused,
        }
        print(json.dumps(obj))


def main(argv: list[str] | None = None) -> None:
    args = _build_parser().parse_args(argv)

    try:
        cfg = load_config()
    except Exception as exc:
        print(f"platform-health: config load failed: {exc}", file=sys.stderr)
        sys.exit(1)

    health = build_platform_health(cfg)

    records = sorted(health.values(), key=lambda r: r.platform)

    if args.platform is not None:
        records = [r for r in records if r.platform == args.platform]
        if not records:
            print(
                f"platform-health: platform {args.platform!r} not found",
                file=sys.stderr,
            )

    if args.as_json:
        _print_json(records)
    else:
        _print_table(records)
