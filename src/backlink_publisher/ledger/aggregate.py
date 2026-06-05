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

import json
from collections import Counter
from datetime import datetime
from typing import TYPE_CHECKING

from backlink_publisher._util.url import canonicalize_url
from backlink_publisher.anchor.metrics import exact_match_ratio
from backlink_publisher.publishing import registry

# Importing the adapters package populates the registry via its ``register()``
# side effects. Without this the registry is empty and every link classifies as
# ``unknown`` — so the engine must trigger registration itself rather than rely
# on the caller having imported adapters.
import backlink_publisher.publishing.adapters  # noqa: F401,E402

from .model import DofollowBreakdown, LedgerRow, worst_liveness
from .sources import LinkRecord, build_target_buckets

if TYPE_CHECKING:
    from backlink_publisher.events.store import EventStore


def _load_confirmed_dofollow_urls(store: "EventStore") -> frozenset:
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


def _link_liveness(link: LinkRecord, now: datetime, stale_days: int) -> str:
    """Per-link liveness from the recorded verify signal (no fetching)."""
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
    store=None,
    history=None,
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
            cls, referral = _classify(
                link.platform,
                confirmed_dofollow_urls=confirmed_dofollow_urls,
                live_url=link.live_url,
            )
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

            status = _link_liveness(link, now, stale_days)
            statuses.append(status)
            if status == "live":
                live_links += 1
                if cls == "dofollow":
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
