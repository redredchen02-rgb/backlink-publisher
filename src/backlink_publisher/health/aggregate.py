"""Unified per-platform health source — Plan 2026-06-03-004 Unit 1.

``build_platform_health(config)`` is the single canonical source of truth for
per-platform health state. It combines:
- EventStore last-terminal-event per platform (immutable facts)
- ``circuit.is_tripped()`` state (live read, no network)
- ``LockedHealthStore`` mutable state (consecutive_failures, paused)

No network calls; no side effects.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import TYPE_CHECKING

from backlink_publisher._util.logger import opencli_logger as _log

if TYPE_CHECKING:
    from backlink_publisher.config import Config


_TERMINAL_KINDS = ("publish.confirmed", "publish.unverified", "publish.failed")

# Redact any substring that looks like a token (≥20 alphanumeric/dash/underscore chars).
_TOKEN_RE = re.compile(r"[A-Za-z0-9_\-]{20,}")


@dataclass(frozen=True)
class PlatformHealthRecord:
    platform: str
    last_success_at: str | None = None
    last_failure_at: str | None = None
    last_error_msg: str | None = None
    consecutive_failures: int = 0
    circuit_tripped: bool = False
    circuit_tripped_at: str | None = None
    paused: bool = False


def _redact(msg: str | None) -> str | None:
    if not msg:
        return msg
    return _TOKEN_RE.sub("[REDACTED]", msg)


def build_platform_health(config: Config) -> dict[str, PlatformHealthRecord]:
    """Return a mapping of platform name → PlatformHealthRecord.

    Never raises — returns empty dict on any top-level error.
    """
    try:
        return _build(config)
    except Exception as exc:
        _log.warning(f"build_platform_health: unexpected error: {exc}")
        return {}


def _build(config: Config) -> dict[str, PlatformHealthRecord]:
    from backlink_publisher.events import EventStore
    from backlink_publisher.health.persistence import locked_store
    from backlink_publisher.publishing.registry import registered_platforms
    from backlink_publisher.publishing.reliability import circuit

    platforms = registered_platforms()
    platform_set = set(platforms)
    store = EventStore()

    last_success: dict[str, str] = {}
    last_failure: dict[str, str] = {}
    last_error: dict[str, str] = {}

    # Single consolidated query over the terminal kinds both partitions need,
    # ordered so the FIRST row seen per (platform, kind) is the most recent
    # (ts_utc DESC, id DESC) — matching the per-platform LIMIT 1 the two old
    # loops used. Rows are partitioned in memory once instead of issuing 2N
    # round-trips.
    try:
        rows = store.query(
            """
            SELECT json_extract(payload_json, '$.platform') AS platform,
                   ts_utc,
                   kind,
                   json_extract(payload_json, '$.error') AS error
            FROM events
            WHERE kind IN ('publish.confirmed', 'publish.failed', 'publish.unverified')
            ORDER BY ts_utc DESC, id DESC
            """,
        )
    except Exception as exc:
        _log.debug(f"build_platform_health: terminal-event query failed: {exc}")
        rows = []

    remaining_success = set(platforms)
    remaining_failure = set(platforms)

    for row in rows:
        if not remaining_success and not remaining_failure:
            break
        platform = row["platform"]
        if platform not in platform_set:
            continue
        kind = row["kind"]
        if kind == "publish.confirmed":
            # First (most-recent) confirmed row per platform wins.
            if platform in remaining_success:
                last_success[platform] = row["ts_utc"]
                remaining_success.remove(platform)
        else:  # publish.failed / publish.unverified
            if platform in remaining_failure:
                last_failure[platform] = row["ts_utc"]
                last_error[platform] = _redact(row["error"] or "") or None  # type: ignore[assignment]
                remaining_failure.remove(platform)

    # circuit.py persists per-platform timestamps under "tripped_at_iso" in
    # this file. Read + parse it ONCE here, then do dict lookups in the loop
    # instead of re-reading the file per tripped platform. Missing/unreadable
    # file → no recorded trip timestamps (same as the old per-platform guard,
    # which only read tripped_at when the file existed).
    circuit_state: dict = {}
    try:
        state_path = config.config_dir / "publish-circuit-state.json"
        if state_path.exists():
            import json as _json
            raw = _json.loads(state_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                circuit_state = raw
    except Exception as exc:
        _log.debug(f"build_platform_health: circuit state load failed: {exc}")

    result: dict[str, PlatformHealthRecord] = {}
    for platform in platforms:
        # Circuit state — read for every registered platform. As of Phase 3 the
        # breaker covers all platforms (not just browser-tier), so a non-browser
        # platform can legitimately report tripped here.
        tripped = False
        tripped_at: str | None = None
        try:
            tripped = circuit.is_tripped(platform, config)
            if tripped:
                entry = circuit_state.get(platform)
                if isinstance(entry, dict):
                    tripped_at = entry.get("tripped_at_iso")
        except Exception as exc:
            _log.debug(f"build_platform_health: circuit check for {platform}: {exc}")

        # Mutable state from locked store.
        mutable = locked_store.get(platform, config)

        result[platform] = PlatformHealthRecord(
            platform=platform,
            last_success_at=last_success.get(platform),
            last_failure_at=last_failure.get(platform),
            last_error_msg=last_error.get(platform),
            consecutive_failures=mutable["consecutive_failures"],
            circuit_tripped=tripped,
            circuit_tripped_at=tripped_at,
            paused=mutable["paused"],
        )

    return result
