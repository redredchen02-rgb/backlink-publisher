"""bp — grouped overview of all backlink-publisher CLI commands."""
from __future__ import annotations

GROUPS: list[tuple[str, list[tuple[str, str]]]] = [
    ("Pipeline", [
        ("plan-backlinks",         "Generate article payloads from seed URLs"),
        ("validate-backlinks",     "Validate planned payloads before publishing"),
        ("publish-backlinks",      "Publish validated payloads to target platforms"),
        ("recheck-backlinks",      "Re-verify liveness of published links"),
        ("dispatch-backlinks",     "Route payloads to configured channel adapters"),
        ("spray-backlinks",        "Publish across all available channels at once"),
        ("phase0-seal",            "Seal a pipeline run and write the phase-0 report"),
        ("report-anchors",         "Report anchor text distribution for a plan"),
    ]),
    ("Channel", [
        ("bind-channel",           "Register a new publishing channel"),
        ("velog-login",            "Authenticate with Velog and store credentials"),
        ("medium-login",           "Authenticate with Medium and store credentials"),
        ("frw-login",              "Authenticate with FRW and store credentials"),
        ("cull-channels",          "Remove unhealthy or stale channels"),
        ("keepalive-run",          "Run one keepalive cycle for all channels"),
        ("keepalive-status",       "Show keepalive loop health summary"),
        ("keepalive-reset-exhausted", "Clear exhausted retry state for a target URL"),
    ]),
    ("Analysis", [
        ("plan-gap",               "Identify content gaps relative to target pages"),
        ("pr-opportunities",       "Find PageRank link-building opportunities"),
        ("weights",                "Show or update platform scoring weights"),
        ("equity-ledger",          "Report link equity distribution"),
        ("footprint",              "Analyse publishing footprint for a seed set"),
        ("click-track",            "Track click-through events from published links"),
        ("generate-backlink-text", "Generate anchor text for a target URL"),
        ("canonical-expand",       "Expand canonical URLs for a seed list"),
        ("comment",                "Post a contextual comment backlink"),
        ("probe-citations",        "Check citation coverage for target URLs"),
        ("probe-index",            "Probe GSC for page-signal indexation status"),
        ("probe-ranking",          "Snapshot keyword ranking positions from GSC"),
        ("publish-metrics",        "Compute and report publish reliability metrics"),
        ("referral-attribute",     "Attribute referral traffic to published backlinks"),
    ]),
    ("Diagnostics", [
        ("gate-probe",             "Run a phase-0 gate probe and report result"),
        ("platform-health",        "Show real-time health for all platforms"),
        ("health-check",           "Run full system health check"),
        ("audit-state",            "Inspect current state store contents"),
        ("preflight-targets",      "Validate target URLs before publishing"),
        ("canary-targets",         "Run canary checks on target URLs"),
        ("canary-seed",            "Run canary checks on seed URLs"),
        ("channel-scorecard",      "Show performance scorecard per channel"),
        ("plan-check",             "Validate a plan document against the schema"),
        ("verify-dofollow",        "Verify dofollow status of published links"),
        ("recheck-overlay",        "Re-check overlay state for published items"),
        ("debt-report",            "Report link debt and outstanding obligations"),
        ("decay-alert",            "Alert on decayed or degraded backlinks"),
    ]),
    ("State", [
        ("backup-state",           "Back up all state stores to a timestamped archive"),
        ("restore-state",          "Restore state stores from a backup archive"),
    ]),
    ("WebUI", [
        ("pipeline-orchestrator",  "Start the pipeline orchestrator (launches WebUI backend)"),
    ]),
]


def _print_overview() -> None:
    import sys

    print("backlink-publisher — available commands\n")
    for group_name, cmds in GROUPS:
        print(f"  {group_name}")
        for cmd, desc in cmds:
            print(f"    {cmd:<28}{desc}")
        print()
    print("Run any command with --help for details.", file=sys.stdout)


def main(argv: list[str] | None = None) -> None:
    import sys

    argv = sys.argv[1:] if argv is None else list(argv)
    if not argv or argv[0] in ("-h", "--help"):
        _print_overview()
        return
    print(f"bp: unknown argument {argv[0]!r}", file=sys.stderr)
    print("Run `bp` or `bp --help` to see all available commands.", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
