"""Unit 3 — dimension computation. The single engine entry: ``build_ledger``.

Turns the raw per-target buckets from :mod:`ledger.sources` into ``LedgerRow``
scorecards. Both the CLI verb (U4) and the WebUI route (U5) call ``build_ledger``
in-process so their numbers match by construction.

Classification rules (plan R3/R3a/R5):
- ``dofollow_status(platform) is None`` (or no platform) → ``unknown`` — never
  conflated with an explicit nofollow. (``referral_value`` is NOT used to detect
  unknown; it is ``None`` for registered dofollow platforms by design.)
- ``referral_value`` high/low sub-grades **nofollow** links only.
Liveness (plan R7): ``failed`` (verify error) > ``stale`` (verified older than
``stale_days``) > ``live`` (verified, fresh) > ``unverified`` (never verified),
worst-status-wins per target.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime
import json
from typing import Any, TYPE_CHECKING

from backlink_publisher._util.url import canonicalize_url
from backlink_publisher.anchor.metrics import exact_match_ratio
from backlink_publisher.publishing import registry

# Importing the adapters package populates the registry via its ``register()``
# side effects. Without this the registry is empty and every link classifies as
# ``unknown`` — so the engine must trigger registration itself rather than rely
# on the caller having imported adapters.
import backlink_publisher.publishing.adapters  # noqa: F401,E402
from backlink_publisher.recheck.verdicts import DOFOLLOW_LOST as _DOFOLLOW_LOST

from .model import DofollowBreakdown, LedgerRow, worst_liveness
from .sources import build_target_buckets, LinkRecord

if TYPE_CHECKING:
    from backlink_publisher.events.store import EventStore


def _load_confirmed_dofollow_urls(store: EventStore | None) -> frozenset[str]:
    """Return canonical live_urls whose latest ``link.rechecked`` event has
    ``confirmed_dofollow=True``.

    One full-table scan per ``build_ledger()`` call (same pattern as
    ``overlay.py``). Recency is determined by ``ts_utc`` with ``events.id`` as
    a same-timestamp tiebreaker. Returns empty frozenset when store is None.
    """
    from backlink_publisher.events.kinds import LINK_RECHECKED
    from backlink_publisher.recheck.selection import _parse_ts

    if store is None:
        return frozenset()

    latest: dict[str, tuple] = {}
    sql = "SELECT id, payload_json, ts_utc FROM events WHERE kind = ?"
    for row in store.query(sql, (LINK_RECHECKED,)):
        try:
            payload = json.loads(row["payload_json"] or "{}")
        except (ValueError, TypeError):
            continue
        raw_url = payload.get("live_url")
        if not raw_url:
            continue
        try:
            canon = canonicalize_url(raw_url)
        except Exception:  # noqa: BLE001
            continue
        ts = _parse_ts(row["ts_utc"])
        rid = row["id"]
        prev = latest.get(canon)
        if prev is None:
            latest[canon] = (ts, rid, bool(payload.get("confirmed_dofollow", False)))
        else:
            prev_ts, prev_rid, _ = prev
            is_newer = (
                (ts is not None and prev_ts is None)
                or (ts is not None and prev_ts is not None and ts > prev_ts)
                or (ts == prev_ts and rid > prev_rid)
            )
            if is_newer:
                latest[canon] = (ts, rid, bool(payload.get("confirmed_dofollow", False)))

    return frozenset(url for url, (_ts, _rid, cd) in latest.items() if cd)


def _classify(
    platform: str | None,
    *,
    confirmed_dofollow_urls: frozenset = frozenset(),
    live_url: str | None = None,
) -> tuple[str, str | None]:
    """Return ``(dofollow_class, nofollow_referral)`` for a link's platform."""
    if not platform:
        return "unknown", None
    status = registry.dofollow_status(platform)
    if status is None:
        return "unknown", None
    if status is True:
        return "dofollow", None
    if status == "uncertain":
        if live_url and live_url in confirmed_dofollow_urls:
            return "dofollow", None  # probe confirmed: no nofollow attr
        return "uncertain", None
    # Explicit nofollow → carry the high/low referral sub-grade.
    return "nofollow", registry.referral_value(platform)


def _load_recheck_liveness(store: EventStore | None) -> dict[str, str]:
    """Return ``{canonical live_url: latest recheck verdict}`` for links whose
    freshest ``link.rechecked`` verdict is dead/degraded.

    Mirrors ``_load_confirmed_dofollow_urls`` (one full-table scan, recency by
    ``ts_utc`` with ``events.id`` tiebreak) by reusing the shared
    ``latest_link_verdicts`` reader so the "latest verdict per link" invariant
    can't drift. Only ``host_gone`` / ``link_stripped`` (deterministic dead) and
    ``dofollow_lost`` (live-but-nofollow) are surfaced — ``alive`` keeps the
    link live and ``probe_error`` is indeterminate, so neither overrides the
    recorded ``verified_at`` signal. ``aid:`` fallback keys are dropped: the
    ledger joins links by canonical ``live_url`` only.
    """
    from backlink_publisher.recheck.latest_verdicts import latest_link_verdicts
    from backlink_publisher.recheck.verdicts import (
        DETERMINISTIC_DEAD,
        DOFOLLOW_LOST,
    )

    if store is None:
        return {}

    overriding = DETERMINISTIC_DEAD | {DOFOLLOW_LOST}
    latest, _unkeyable = latest_link_verdicts(store)
    out: dict[str, str] = {}
    for key, lv in latest.items():
        if key.startswith("aid:"):
            continue
        verdict = lv.payload.get("verdict")
        if verdict in overriding:
            out[key] = verdict
    return out


def _link_liveness(
    link: LinkRecord,
    now: datetime,
    stale_days: int,
    *,
    recheck_verdict: str | None = None,
) -> str:
    """Per-link liveness from the recorded verify signal (no fetching).

    A dead latest ``link.rechecked`` verdict (``host_gone`` / ``link_stripped``)
    overrides a stale ``verified_at`` — ``write_verified_at`` only advances on
    ALIVE verdicts, so a dead recheck would otherwise leave the link counted as
    live (the inverse of the live-dofollow-undercounting learning). A benign or
    absent recheck (``alive`` / ``probe_error`` / never rechecked) leaves
    ``recheck_verdict`` None and the recorded verify signal governs.
    """
    from backlink_publisher.recheck.verdicts import is_deterministic_dead

    if recheck_verdict is not None and is_deterministic_dead(recheck_verdict):
        return "failed"
    if link.verify_error:
        return "failed"
    if not link.verified_at:
        return "unverified"
    try:
        verified = datetime.fromisoformat(link.verified_at)
    except (ValueError, TypeError):
        return "unverified"  # unparseable timestamp ⇒ no reliable evidence
    if verified.tzinfo is not None:
        # Writers are inconsistent (recheck uses naive-local; some bind paths
        # emit tz-aware UTC). Fold to naive local so the subtraction against a
        # naive ``now`` can never raise "can't subtract offset-naive/aware".
        verified = verified.astimezone().replace(tzinfo=None)
    return "stale" if (now - verified).days > stale_days else "live"


def build_ledger(
    *,
    stale_days: int = 30,
    store: EventStore | None = None,
    history: Any = None,
) -> list[LedgerRow]:
    """Build the per-target scorecard. ``store``/``history`` injectable for tests.

    Default sort surfaces weak targets first (live-dofollow ascending), a raw
    dimension — not a composite index (plan R6a).
    """
    from backlink_publisher.events import EventStore as _EventStore

    # Resolve store before any call so _load_confirmed_dofollow_urls receives a
    # real EventStore (build_target_buckets resolves store internally but does
    # NOT reassign the caller's local variable).
    store = store or _EventStore()
    confirmed_dofollow_urls = _load_confirmed_dofollow_urls(store)
    # Latest dead/degraded recheck verdict per canonical live_url. A host_gone /
    # link_stripped verdict drops the link from live_links; dofollow_lost keeps
    # it live but strips it from live_dofollow (live-but-nofollow).
    recheck_liveness = _load_recheck_liveness(store)

    now = datetime.now()
    buckets = build_target_buckets(store=store, history=history)
    rows: list[LedgerRow] = []

    for target, bucket in buckets.items():
        breakdown = DofollowBreakdown()
        platforms: set[str] = set()
        live_dofollow_platforms: set[str] = set()
        statuses: list[str] = []
        live_links = 0
        live_dofollow = 0

        # A history row bundling >1 link gives row-level (not per-link) evidence.
        item_link_counts = Counter(
            lk.history_item_id for lk in bucket.links.values() if lk.history_item_id
        )
        row_level = False

        for link in bucket.links.values():
            recheck_verdict = recheck_liveness.get(link.live_url)
            cls, referral = _classify(
                link.platform,
                confirmed_dofollow_urls=confirmed_dofollow_urls,
                live_url=link.live_url,
            )
            # dofollow_lost: link is live but its rel now strips weight, so it no
            # longer counts toward live_dofollow even on a dofollow platform.
            dofollow_lost = recheck_verdict == _DOFOLLOW_LOST
            if cls == "dofollow":
                breakdown.dofollow += 1
            elif cls == "uncertain":
                breakdown.uncertain += 1
            elif cls == "nofollow":
                breakdown.nofollow += 1
                if referral == "high":
                    breakdown.nofollow_high += 1
                elif referral == "low":
                    breakdown.nofollow_low += 1
            else:
                breakdown.unknown += 1

            if link.platform:
                platforms.add(link.platform)

            status = _link_liveness(
                link, now, stale_days, recheck_verdict=recheck_verdict
            )
            statuses.append(status)
            if status == "live":
                live_links += 1
                if cls == "dofollow" and not dofollow_lost:
                    live_dofollow += 1
                    if link.platform:
                        live_dofollow_platforms.add(link.platform)

            if link.history_item_id and item_link_counts[link.history_item_id] > 1:
                row_level = True

        verified_ats = [
            lk.verified_at for lk in bucket.links.values() if lk.verified_at
        ]
        item_ids = sorted(
            {lk.history_item_id for lk in bucket.links.values() if lk.history_item_id}
        )

        rows.append(LedgerRow(
            target_url=target,
            total_links=len(bucket.links),
            live_links=live_links,
            dofollow=breakdown,
            live_dofollow=live_dofollow,
            platform_count=len(platforms),
            platforms=sorted(platforms),
            live_dofollow_platforms=sorted(live_dofollow_platforms),
            exact_match_pct=(
                exact_match_ratio(bucket.profile_entries)
                if bucket.has_anchor_data else 0.0
            ),
            has_anchor_data=bucket.has_anchor_data,
            liveness=worst_liveness(statuses),
            liveness_verified_at=max(verified_ats) if verified_ats else None,
            liveness_row_level=row_level,
            history_item_ids=item_ids,
        ))

    rows.sort(key=lambda r: (r.live_dofollow, r.target_url))
    return rows
