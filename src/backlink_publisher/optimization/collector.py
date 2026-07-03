"""Signal Collector — gather publishing outcome signals from existing quality gates.

Signal sources (all consumed read-only):
  1. ``recheck-backlinks`` — survival status and dofollow verdicts
  2. ``canary_targets`` — forward-path drift detection
  3. ``equity_ledger`` — aggregated per-target scorecard data

The collector normalises these into per-platform statistics and writes them
into ``optimization_state.json`` via ``OptimizationState.update_stats()``.
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
from typing import Any, cast

from backlink_publisher._util.subprocess_env import utf8_child_env
from backlink_publisher.config.loader import _config_dir as _resolve_config_dir
from backlink_publisher.optimization import OptimizationState

log = logging.getLogger(__name__)

# Exit codes
EXIT_OK = 0
EXIT_COLLECT_ERR = 3


def collect_all_signals(
    state: OptimizationState,
    dry_run: bool = False,
    source_filter: str | None = None,
    language: str = "default",
) -> dict[str, Any]:
    """Run all enabled signal collectors and return aggregated per-platform stats.

    When *dry_run* is ``True``, results are returned but NOT written to the
    state file. The *source_filter* (``"recheck"``, ``"canary"``, or
    ``"equity"``) restricts collection to a single source for debugging.
    *language* scopes the signal write to a specific language namespace.

    Returns a dict with keys ``"recheck"``, ``"canary"``, ``"equity"`` (each
    holding the raw signal data) plus ``"merged"`` (the merged per-platform
    statistics ready to write).
    """
    signals: dict[str, Any] = {}

    if source_filter is None or source_filter == "recheck":
        signals["recheck"] = _collect_from_recheck()
    else:
        signals["recheck"] = {"status": "skipped"}

    if source_filter is None or source_filter == "canary":
        signals["canary"] = _collect_from_canary()
    else:
        signals["canary"] = {"status": "skipped"}

    if source_filter is None or source_filter == "equity":
        signals["equity"] = _collect_from_equity()
    else:
        signals["equity"] = {"status": "skipped"}

    merged = _merge_signals(signals)

    if not dry_run:
        for platform, stats in merged.items():
            state.update_stats(platform, stats, language=language)

    return {
        "raw": signals,
        "merged": merged,
    }


def _collect_from_recheck() -> dict[str, Any]:
    """Collect platform-level survival / dofollow statistics from
    ``recheck-backlinks``.

    Attempts to read the recheck store directly (events.db or its derived
    aggregates). Falls back to running the CLI with ``--json-summary`` if
    available.

    Returns a dict keyed by platform name with aggregated counts, or
    ``{"status": "unavailable"}`` if no data source is reachable.
    """
    # Preferred path: read events.db for recheck verdicts.
    # Fallback: parse CLI output.
    result = _try_cli_collect("recheck-backlinks", ["--json-summary", "--summary-only"])
    if result is not None:
        return result

    # If CLI isn't available, return empty so the merge still works.
    log.info("recheck signal source unavailable — skipping")
    return {"status": "unavailable"}


def _collect_from_canary() -> dict[str, Any]:
    """Collect forward-path drift signals from the canary target system.

    Attempts to read ``canary-health.json`` directly from the config
    directory. Falls back to the CLI if the file is not present.

    Returns a dict mapping platform names to drift counts, or
    ``{"status": "unavailable"}``.
    """
    # Try reading canary-health.json from config dir
    config_dir = _resolve_config_dir()
    canary_path = config_dir / "canary-health.json"
    if canary_path.exists():
        try:
            raw = canary_path.read_text(encoding="utf-8")
            data: dict[str, Any] = json.loads(raw)
            return _extract_platform_drift(data)
        except (json.JSONDecodeError, OSError):
            log.warning("canary-health.json unreadable — falling back to CLI")

    result = _try_cli_collect("canary-targets", ["--json-summary"])
    if result is not None:
        return result

    log.info("canary signal source unavailable — skipping")
    return {"status": "unavailable"}


def _collect_from_equity() -> dict[str, Any]:
    """Collect aggregated publishing statistics from the equity ledger.

    Attempts to read the equity ledger data. Returns per-platform aggregated
    stats or ``{"status": "unavailable"}``.
    """
    result = _try_cli_collect("equity-ledger", ["--json-summary"])
    if result is not None:
        return result

    log.info("equity signal source unavailable — skipping")
    return {"status": "unavailable"}


def _try_cli_collect(
    command: str,
    extra_args: list[str],
) -> dict[str, Any] | None:
    """Try to run a CLI command and parse its JSON output.

    Returns the parsed dict on success, or ``None`` if the command is not
    found or returns a non-zero exit code.
    """
    try:
        result = subprocess.run(
            [sys.executable, "-m", f"backlink_publisher.cli.{command.replace('-', '_')}"]
            + extra_args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=utf8_child_env(),
            timeout=30,
        )
        if result.returncode != 0:
            log.debug("%s exited %d: %s", command, result.returncode, result.stderr[:200])
            return None
        return cast(dict[str, Any], json.loads(result.stdout))
    except (FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        log.debug("Failed to collect from %s: %s", command, exc)
        return None


def _extract_platform_drift(canary_data: dict[str, Any]) -> dict[str, Any]:
    """Extract per-platform drift counts from canary-health.json structure.

    The canary health file stores per-platform records; platforms with
    ``"forward_path_drift": true`` contribute to the drift count.
    """
    platforms: dict[str, Any] = {}
    for platform, entry in canary_data.items():
        if not isinstance(entry, dict):
            continue
        drift = 1 if entry.get("forward_path_drift") else 0
        platforms[platform] = {"drift_count": drift}
    return {"platforms": platforms, "status": "collected"}


def _merge_signals(signals: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Merge raw signals from all sources into per-platform statistics.

    Each source contributes additive fields (drift_count, alive_count, etc.).
    """
    merged: dict[str, dict[str, Any]] = {}

    # Merge recheck signals
    recheck = signals.get("recheck", {})
    if "platforms" in recheck:
        for platform, stats in recheck["platforms"].items():
            if platform not in merged:
                merged[platform] = {}
            merged[platform]["alive_count"] = stats.get("alive_count", 0)
            merged[platform]["dofollow_count"] = stats.get("dofollow_count", 0)
            merged[platform]["total_published"] = stats.get("total_published", 0)
            merged[platform]["last_recheck"] = stats.get("last_recheck")

    # Merge canary signals
    canary = signals.get("canary", {})
    if "platforms" in canary:
        for platform, stats in canary["platforms"].items():
            if platform not in merged:
                merged[platform] = {}
            existing_drift = merged[platform].get("drift_count", 0)
            merged[platform]["drift_count"] = existing_drift + stats.get("drift_count", 0)

    # Merge equity signals (complements recheck data with broader stats)
    equity = signals.get("equity", {})
    if "platforms" in equity:
        for platform, stats in equity["platforms"].items():
            if platform not in merged:
                merged[platform] = {}
            for key, value in stats.items():
                if key in ("total_published", "alive_count", "dofollow_count", "drift_count"):
                    merged[platform][key] = merged[platform].get(key, 0) + value
                else:
                    merged[platform][key] = value

    return merged
