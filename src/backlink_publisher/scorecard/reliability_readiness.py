"""Per-channel enforce-readiness from observe data (Plan 2026-06-15-006, Unit 4).

Two sources, joined per channel — they CANNOT be collapsed into one:

  * attempt denominator  = ``publish.*`` event kinds (the source ``success_rate``
    uses). A clean dispatch writes a ``publish.*`` row but NO
    ``reliability.decision`` row, so attempts cannot be derived from
    ``reliability.decision`` alone.
  * would-skip numerator = ``reliability.decision`` rows whose decision is a
    ``would_skip_*`` (what enforce WOULD have skipped, recorded in observe mode).
    ``skipped_*`` (enforce) and ``degraded`` / ``circuit_state_unreadable`` (alert)
    decisions are deliberately NOT counted here.

The verdict is THREE-state, not a binary that conflates "safe" with "pointless":

  * ``insufficient_data``  — too few attempts or too short an observe window;
    falls back to operator qualitative judgement.
  * ``enforce_pointless``  — enough data, but the gate ~never wants to fire
    (would_skip ≈ 0) → a real negative conclusion ("not worth enforcing").
  * ``enforce_worthwhile`` — enough data AND would_skip present → enforce will
    actually catch real skips.

Read-only; no writes, no network. The thresholds are provisional, to be calibrated
against real observe data (plan §Deferred to Implementation).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from backlink_publisher.events import EventStore, kinds

DEFAULT_WINDOW_DAYS = 30
#: Channels with this many attempts or fewer are flagged thin (mirrors scorecard).
DEFAULT_SMALL_SAMPLE_MAX = 4
#: Provisional readiness floors — calibrate against real observe data (plan §Deferred).
DEFAULT_MIN_ATTEMPTS = 30
DEFAULT_MIN_DAYS_OBSERVED = 7

VERDICT_INSUFFICIENT = "insufficient_data"
VERDICT_POINTLESS = "enforce_pointless"
VERDICT_WORTHWHILE = "enforce_worthwhile"

UNATTRIBUTED = "(unattributed)"

_ATTEMPT_KINDS: tuple[str, ...] = (
    kinds.PUBLISH_CONFIRMED,
    kinds.PUBLISH_UNVERIFIED,
    kinds.PUBLISH_FAILED,
)
#: A would-skip is any ``would_skip_*`` decision (what enforce WOULD have skipped
#: in observe mode). Matched by prefix so a new ``would_skip_*`` decision is
#: counted automatically — no second list to keep in sync with events_store.
_WOULD_SKIP_PREFIX = "would_skip"


@dataclass(frozen=True)
class ChannelReadiness:
    channel: str
    observed_attempts: int
    would_skip_count: int
    would_skip_rate: float | None  # None when observed_attempts == 0
    days_observed: int
    small_sample: bool
    verdict: str
    reason: str


@dataclass(frozen=True)
class ReadinessReport:
    window_days: int
    per_channel: list[ChannelReadiness]


def _parse_ts(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _verdict(
    *,
    attempts: int,
    would_skip: int,
    days_observed: int,
    small_sample: bool,
    min_attempts: int,
    min_days: int,
) -> tuple[str, str]:
    if small_sample or attempts < min_attempts or days_observed < min_days:
        return VERDICT_INSUFFICIENT, (
            f"need >={min_attempts} attempts over >={min_days}d "
            f"(have {attempts} over {days_observed}d)"
        )
    if would_skip == 0:
        return (
            VERDICT_POINTLESS,
            "no would-skip over a sufficient window — enforce would never fire",
        )
    return VERDICT_WORTHWHILE, f"{would_skip} would-skip(s) — enforce would catch these"


def channel_readiness(
    *,
    window_days: int = DEFAULT_WINDOW_DAYS,
    small_sample_max: int = DEFAULT_SMALL_SAMPLE_MAX,
    min_attempts: int = DEFAULT_MIN_ATTEMPTS,
    min_days_observed: int = DEFAULT_MIN_DAYS_OBSERVED,
    store: EventStore | None = None,
    now: datetime | None = None,
) -> ReadinessReport:
    """Per-channel enforce-readiness over a rolling ``window_days`` window."""
    store = store or EventStore()
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    cutoff = now - timedelta(days=window_days)

    # channel -> {"attempts", "would_skip", "earliest"}
    agg: dict[str, dict] = {}

    def _bucket(channel: str) -> dict:
        return agg.setdefault(
            channel, {"attempts": 0, "would_skip": 0, "earliest": None}
        )

    def _note_ts(bucket: dict, ts: datetime | None) -> None:
        if ts is not None and (bucket["earliest"] is None or ts < bucket["earliest"]):
            bucket["earliest"] = ts

    # 1. attempt denominator — publish.* kinds
    placeholders = ",".join("?" for _ in _ATTEMPT_KINDS)
    for row in store.query(
        f"SELECT payload_json, ts_utc FROM events WHERE kind IN ({placeholders})",
        _ATTEMPT_KINDS,
    ):
        ts = _parse_ts(row["ts_utc"])
        if ts is not None and ts < cutoff:
            continue
        try:
            channel = json.loads(row["payload_json"] or "{}").get("platform")
        except (ValueError, TypeError):
            channel = None
        bucket = _bucket(channel or UNATTRIBUTED)
        bucket["attempts"] += 1
        _note_ts(bucket, ts)

    # 2. would-skip numerator — reliability.decision rows with a would_skip_* decision
    for row in store.query(
        "SELECT payload_json, ts_utc FROM events WHERE kind = ?",
        (kinds.RELIABILITY_DECISION,),
    ):
        ts = _parse_ts(row["ts_utc"])
        if ts is not None and ts < cutoff:
            continue
        try:
            payload = json.loads(row["payload_json"] or "{}")
        except (ValueError, TypeError):
            continue
        if not str(payload.get("decision", "")).startswith(_WOULD_SKIP_PREFIX):
            continue
        bucket = _bucket(payload.get("platform") or UNATTRIBUTED)
        bucket["would_skip"] += 1
        _note_ts(bucket, ts)

    per_channel: list[ChannelReadiness] = []
    for channel, bucket in agg.items():
        attempts = bucket["attempts"]
        would_skip = bucket["would_skip"]
        earliest = bucket["earliest"]
        days_observed = (now - earliest).days if earliest is not None else 0
        small_sample = attempts <= small_sample_max
        verdict, reason = _verdict(
            attempts=attempts,
            would_skip=would_skip,
            days_observed=days_observed,
            small_sample=small_sample,
            min_attempts=min_attempts,
            min_days=min_days_observed,
        )
        per_channel.append(
            ChannelReadiness(
                channel=channel,
                observed_attempts=attempts,
                would_skip_count=would_skip,
                would_skip_rate=(round(would_skip / attempts, 3) if attempts else None),
                days_observed=days_observed,
                small_sample=small_sample,
                verdict=verdict,
                reason=reason,
            )
        )

    per_channel.sort(key=lambda c: c.channel)
    return ReadinessReport(window_days=window_days, per_channel=per_channel)
