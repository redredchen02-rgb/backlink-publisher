"""backlink-doctor - read-only preflight for producing a first real dofollow backlink.

The operator machine often has *zero* real publish telemetry - the tool has
never produced a real dofollow backlink even though several dofollow platforms
need no credentials at all. This command inspects the adapter registry (and,
best-effort, local config) and prints the shortest path to a first real
backlink, plus the credential gaps blocking the high-value channels.

Contract: machine JSON on stdout (one line); human guidance on stderr; exit 0.
No network, no writes.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any


def build_report(registry_view: list[dict[str, Any]]) -> dict[str, Any]:
    """Classify the registry into actionable buckets (pure - no I/O).

    ``registry_view`` items: ``{"platform": str, "dofollow": bool|str,
    "auth_type": str}`` (already excludes retired platforms).
    """
    ready_now = [
        r["platform"] for r in registry_view
        if r["dofollow"] is True and r["auth_type"] == "anon"
    ]
    high_value_gaps = [
        r["platform"] for r in registry_view
        if r["dofollow"] is True and r["auth_type"] != "anon"
    ]
    uncertain_anon = [
        r["platform"] for r in registry_view
        if r["dofollow"] == "uncertain" and r["auth_type"] == "anon"
    ]
    first = ready_now[0] if ready_now else None
    if first:
        shortest_path = (
            f"{first} needs no account - publish a real dofollow backlink now, e.g.: "
            f"plan-backlinks <seeds> | publish-backlinks --platform {first}"
        )
    else:
        shortest_path = (
            "bind one dofollow=True channel (e.g. ghpages via token) to produce "
            "your first real backlink"
        )
    return {
        "ready_now": ready_now,
        "high_value_gaps": high_value_gaps,
        "uncertain_anon": uncertain_anon,
        "shortest_path": shortest_path,
    }


def _registry_view() -> list[dict[str, Any]]:
    import backlink_publisher.publishing.adapters  # noqa: F401  (populate registry)
    from backlink_publisher.publishing.registry import (
        auth_type,
        dofollow_status,
        registered_platforms,
        visibility,
    )

    view: list[dict[str, Any]] = []
    for platform in registered_platforms():
        if visibility(platform) == "retired":
            continue
        view.append({
            "platform": platform,
            "dofollow": dofollow_status(platform),
            "auth_type": auth_type(platform),
        })
    return view


def _config_gaps() -> list[str]:
    """Best-effort local-config advisories; never raises (returns [] on any issue)."""
    gaps: list[str] = []
    try:

        from backlink_publisher._util.paths import _config_dir

        cfg = _config_dir()
        if not (cfg / "config.toml").is_file():
            gaps.append("config.toml missing - add a [target.*] section with main_url + anchor pools")
        llm = cfg / "llm-settings.json"
        if not llm.is_file():
            gaps.append("llm-settings.json missing - needed to generate article bodies at plan time")
    except Exception:  # noqa: BLE001  (advisory only - a config-dir failure must not break the preflight)
        return []
    return gaps


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="backlink-doctor",
        description="Read-only preflight: the shortest path to a first real dofollow backlink.",
    )
    parser.add_argument("--json", action="store_true", help="suppress the human stderr summary")
    args = parser.parse_args(argv)

    report = build_report(_registry_view())
    report["config_gaps"] = _config_gaps()

    print(json.dumps(report))  # stdout = machine contract

    if not args.json:
        print(f"\nShortest path:  {report['shortest_path']}", file=sys.stderr)
        print(
            f"Ready now (no credentials):  {', '.join(report['ready_now']) or '(none)'}",
            file=sys.stderr,
        )
        print(
            f"High-value dofollow, needs setup:  {', '.join(report['high_value_gaps']) or '(none)'}",
            file=sys.stderr,
        )
        print(
            f"Anonymous 'uncertain' (canary-flip candidates):  "
            f"{', '.join(report['uncertain_anon']) or '(none)'}",
            file=sys.stderr,
        )
        for gap in report["config_gaps"]:
            print(f"  ! {gap}", file=sys.stderr)

    sys.exit(0)


if __name__ == "__main__":
    main()
