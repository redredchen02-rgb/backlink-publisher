from __future__ import annotations

from typing import Any

"""Keep-alive status view (R3 / plan 2026-06-04-001 Unit 4).

Builds the per-target keep-alive scorecard the operator lands on: live-dofollow +
platforms from the (now -api-deduped) equity ledger, joined to the *current*
per-link verdict read from the ``link.rechecked`` time series — the authority for
"is this link stripped now", since the ledger liveness column is stale
(recheck→ledger writeback is deferred). Bleeding targets sort first; test-data
hosts (``example.com``) are excluded so a new operator isn't misled.
"""

from datetime import datetime
from urllib.parse import urlsplit

from backlink_publisher._util.url import canonicalize_url
from backlink_publisher.events import EventStore
from backlink_publisher.events.kinds import LINK_RECHECKED, PUBLISH_CONFIRMED
from backlink_publisher.events.trend_query import compute_target_trends
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


def build_keepalive_view(*, store: Any=None, history: Any=None, now: Any=None) -> dict:
    """Return the keep-alive scorecard payload for the screen bootstrap.

    ``store``/``history``/``now`` are injectable for tests.
    """
    store = store or EventStore()
    now = now or datetime.now()

    ledger_rows = build_ledger(store=store, history=history)
    # derive_per_target_status already keys by canonical target (merging
    # canonically-equal raw variants), so a direct canonical lookup joins it to
    # the ledger rows — no lossy re-key that could drop a bleeding target.
    per_target = derive_per_target_status(store)

    try:
        trends = compute_target_trends(store=store)
    except Exception:
        trends = {}

    targets: list[dict] = []
    for row in ledger_rows:
        if _host(row.target_url) in _EXCLUDED_HOSTS:
            continue
        canon = canonicalize_url(row.target_url)
        status = per_target.get(canon)
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
                "unknown_follow": row.dofollow.unknown,
                "rechecked": rechecked,
                "strip_rate": round(strip_rate, 3),
                "last_verified": status["last_verified"] if status else None,
                "needs_attention": stripped > 0,
                "trend": trends.get(canon),
            }
        )

    # Bleeding targets first: needs-attention by strip-rate desc, then the rest.
    targets.sort(key=lambda t: (not t["needs_attention"], -t["strip_rate"], -t["stripped"]))

    # The authoritative S3 republish gap set (Unit 6), derived with the SAME
    # runtime sticky roster the republish job will use (blogger-only while GitHub
    # is suspended) so the count the operator selects from matches what publishes
    # — no S2↔S3 drift. Channel-exhausted gaps (dead but no free sticky dest) are
    # surfaced as a count, not as selectable rows.
    from backlink_publisher.gap.engine import GapOptions, plan_keepalive_gap

    from .keepalive_job import RUNTIME_STICKY_PLATFORMS

    _seeds, gap_objs = plan_keepalive_gap(
        ledger_rows, per_target, GapOptions(desired=5, language="zh-CN"),
        sticky_platforms=RUNTIME_STICKY_PLATFORMS,
    )
    gaps = [
        {
            "target_url": g.target_url,
            "stripped": g.stripped,
            "platforms": g.emitted_platforms,
        }
        for g in gap_objs
        if g.emitted_platforms
    ]
    gap_channel_exhausted = sum(1 for g in gap_objs if g.channel_exhausted)
    # Still-live targets that were rechecked but are NOT a gap (the "excluded
    # because still live" count the S3 panel shows alongside the gap list).
    live_excluded = sum(
        1 for t in targets if t["rechecked"] > 0 and t["stripped"] == 0
    )

    last_recheck = _max_ts(store, LINK_RECHECKED)
    latest_publish = _max_ts(store, PUBLISH_CONFIRMED)
    # Stale = newer publishes exist that have never been rechecked.
    stale = bool(
        latest_publish is not None
        and (last_recheck is None or latest_publish > last_recheck)
    )
    stale_days = None
    if last_recheck is not None:
        # last_recheck is tz-aware UTC; now is naive local. Convert the recheck
        # ts to local *before* stripping tz (matching ledger/aggregate.py's
        # verified.astimezone().replace(tzinfo=None)) so the day delta isn't
        # skewed by the operator's UTC offset.
        lr = last_recheck.astimezone().replace(tzinfo=None)
        stale_days = max(0, (now.replace(tzinfo=None) - lr).days)

    return {
        "targets": targets,
        "is_empty": last_recheck is None,
        "stale": stale,
        "stale_days": stale_days,
        "last_recheck": last_recheck.isoformat() if last_recheck else None,
        "latest_publish": latest_publish.isoformat() if latest_publish else None,
        # S3 republish surface (Unit 7): the deduped gap set + exclusion tallies.
        "gaps": gaps,
        "gap_channel_exhausted": gap_channel_exhausted,
        "live_excluded": live_excluded,
    }


def build_cycle_status_view(*, run_state: Any=None, opt_state: Any=None) -> dict:
    """Return automated keepalive cycle status for the WebUI panel.

    ``run_state`` / ``opt_state`` are injectable for tests — pass
    ``KeepaliveRunState(data_dir=tmp_path)`` / ``OptimizationState(data_dir=tmp_path)``.
    """
    from backlink_publisher.keepalive.run_state import KeepaliveRunState
    from backlink_publisher.optimization.state import OptimizationState

    rs = run_state if run_state is not None else KeepaliveRunState()
    data = rs.load()

    last_run_at = data.get("last_run_at")
    if not last_run_at:
        return {
            "has_data": False,
            "last_run_at": None,
            "cycle_summary": {},
            "platforms": [],
            "exhausted": [],
            "exhausted_total": 0,
        }

    cycle_summary = data.get("last_cycle_summary") or {}
    retry_counts = data.get("retry_counts") or {}
    max_retry = rs.MAX_RETRY

    # Build exhausted list — None last_attempt_at sorts last via empty-string coercion.
    # isinstance guard: skip corrupted entries that are not dicts (e.g. manual edits).
    # str() in sort key: guard against legacy unix-timestamp int values.
    all_exhausted = [
        {
            "target_url": url,
            "attempts": int(entry.get("attempts") or 0),
            "last_attempt_at": entry.get("last_attempt_at"),
            "last_outcome": entry.get("last_outcome"),
            "platforms_tried": list(entry.get("platforms_tried") or []),
        }
        for url, entry in retry_counts.items()
        if isinstance(entry, dict) and int(entry.get("attempts") or 0) >= max_retry
    ]
    all_exhausted.sort(key=lambda e: str(e.get("last_attempt_at") or ""), reverse=True)
    exhausted_total = len(all_exhausted)
    exhausted = all_exhausted[:20]

    # Platform health from OptimizationState.to_summary() — to_summary() produces
    # the "platforms" list; raw .load() has no "platforms" key.
    platforms: list[dict] = []
    try:
        os_inst = opt_state if opt_state is not None else OptimizationState()
        summary = os_inst.to_summary()
        for p in summary.get("platforms", []):
            weight = float(p.get("current", 1.0))
            locked = bool(p.get("locked", False))
            pstats = p.get("stats") or {}
            platforms.append({
                "name": p.get("name", ""),
                "weight": round(weight, 4),
                "circuit_broken": weight == 0.0 and not locked,
                "locked": locked,
                "alive_count": int(pstats.get("alive_count") or 0),
                "total_published": int(pstats.get("total_published") or 0),
            })
    except Exception:
        platforms = []

    return {
        "has_data": True,
        "last_run_at": last_run_at,
        "cycle_summary": cycle_summary,
        "platforms": platforms,
        "exhausted": exhausted,
        "exhausted_total": exhausted_total,
    }
