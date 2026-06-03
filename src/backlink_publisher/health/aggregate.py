"""Unified per-platform health source — Plan 2026-06-03-004 Unit 1.

``build_platform_health(config)`` is the single canonical source of truth for
per-platform health state. It combines:
- EventStore last-terminal-event per platform (immutable facts)
- ``circuit.is_tripped()`` state (live read, no network)
- ``LockedHealthStore`` mutable state (consecutive_failures, paused)

No network calls; no side effects.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
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
    from backlink_publisher.publishing.registry import registered_platforms
    from backlink_publisher.publishing.reliability import circuit
    from backlink_publisher.health.persistence import locked_store

    platforms = registered_platforms()
    store = EventStore()

    last_success: dict[str, str] = {}
    last_failure: dict[str, str] = {}
    last_error: dict[str, str] = {}

    # Query last confirmed event per platform.
    for platform in platforms:
        try:
            rows = store.query(
                """
                SELECT ts_utc
                FROM events
                WHERE kind = 'publish.confirmed'
                  AND json_extract(payload_json, '$.platform') = ?
                ORDER BY ts_utc DESC, id DESC
                LIMIT 1
                """,
                (platform,),
            )
            if rows:
                last_success[platform] = rows[0]["ts_utc"]
        except Exception as exc:
            _log.debug(f"build_platform_health: confirmed query for {platform}: {exc}")

    # Query last failed/unverified event per platform.
    for platform in platforms:
        try:
            rows = store.query(
                """
                SELECT ts_utc, json_extract(payload_json, '$.error') AS error
                FROM events
                WHERE kind IN ('publish.failed', 'publish.unverified')
                  AND json_extract(payload_json, '$.platform') = ?
                ORDER BY ts_utc DESC, id DESC
                LIMIT 1
                """,
                (platform,),
            )
            if rows:
                last_failure[platform] = rows[0]["ts_utc"]
                last_error[platform] = _redact(rows[0].get("error") or "") or None
        except Exception as exc:
            _log.debug(f"build_platform_health: failure query for {platform}: {exc}")

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
                # circuit.py persists the timestamp under "tripped_at_iso".
                state_path = config.config_dir / "publish-circuit-state.json"
                if state_path.exists():
                    import json as _json
                    raw = _json.loads(state_path.read_text(encoding="utf-8"))
                    tripped_at = raw.get(platform, {}).get("tripped_at_iso")
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
