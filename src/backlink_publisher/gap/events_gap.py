"""Pipeline closed-loop gap detection: query events.db for stale targets.

A target is "gappy" when:
  - >48h since the last ``publish.intent`` event (stale intent = needs re-discovery)
  - >7d since the last ``publish.confirmed`` / ``link.rechecked`` event
    (stale confirmation = needs recheck)

Pure-ish: reads from EventStore, returns structured dataclasses. No I/O
beyond the query layer. The CLI shell lives in
:mod:`backlink_publisher.cli.pipeline_orchestrator`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, UTC
from typing import Any

from backlink_publisher.events.store import EventStore

#: Default staleness thresholds (operator-tunable at call sites).
_INTENT_STALE_HOURS: float = 48
_CONFIRM_STALE_HOURS: float = 168  # 7 days


@dataclass
class PipelineGap:
    """One target identified as needing pipeline attention.

    ``gap_type`` encodes which threshold was breached:
      - ``"no_history"`` — target has zero events in events.db
      - ``"stale_intent"`` — last ``publish.intent`` older than threshold
      - ``"stale_confirm"`` — last confirmation older than threshold
      - ``"both"`` — both intent and confirmation are stale
    """

    target_url: str
    host: str
    gap_type: str
    last_intent_ts: str | None = None
    hours_since_intent: float | None = None
    last_confirm_ts: str | None = None
    hours_since_confirm: float | None = None
    last_intent_payload: dict[str, Any] | None = None
    last_confirm_payload: dict[str, Any] | None = None

    @property
    def summary(self) -> str:
        """Human-readable one-liner for logging / event payloads."""
        parts: list[str] = [f"target={self.target_url}", f"gap={self.gap_type}"]
        if self.hours_since_intent is not None:
            parts.append(f"intent={self.hours_since_intent:.0f}h")
        if self.hours_since_confirm is not None:
            parts.append(f"confirm={self.hours_since_confirm:.0f}h")
        return " ".join(parts)


@dataclass
class GapResult:
    """Result of a ``find_gaps()`` call."""

    gaps: list[PipelineGap] = field(default_factory=list)
    total_targets_scanned: int = 0
    skipped_stale_intent: int = 0
    skipped_stale_confirm: int = 0


def _parse_iso_or_none(ts: str | None) -> datetime | None:
    """Parse ISO-8601 UTC timestamp, returning None on any failure."""
    if not ts:
        return None
    try:
        # Python 3.11+ fromisoformat handles the trailing Z via
        # replace() — keep the explicit path for clarity.
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _hours_since(dt: datetime | None, now: datetime) -> float | None:
    """Compute hours between *now* and *dt* (None-safe)."""
    if dt is None:
        return None
    return (now - dt).total_seconds() / 3600


def find_gaps(
    store: EventStore,
    *,
    intent_stale_hours: float = _INTENT_STALE_HOURS,
    confirm_stale_hours: float = _CONFIRM_STALE_HOURS,
    now: datetime | None = None,
) -> GapResult:
    """Query events.db and return targets that need pipeline attention.

    Parameters
    ----------
    store:
        Connected ``EventStore`` instance.
    intent_stale_hours:
        Hours since last ``publish.intent`` before a target is considered
        stale. Default 48.
    confirm_stale_hours:
        Hours since last confirmation event before stale. Default 168 (7d).
    now:
        Override "now" for deterministic testing. Defaults to UTC now.

    Returns
    -------
    ``GapResult`` with a list of ``PipelineGap`` entries.
    """
    if now is None:
        now = datetime.now(UTC)

    # --- Step 1: collect all distinct target_urls from events.db -----------
    all_targets = store.query(
        "SELECT DISTINCT target_url FROM events WHERE target_url IS NOT NULL"
    )

    result = GapResult(total_targets_scanned=len(all_targets))

    # --- Step 2: for each target, inspect latest intent + confirm ----------
    for (target_url,) in all_targets:
        gap = _inspect_target(
            store, target_url, now, intent_stale_hours, confirm_stale_hours
        )
        if gap is not None:
            result.gaps.append(gap)
            if gap.gap_type in ("stale_intent", "both"):
                result.skipped_stale_intent += 1
            if gap.gap_type in ("stale_confirm", "both"):
                result.skipped_stale_confirm += 1

    return result


def _inspect_target(
    store: EventStore,
    target_url: str,
    now: datetime,
    intent_stale_hours: float,
    confirm_stale_hours: float,
) -> PipelineGap | None:
    """Examine one target's event history and return a gap if stale.

    Returns ``None`` when the target is up-to-date on both axes.
    """
    # Derive host from target_url (just for the gap record).
    host = _derive_host(target_url)

    # --- Latest publish.intent --------------------------------------------
    intent_rows = store.query(
        "SELECT ts_utc, payload_json FROM events "
        "WHERE target_url = ? AND kind = 'publish.intent' "
        "ORDER BY ts_utc DESC LIMIT 1",
        (target_url,),
    )

    last_intent_ts: str | None = None
    last_intent_dt: datetime | None = None
    last_intent_payload: dict[str, Any] | None = None

    if intent_rows:
        row = intent_rows[0]
        last_intent_ts = row["ts_utc"]
        last_intent_dt = _parse_iso_or_none(last_intent_ts)
        try:
            import json
            last_intent_payload = json.loads(row["payload_json"])
        except (json.JSONDecodeError, TypeError, KeyError):
            last_intent_payload = None

    hours_since_intent = _hours_since(last_intent_dt, now)
    intent_stale = (
        hours_since_intent is not None and hours_since_intent > intent_stale_hours
    )

    # --- Latest publish.confirmed OR link.rechecked -----------------------
    confirm_rows = store.query(
        "SELECT ts_utc, kind, payload_json FROM events "
        "WHERE target_url = ? AND kind IN ('publish.confirmed', 'link.rechecked') "
        "ORDER BY ts_utc DESC LIMIT 1",
        (target_url,),
    )

    last_confirm_ts: str | None = None
    last_confirm_dt: datetime | None = None
    last_confirm_payload: dict[str, Any] | None = None

    if confirm_rows:
        row = confirm_rows[0]
        last_confirm_ts = row["ts_utc"]
        last_confirm_dt = _parse_iso_or_none(last_confirm_ts)
        try:
            import json
            last_confirm_payload = json.loads(row["payload_json"])
        except (json.JSONDecodeError, TypeError, KeyError):
            last_confirm_payload = None

    hours_since_confirm = _hours_since(last_confirm_dt, now)
    confirm_stale = (
        hours_since_confirm is not None and hours_since_confirm > confirm_stale_hours
    )

    # --- Determine gap type ------------------------------------------------
    no_history = last_intent_ts is None and last_confirm_ts is None
    if no_history:
        return PipelineGap(
            target_url=target_url,
            host=host,
            gap_type="no_history",
        )

    if intent_stale and confirm_stale:
        gap_type = "both"
    elif intent_stale:
        gap_type = "stale_intent"
    elif confirm_stale:
        gap_type = "stale_confirm"
    else:
        return None  # Target is up-to-date

    return PipelineGap(
        target_url=target_url,
        host=host,
        gap_type=gap_type,
        last_intent_ts=last_intent_ts,
        hours_since_intent=hours_since_intent,
        last_confirm_ts=last_confirm_ts,
        hours_since_confirm=hours_since_confirm,
        last_intent_payload=last_intent_payload,
        last_confirm_payload=last_confirm_payload,
    )


def _derive_host(target_url: str) -> str:
    """Extract hostname from a target_url, or return the raw string on error."""
    try:
        from urllib.parse import urlparse
        parsed = urlparse(target_url)
        return parsed.hostname or target_url
    except Exception:
        return target_url
