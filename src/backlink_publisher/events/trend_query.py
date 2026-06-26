"""Per-target weekly survival-trend query for the keep-alive sparklines.

Returns four weekly buckets (oldest → newest) covering the past 28 days.
Each bucket is the fraction of *definitive* verdicts that were "alive" in that
7-day window.  Indeterminate verdicts (``probe_error``) are excluded from the
denominator so a probe outage week doesn't collapse the line.

Hosts in _EXCLUDED_HOSTS are silently omitted.
"""

from __future__ import annotations

from datetime import datetime, timedelta, UTC
import json
from typing import Any

from backlink_publisher._util.url import canonicalize_url
from backlink_publisher.events.store import EventStore
from backlink_publisher.recheck import verdicts as _v

_EXCLUDED_HOSTS = frozenset({"example.com"})
_INDETERMINATE = frozenset({_v.PROBE_ERROR})
_ALIVE = _v.ALIVE

TREND_WEEKS = 4  # number of weekly buckets


def _host(url: str | None) -> str:
    from urllib.parse import urlsplit
    if not url:
        return ""
    return (urlsplit(url).hostname or "").lower()


def _parse_ts(ts_str: str | None) -> datetime | None:
    if not ts_str:
        return None
    try:
        dt = datetime.fromisoformat(ts_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt
    except (ValueError, TypeError):
        return None


def compute_target_trends(
    *,
    days: int = 28,
    store: EventStore | None = None,
    now: datetime | None = None,
) -> dict[str, list[float | None]]:
    """Return per-target weekly alive-rate trend for the past ``days`` days.

    Return shape::

        {
            "https://example.org/page": [None, 0.8, 1.0, 0.9],
            ...
        }

    Each list has exactly ``TREND_WEEKS`` entries, oldest first.  ``None``
    means no definitive verdicts were recorded in that bucket.
    """
    store = store or EventStore()
    now = now or datetime.now(tz=UTC)
    cutoff = now - timedelta(days=days)
    cutoff_iso = cutoff.isoformat()

    rows = store.query(
        "SELECT target_url, ts_utc, payload_json FROM events"
        " WHERE kind = 'link.rechecked' AND ts_utc >= ?"
        " ORDER BY ts_utc",
        (cutoff_iso,),
    )

    # buckets[canonical_url][week_idx] = (alive_count, total_count)
    buckets: dict[str, list[list[int]]] = {}

    for row in rows:
        url = row["target_url"]
        if not url or _host(url) in _EXCLUDED_HOSTS:
            continue
        try:
            payload: dict[str, Any] = json.loads(row["payload_json"])
        except (json.JSONDecodeError, TypeError):
            continue
        verdict = payload.get("verdict", "")
        if verdict in _INDETERMINATE:
            continue

        ts = _parse_ts(row["ts_utc"])
        if ts is None:
            continue

        age_days = (now - ts).days
        week_idx = min(TREND_WEEKS - 1 - age_days // 7, TREND_WEEKS - 1)
        if week_idx < 0:
            continue

        canon = canonicalize_url(url)
        if canon not in buckets:
            buckets[canon] = [[0, 0] for _ in range(TREND_WEEKS)]
        buckets[canon][week_idx][1] += 1
        if verdict == _ALIVE:
            buckets[canon][week_idx][0] += 1

    result: dict[str, list[float | None]] = {}
    for canon, weeks in buckets.items():
        trend: list[float | None] = []
        for alive, total in weeks:
            trend.append(alive / total if total > 0 else None)
        result[canon] = trend
    return result
