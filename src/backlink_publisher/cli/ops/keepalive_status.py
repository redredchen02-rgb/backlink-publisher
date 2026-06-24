"""keepalive-status — loop health summary (plan 2026-06-05-004 U5).

Shows last cycle timestamp, gap/publish/alive statistics, platform health from
optimization_state.json, and exhausted target list.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def _relative_ts(iso: str | None) -> str:
    if not iso:
        return "never"
    try:
        from datetime import datetime, timezone
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        dt = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - dt
        secs = int(delta.total_seconds())
        if secs < 60:
            return f"{secs}s ago"
        if secs < 3600:
            return f"{secs // 60}m ago"
        if secs < 86400:
            return f"{secs // 3600}h ago"
        return f"{secs // 86400}d ago"
    except Exception:
        return iso or "never"


def _build_status(data_dir: Path | None = None) -> dict:
    from backlink_publisher.keepalive.run_state import KeepaliveRunState
    from backlink_publisher.optimization.state import OptimizationState

    rs = KeepaliveRunState(data_dir=data_dir)
    rs_data = rs.load()

    opt = OptimizationState(data_dir=data_dir)
    opt_data = opt.load()

    platform_health = []
    # opt_data is v2: weights/stats are nested under a language namespace.
    weights = opt_data.get("weights", {}).get("default", {})
    stats = opt_data.get("stats", {}).get("default", {})
    for name, wentry in weights.items():
        current = float(wentry.get("current", 1.0))
        pstats = stats.get(name, {})
        alive = int(pstats.get("alive_count", 0))
        total = int(pstats.get("total_published", 0))
        alive_rate = alive / total if total > 0 else None
        platform_health.append({
            "platform": name,
            "weight": current,
            "alive_rate": alive_rate,
            "circuit_broken": current == 0.0,
        })

    exhausted = []
    max_retry = rs.MAX_RETRY
    for url, entry in rs_data.get("retry_counts", {}).items():
        if int(entry.get("attempts", 0)) >= max_retry:
            exhausted.append({
                "url": url,
                "attempts": entry.get("attempts", 0),
                "last_outcome": entry.get("last_outcome"),
                "platforms_tried": entry.get("platforms_tried", []),
            })

    return {
        "last_run_at": rs_data.get("last_run_at"),
        "last_cycle": rs_data.get("last_cycle_summary", {}),
        "platform_health": platform_health,
        "exhausted_targets": exhausted,
    }


def main(argv: list[str] | None = None) -> None:
    import argparse

    parser = argparse.ArgumentParser(
        prog="keepalive-status",
        description="Show keep-alive loop health summary",
    )
    parser.add_argument(
        "--json", action="store_true", dest="as_json",
        help="Machine-readable JSON output",
    )
    parser.add_argument(
        "--platform", metavar="P",
        help="Filter platform health to this platform",
    )
    parser.add_argument(
        "--reset-exhausted", metavar="URL",
        help="Remove URL from exhausted list (operator reset)",
    )
    args = parser.parse_args(argv)

    from backlink_publisher.keepalive.run_state import KeepaliveRunState

    if args.reset_exhausted:
        rs = KeepaliveRunState()
        rs.reset_exhausted(args.reset_exhausted)
        print(f"keepalive-status: reset exhausted — {args.reset_exhausted}", file=sys.stderr)

    status = _build_status()

    if args.as_json:
        print(json.dumps(status, ensure_ascii=False, indent=2))
        return

    last_run = status["last_run_at"]
    cycle = status["last_cycle"]
    health = status["platform_health"]
    exhausted = status["exhausted_targets"]

    if args.platform:
        health = [h for h in health if h["platform"] == args.platform]

    if last_run is None:
        print("No keepalive cycle has run yet.")
        print("Run `backlink-publisher keepalive-run` to start.")
        return

    print(f"Last run: {last_run} ({_relative_ts(last_run)})")
    if cycle:
        print(
            f"Cycle summary: gaps_found={cycle.get('gaps_found', 0)}, "
            f"published={cycle.get('published', 0)}, "
            f"alive={cycle.get('reverified_alive', 0)}, "
            f"dead={cycle.get('reverified_dead', 0)}, "
            f"skipped_exhausted={cycle.get('exhausted_skipped', 0)}"
        )
    print()
    if health:
        print("Platform Health (from optimization_state.json):")
        for h in health:
            rate = f"{h['alive_rate']:.0%}" if h["alive_rate"] is not None else "n/a"
            circuit = "  CIRCUIT-BROKEN" if h["circuit_broken"] else ""
            print(f"  {h['platform']:<12} weight={h['weight']:.2f}  alive_rate={rate}{circuit}")
    else:
        print("Platform Health: no data (run optimize-weights first)")
    print()
    if exhausted:
        print(f"Exhausted Targets (retry >= {KeepaliveRunState().MAX_RETRY}):")
        for e in exhausted:
            tried = ", ".join(e.get("platforms_tried") or [])
            print(f"  {e['url']}  (attempts={e['attempts']}, tried: {tried})")
    else:
        print("Exhausted Targets: (none)")
