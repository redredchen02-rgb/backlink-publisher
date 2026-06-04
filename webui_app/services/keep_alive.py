"""Keep-alive status view (R3 / plan 2026-06-04-001 Unit 4).

Builds the per-target keep-alive scorecard the operator lands on: live-dofollow +
platforms from the (now -api-deduped) equity ledger, joined to the *current*
per-link verdict read from the ``link.rechecked`` time series — the authority for
"is this link stripped now", since the ledger liveness column is stale
(recheck→ledger writeback is deferred). Bleeding targets sort first; test-data
hosts (``example.com``) are excluded so a new operator isn't misled.
"""
from __future__ import annotations

from datetime import datetime
from urllib.parse import urlsplit

from backlink_publisher._util.url import canonicalize_url
from backlink_publisher.events import EventStore
from backlink_publisher.events.kinds import LINK_RECHECKED, PUBLISH_CONFIRMED
from backlink_publisher.ledger import build_ledger
from backlink_publisher.recheck import verdicts
from backlink_publisher.recheck.events_io import derive_per_target_status
from backlink_publisher.recheck.selection import _parse_ts

#: Hosts whose rows are test fixtures, never shown in the operator scorecard.
_EXCLUDED_HOSTS = frozenset({"example.com"})

# stripped = the deterministic-dead set (the republishable gap signal).
_STRIPPED = (verdicts.LINK_STRIPPED, verdicts.HOST_GONE)


def _host(url: str | None) -> str:
    if not url:
        return ""
    return (urlsplit(url).hostname or "").lower()


def _max_ts(store: EventStore, kind: str) -> datetime | None:
    latest: datetime | None = None
    for row in store.query("SELECT ts_utc FROM events WHERE kind = ?", (kind,)):
        ts = _parse_ts(row["ts_utc"])
        if ts is not None and (latest is None or ts > latest):
            latest = ts
    return latest


def build_keepalive_view(*, store=None, history=None, now=None) -> dict:
    """Return the keep-alive scorecard payload for the screen bootstrap.

    ``store``/``history``/``now`` are injectable for tests.
    """
    store = store or EventStore()
    now = now or datetime.now()

    ledger_rows = build_ledger(store=store, history=history)
    per_target = derive_per_target_status(store)
    # Re-key recheck status by canonical target so it joins to ledger rows.
    recheck_by_canon = {canonicalize_url(t): s for t, s in per_target.items()}

    targets: list[dict] = []
    for row in ledger_rows:
        if _host(row.target_url) in _EXCLUDED_HOSTS:
            continue
        canon = canonicalize_url(row.target_url)
        status = recheck_by_canon.get(canon)
        counts = status["counts"] if status else {v: 0 for v in verdicts.VERDICTS}
        rechecked = status["total"] if status else 0
        stripped = counts[verdicts.LINK_STRIPPED] + counts[verdicts.HOST_GONE]
        strip_rate = (stripped / rechecked) if rechecked else 0.0
        targets.append(
            {
                "target_url": row.target_url,
                "live_dofollow": row.live_dofollow,
                "platforms": sorted(row.platforms),
                "total_links": row.total_links,
                "alive": counts[verdicts.ALIVE],
                "stripped": stripped,
                "decayed": counts[verdicts.DOFOLLOW_LOST],
                "check_failed": counts[verdicts.PROBE_ERROR],
                "unknown_follow": row.dofollow.get("unknown", 0) if isinstance(row.dofollow, dict) else 0,
                "rechecked": rechecked,
                "strip_rate": round(strip_rate, 3),
                "last_verified": status["last_verified"] if status else None,
                "needs_attention": stripped > 0,
            }
        )

    # Bleeding targets first: needs-attention by strip-rate desc, then the rest.
    targets.sort(key=lambda t: (not t["needs_attention"], -t["strip_rate"], -t["stripped"]))

    last_recheck = _max_ts(store, LINK_RECHECKED)
    latest_publish = _max_ts(store, PUBLISH_CONFIRMED)
    # Stale = newer publishes exist that have never been rechecked.
    stale = bool(
        latest_publish is not None
        and (last_recheck is None or latest_publish > last_recheck)
    )
    stale_days = None
    if last_recheck is not None:
        # ts may be tz-aware (UTC); now is naive local — fold to naive before
        # subtracting, matching ledger._link_liveness.
        lr = last_recheck.replace(tzinfo=None)
        stale_days = max(0, (now.replace(tzinfo=None) - lr).days)

    return {
        "targets": targets,
        "is_empty": last_recheck is None,
        "stale": stale,
        "stale_days": stale_days,
        "last_recheck": last_recheck.isoformat() if last_recheck else None,
        "latest_publish": latest_publish.isoformat() if latest_publish else None,
    }
