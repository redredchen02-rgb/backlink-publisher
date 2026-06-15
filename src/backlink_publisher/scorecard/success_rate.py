"""Per-channel publish success-rate metric (Plan 2026-06-15-001, Unit B2).

Publish success is NOT link liveness: a link can publish successfully and later
be stripped. This metric answers "of the publishes we attempted on channel X,
what fraction succeeded?", surfaced alongside the scorecard's ``live_pct`` but
kept distinct from it.

Source decision (feasibility review, 2026-06-15): derive from the
ALREADY-PERSISTED publish event kinds rather than introducing a new persistence
path. ``emit_attempt``/``publish_attempt`` is logger-only (stderr) and not
queryable, so it is not used here.

* successes  = ``publish.confirmed`` + ``publish.unverified`` (the post was created)
* failures   = ``publish.failed``

Known denominator gap (documented, not silently ignored): circuit-/health-gated
*skips* (``skipped_circuit_open`` / ``skipped_policy``) are emitted by
``reliability.policy`` to logs only and are NOT in events.db, so they cannot be
counted here yet. An all-tripped channel therefore shows a *thin/absent* denominator
(``small_sample``) rather than a falsely-high rate — but folding skips into the
denominator requires persisting them first (plan §Deferred to Implementation).

Read-only; no writes, no network.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from backlink_publisher.events import EventStore, kinds

DEFAULT_WINDOW_DAYS = 30
#: Channels with this many attempts or fewer are flagged thin (mirrors the
#: scorecard's small-sample convention).
DEFAULT_SMALL_SAMPLE_MAX = 4

_SUCCESS_KINDS: tuple[str, ...] = (kinds.PUBLISH_CONFIRMED, kinds.PUBLISH_UNVERIFIED)
_FAILURE_KINDS: tuple[str, ...] = (kinds.PUBLISH_FAILED,)
_ALL_KINDS: tuple[str, ...] = _SUCCESS_KINDS + _FAILURE_KINDS

UNATTRIBUTED = "(unattributed)"


@dataclass(frozen=True)
class ChannelSuccessRate:
    channel: str
    successes: int
    failures: int
    attempts: int
    success_pct: float | None  # None when attempts == 0
    small_sample: bool


@dataclass(frozen=True)
class SuccessRateReport:
    window_days: int
    overall_successes: int
    overall_failures: int
    overall_attempts: int
    overall_success_pct: float | None
    per_channel: list[ChannelSuccessRate]


def _parse_ts(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def publish_success_rate(
    *,
    window_days: int = DEFAULT_WINDOW_DAYS,
    small_sample_max: int = DEFAULT_SMALL_SAMPLE_MAX,
    store: EventStore | None = None,
    now: datetime | None = None,
) -> SuccessRateReport:
    """Per-channel publish success % over a rolling ``window_days`` window."""
    store = store or EventStore()
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    cutoff = now - timedelta(days=window_days)

    placeholders = ",".join("?" for _ in _ALL_KINDS)
    sql = (
        "SELECT kind, payload_json, ts_utc FROM events "
        f"WHERE kind IN ({placeholders})"
    )

    # channel -> [successes, failures]
    tallies: dict[str, list[int]] = {}
    for row in store.query(sql, _ALL_KINDS):
        ts = _parse_ts(row["ts_utc"])
        if ts is not None and ts < cutoff:
            continue  # outside the window; a NULL/unparseable ts is kept (conservative)
        try:
            payload = json.loads(row["payload_json"] or "{}")
        except (ValueError, TypeError):
            payload = {}
        channel = payload.get("platform") or UNATTRIBUTED
        acc = tallies.setdefault(channel, [0, 0])
        if row["kind"] in _SUCCESS_KINDS:
            acc[0] += 1
        else:
            acc[1] += 1

    per_channel: list[ChannelSuccessRate] = []
    tot_s = tot_f = 0
    for channel, (succ, fail) in tallies.items():
        attempts = succ + fail
        tot_s += succ
        tot_f += fail
        per_channel.append(
            ChannelSuccessRate(
                channel=channel,
                successes=succ,
                failures=fail,
                attempts=attempts,
                success_pct=(round(succ / attempts, 3) if attempts else None),
                small_sample=attempts <= small_sample_max,
            )
        )

    # Weakest channels first — lowest success rate, then most failures.
    per_channel.sort(
        key=lambda c: (c.success_pct if c.success_pct is not None else 1.0, -c.failures, c.channel)
    )
    overall_attempts = tot_s + tot_f
    return SuccessRateReport(
        window_days=window_days,
        overall_successes=tot_s,
        overall_failures=tot_f,
        overall_attempts=overall_attempts,
        overall_success_pct=(round(tot_s / overall_attempts, 3) if overall_attempts else None),
        per_channel=per_channel,
    )
