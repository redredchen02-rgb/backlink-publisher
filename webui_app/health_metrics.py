"""Read-only health aggregations for the publishing dashboard.

Plan 2026-05-25-006 / U2. Pure, deterministic queries over the (post-005-fix)
``events.db`` projection plus ``channel_status``. No mutation, no network.

Honesty rules baked into the queries
------------------------------------
- **Success = ``publish.confirmed`` only.** 005-fix emits a *distinct*
  ``publish.unverified`` kind for a ``done`` whose post-publish verify failed
  (CLI exit 5). The terminal universe is ``confirmed + unverified + failed`` so
  an unverified publish counts *against* success instead of silently vanishing
  from the denominator — that vanishing was exactly the lie this dashboard exists
  to not tell.
- **All queries filter to ``publish.*`` terminal kinds.** The ``events`` table
  also holds banner / image_gen kinds (direct ``EventStore.append``); a bare
  ``COUNT(*)`` would conflate them.
- **Latest-outcome-per-target uses ``ORDER BY ts_utc DESC, id DESC``** — ``ts_utc``
  alone is not a total order (ties across a run), so ``id`` is the tiebreak.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, UTC
import functools
import logging

from backlink_publisher.events import EventStore

_log = logging.getLogger(__name__)


def fail_open(default=None):
    """Decorator that catches all exceptions and returns a default value.

    Used by health metric functions that must never 500 the page.
    Logs the exception at warning level for debugging.
    """
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001
                _log.warning("health_metrics: %s failed: %s", fn.__name__, exc)
                return default() if callable(default) else default
        return wrapper
    return decorator


#: Terminal publish kinds. ``publish.intent`` is non-terminal and excluded.
_TERMINAL_KINDS = ("publish.confirmed", "publish.unverified", "publish.failed")

#: A per-adapter row with fewer than this many terminal events is flagged as a
#: small sample — its percentage is statistically noisy and the UI says so.
SMALL_SAMPLE_THRESHOLD = 5

#: Channel-status values that mean "operator must act".
_BROKEN_STATUSES = ("expired", "identity_mismatch")

#: Default look-back window.
DEFAULT_WINDOW_DAYS = 30


@dataclass(frozen=True)
class SuccessRate:
    """Overall hero: distinct targets by latest in-window terminal outcome."""

    targets: int = 0
    confirmed: int = 0
    pct: float | None = None  # None == "no data" (denominator 0), not "0%"

    @property
    def has_data(self) -> bool:
        return self.targets > 0


@dataclass(frozen=True)
class AdapterHealth:
    platform: str  # "Unattributed" when the event carried no platform
    confirmed: int
    unverified: int
    failed: int
    total: int
    pct: float | None
    small_sample: bool


@dataclass(frozen=True)
class ErrorBucket:
    error_class: str  # "unclassified" when the failed event carried no class
    count: int


@dataclass(frozen=True)
class BrokenChannel:
    channel: str
    status: str  # one of _BROKEN_STATUSES
    last_verified_at: str | None = None


@dataclass(frozen=True)
class Health:
    window_days: int
    since_utc: str
    success: SuccessRate
    per_adapter: list[AdapterHealth] = field(default_factory=list)
    errors: list[ErrorBucket] = field(default_factory=list)
    broken: list[BrokenChannel] = field(default_factory=list)


def _window_start(now: datetime, window_days: int) -> str:
    """ISO-8601 UTC lower bound, matching the projector's ts_utc format.

    Events store ``ts_utc`` as ``...+00:00`` ISO strings; the same format here
    makes the ``ts_utc >= ?`` comparison a correct lexicographic range check.
    """
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    return (now.astimezone(UTC) - timedelta(days=window_days)).isoformat()


def success_rate(store: EventStore, *, since_utc: str) -> SuccessRate:
    """Per distinct ``target_url``, take the latest in-window terminal event;
    success = that latest is ``publish.confirmed``."""
    placeholders = ",".join("?" for _ in _TERMINAL_KINDS)
    rows = store.query(
        f"""
        WITH latest AS (
            SELECT target_url, kind,
                   ROW_NUMBER() OVER (
                       PARTITION BY target_url
                       ORDER BY ts_utc DESC, id DESC
                   ) AS rn
            FROM events
            WHERE kind IN ({placeholders})
              AND ts_utc >= ?
              AND target_url IS NOT NULL
        )
        SELECT
            COUNT(*) AS targets,
            SUM(CASE WHEN kind = 'publish.confirmed' THEN 1 ELSE 0 END) AS confirmed
        FROM latest
        WHERE rn = 1
        """,
        (*_TERMINAL_KINDS, since_utc),
    )
    row = rows[0]
    targets = int(row["targets"] or 0)
    confirmed = int(row["confirmed"] or 0)
    pct = round(confirmed * 100.0 / targets, 1) if targets else None
    return SuccessRate(targets=targets, confirmed=confirmed, pct=pct)


def per_adapter(store: EventStore, *, since_utc: str) -> list[AdapterHealth]:
    """Per-platform terminal-event counts, worst success-rate first."""
    placeholders = ",".join("?" for _ in _TERMINAL_KINDS)
    rows = store.query(
        f"""
        SELECT
            json_extract(payload_json, '$.platform') AS platform,
            SUM(CASE WHEN kind = 'publish.confirmed' THEN 1 ELSE 0 END) AS confirmed,
            SUM(CASE WHEN kind = 'publish.unverified' THEN 1 ELSE 0 END) AS unverified,
            SUM(CASE WHEN kind = 'publish.failed' THEN 1 ELSE 0 END) AS failed,
            COUNT(*) AS total
        FROM events
        WHERE kind IN ({placeholders})
          AND ts_utc >= ?
        GROUP BY platform
        """,
        (*_TERMINAL_KINDS, since_utc),
    )
    out: list[AdapterHealth] = []
    for r in rows:
        total = int(r["total"] or 0)
        confirmed = int(r["confirmed"] or 0)
        out.append(
            AdapterHealth(
                platform=r["platform"] if r["platform"] is not None else "Unattributed",
                confirmed=confirmed,
                unverified=int(r["unverified"] or 0),
                failed=int(r["failed"] or 0),
                total=total,
                pct=round(confirmed * 100.0 / total, 1) if total else None,
                small_sample=total < SMALL_SAMPLE_THRESHOLD,
            )
        )
    # Worst-first: lowest success pct leads; treat None pct as worst; break ties
    # by larger sample so a 0/20 outranks a 0/1.
    out.sort(key=lambda a: (a.pct if a.pct is not None else -1.0, -a.total))
    return out


def error_distribution(store: EventStore, *, since_utc: str) -> list[ErrorBucket]:
    """Counts of ``publish.failed`` events grouped by ``error_class``."""
    rows = store.query(
        """
        SELECT
            json_extract(payload_json, '$.error_class') AS error_class,
            COUNT(*) AS count
        FROM events
        WHERE kind = 'publish.failed'
          AND ts_utc >= ?
        GROUP BY error_class
        ORDER BY count DESC, error_class
        """,
        (since_utc,),
    )
    return [
        ErrorBucket(
            error_class=r["error_class"] if r["error_class"] is not None else "unclassified",
            count=int(r["count"] or 0),
        )
        for r in rows
    ]


def decay_counts(store: EventStore | None = None) -> dict[str, int]:
    """Backlink decay counts by latest recheck verdict (Plan 2026-05-29-004 U6).

    Thin wrapper over ``recheck.events_io.derive_decay_counts`` so the /ce:health
    route reads decay state through the same health-metrics surface as the other
    aggregations. Reports current state (latest verdict per link, no age window —
    an old un-rechecked dead link still counts).
    """
    from backlink_publisher.recheck.events_io import derive_decay_counts

    return derive_decay_counts(store if store is not None else EventStore())


def broken_channels() -> list[BrokenChannel]:
    """Channels currently flagged expired / identity_mismatch (display-only).

    Reactive: ``channel_status`` only models the channels that publish through
    it (velog/medium/blogger) and flips on failure, not proactively — the UI
    labels this scope honestly (R9). No network.
    """
    from webui_store.channel_status import list_all

    out: list[BrokenChannel] = []
    for channel, rec in sorted(list_all().items()):
        if not isinstance(rec, dict):
            continue
        status = rec.get("status")
        if status in _BROKEN_STATUSES:
            out.append(
                BrokenChannel(
                    channel=channel,
                    status=status,
                    last_verified_at=rec.get("last_verified_at"),
                )
            )
    return out


def geo_citation_share(store: EventStore, *, window_days: int = DEFAULT_WINDOW_DAYS) -> list[dict]:
    """Return per-target citation share data from ``citation.observed`` events.

    Groups ``citation.observed`` events by ``target_url``, computing the
    share metrics that mirror the :class:`~backlink_publisher.geo.share.TargetShare`
    states (never_probed / warming_up / measured / excluded).  Uses
    ``json_extract`` to pull ``verdict`` from ``payload_json``.

    Rolling window: last ``window_days`` days. Read-only; never raises.
    """

    from backlink_publisher.events.kinds import CITATION_OBSERVED
    from backlink_publisher.geo.share import (
        DEFAULT_LOW_CONFIDENCE_THRESHOLD,
        DEFAULT_MIN_SAMPLE,
    )

    since = _window_start(datetime.now(UTC), window_days)

    # Fetch per-target verdict counts and total n in the rolling window.
    # site_cited / article_cited split surfaces in the citation panel (R6).
    rows = store.query(
        """
        SELECT
            target_url,
            COUNT(*) AS total_n,
            SUM(CASE WHEN json_extract(payload_json, '$.verdict') = 'site_cited'
                     THEN 1 ELSE 0 END) AS site_cited,
            SUM(CASE WHEN json_extract(payload_json, '$.verdict') = 'article_cited'
                     THEN 1 ELSE 0 END) AS article_cited,
            SUM(CASE WHEN json_extract(payload_json, '$.verdict') = 'absent'
                     THEN 1 ELSE 0 END) AS absent,
            SUM(CASE WHEN json_extract(payload_json, '$.verdict') = 'refused'
                     THEN 1 ELSE 0 END) AS refused
        FROM events
        WHERE kind = ?
          AND ts_utc >= ?
          AND target_url IS NOT NULL
        GROUP BY target_url
        ORDER BY target_url
        """,
        (CITATION_OBSERVED, since),
    )

    out: list[dict] = []
    for r in rows:
        target_url = r["target_url"]
        total_n = int(r["total_n"] or 0)
        site_cited = int(r["site_cited"] or 0)
        article_cited = int(r["article_cited"] or 0)
        cited = site_cited + article_cited
        absent = int(r["absent"] or 0)
        refused = int(r["refused"] or 0)
        denominator = cited + absent  # refused excluded per D3

        refused_rate = round(refused / total_n, 4) if total_n else 0.0

        if denominator < DEFAULT_MIN_SAMPLE:
            state = "warming_up"
            share = None
            low_confidence = False
        else:
            state = "measured"
            share = round(cited / denominator * 100, 1)
            low_confidence = denominator < DEFAULT_LOW_CONFIDENCE_THRESHOLD

        out.append({
            "target_url": target_url,
            "state": state,
            "share": share,
            "n": denominator,
            "total_n": total_n,
            "site_cited": site_cited,
            "article_cited": article_cited,
            "absent": absent,
            "refused_rate": refused_rate,
            "low_confidence": low_confidence,
        })

    return out


def weights_snapshot() -> dict | None:
    """Return latest weights optimize summary for the /ce:health panel (Plan 2026-06-16-002 U9).

    Reads ``optimization_state.json`` via ``OptimizationState().to_summary()``.
    Returns top-3 platforms by current weight descending, plus the most-recent
    ``updated_at`` timestamp. Returns ``None`` when no state exists or on any error
    (fail-open: never raises).
    """
    try:
        from backlink_publisher.optimization import OptimizationState

        summary = OptimizationState().to_summary()
        platforms = summary.get("platforms") or []
        if not platforms:
            return None
        top3 = sorted(platforms, key=lambda p: float(p.get("current", 1.0)), reverse=True)[:3]
        return {
            "updated_at": summary.get("last_updated"),
            "top_channels": [
                {"name": p["name"], "weight": p["current"], "updated_at": p.get("updated_at")}
                for p in top3
            ],
        }
    except Exception:  # noqa: BLE001 — fail-open, never 500
        return None


@fail_open(default=[])
def indexation_status(store: EventStore) -> list[dict]:
    """Return GSC page-signal status grouped by target_url (Plan 2026-06-16-003 U6).

    Reads ``gsc.page_signal`` events from the last 90 days and groups by
    target_url, counting pages that appeared vs. did not appear in GSC.
    Returns ``[]`` when no data exists (never raises — fail-open).
    """
    from backlink_publisher.events.kinds import GSC_PAGE_SIGNAL

    # Data shape (appeared_count/absent_count, ORDER BY target_url) kept as
    # local's original, NOT origin's renamed appeared/absent/appeared_pct —
    # verified two real consumers depend on the original names:
    # webui_app/templates/health.html:667-668 reads row.appeared_count/
    # absent_count directly, and tests/test_gsc_health_metrics.py:90-91
    # asserts on those exact keys. Origin's rename would have broken both.
    # The @fail_open decorator (origin's addition) replaces the old inner
    # try/except — kept, since it's a real boilerplate-reduction with no
    # effect on the returned shape.
    since = _window_start(datetime.now(UTC), 90)
    rows = store.query(
        """
        SELECT
            target_url,
            COUNT(*) AS total,
            SUM(CASE WHEN json_extract(payload_json, '$.has_impressions') = 1
                     THEN 1 ELSE 0 END) AS appeared_count,
            SUM(CASE WHEN json_extract(payload_json, '$.has_impressions') = 0
                     THEN 1 ELSE 0 END) AS absent_count
        FROM events
        WHERE kind = ?
          AND ts_utc >= ?
          AND target_url IS NOT NULL
        GROUP BY target_url
        ORDER BY target_url
        """,
        (GSC_PAGE_SIGNAL, since),
    )
    return [
        {
            "target_url": r["target_url"],
            "total": int(r["total"] or 0),
            "appeared_count": int(r["appeared_count"] or 0),
            "absent_count": int(r["absent_count"] or 0),
        }
        for r in rows
    ]


def ranking_trend(store: EventStore) -> list[dict]:
    """Return keyword ranking trend: oldest snapshot vs. latest (Plan 2026-06-16-003 U6).

    Compares the oldest ``ranking.snapshot`` event per keyword (baseline,
    taken with pre-build window -60d to -30d) against the most recent one
    (regular weekly probe, recent 30d). Returns delta and trend arrow.
    Returns ``[]`` when no data (never raises).
    """
    try:
        from backlink_publisher.events.kinds import RANKING_SNAPSHOT

        rows = store.query(
            """
            SELECT
                json_extract(payload_json, '$.keyword') AS keyword,
                json_extract(
                    (SELECT payload_json FROM events e2
                     WHERE e2.kind = ? AND json_extract(e2.payload_json, '$.keyword')
                           = json_extract(e1.payload_json, '$.keyword')
                           AND e1.target_url IS NOT NULL
                     ORDER BY e2.ts_utc ASC LIMIT 1),
                    '$.avg_position'
                ) AS baseline_pos,
                json_extract(
                    (SELECT payload_json FROM events e3
                     WHERE e3.kind = ? AND json_extract(e3.payload_json, '$.keyword')
                           = json_extract(e1.payload_json, '$.keyword')
                           AND e1.target_url IS NOT NULL
                     ORDER BY e3.ts_utc DESC LIMIT 1),
                    '$.avg_position'
                ) AS latest_pos
            FROM events e1
            WHERE kind = ?
              AND json_extract(payload_json, '$.keyword') IS NOT NULL
              AND target_url IS NOT NULL
            GROUP BY json_extract(payload_json, '$.keyword')
            ORDER BY json_extract(payload_json, '$.keyword')
            """,
            (RANKING_SNAPSHOT, RANKING_SNAPSHOT, RANKING_SNAPSHOT),
        )

        out = []
        for r in rows:
            kw = r["keyword"]
            baseline = r["baseline_pos"]
            latest = r["latest_pos"]
            if baseline is not None and latest is not None:
                delta = round(float(baseline) - float(latest), 1)
                trend = "↑" if delta > 0 else ("↓" if delta < 0 else "→")
            else:
                delta = None
                trend = "—"
            out.append({
                "keyword": kw,
                "baseline_position": baseline,
                "latest_position": latest,
                "delta": delta,
                "trend": trend,
            })
        return out
    except Exception:  # noqa: BLE001 — fail-open, never 500
        return []


def build_health(
    store: EventStore | None = None,
    *,
    now: datetime | None = None,
    window_days: int = DEFAULT_WINDOW_DAYS,
) -> Health:
    """Assemble the four aggregates for a single dashboard render."""
    store = store or EventStore()
    now = now or datetime.now(UTC)
    since = _window_start(now, window_days)
    return Health(
        window_days=window_days,
        since_utc=since,
        success=success_rate(store, since_utc=since),
        per_adapter=per_adapter(store, since_utc=since),
        errors=error_distribution(store, since_utc=since),
        broken=broken_channels(),
    )


# ── P1 GSC Decision-Making Intelligence helpers (Plan 2026-06-24-001) ──────


def publish_to_index_latency(
    store: EventStore,
    *,
    window_days: int = DEFAULT_WINDOW_DAYS,
) -> list[dict]:
    """Per-platform publish-to-indexation latency (Plan 2026-06-24-001 P1.1).

    Computes ``days_to_index = (ts_first_seen - ts_published)`` for every
    target_url that has a ``gsc.page_signal`` with ``has_impressions=1`` and
    a recorded ``ts_published``. Groups by the platform recorded on the
    latest ``publish.confirmed`` for that target_url.

    Returns ``[]`` on any read error (fail-open). Each entry carries
    ``platform``, ``p50_days``, ``p90_days``, ``count`` (sample size).
    """
    try:
        from backlink_publisher.events.kinds import GSC_PAGE_SIGNAL, PUBLISH_CONFIRMED

        since = _window_start(datetime.now(UTC), window_days)
        rows = store.query(
            """
            SELECT
                target_url,
                MIN(ts_utc) AS ts_first_seen,
                json_extract(payload_json, '$.ts_published') AS ts_published
            FROM events
            WHERE kind = ?
              AND json_extract(payload_json, '$.has_impressions') = 1
              AND ts_utc >= ?
              AND target_url IS NOT NULL
            GROUP BY target_url
            HAVING ts_published IS NOT NULL
            """,
            (GSC_PAGE_SIGNAL, since),
        )

        # Map target_url -> platform from the latest publish.confirmed
        platform_map: dict[str, str] = {}
        for r in rows:
            url = r["target_url"]
            pub_rows = store.query(
                """
                SELECT json_extract(payload_json, '$.platform') AS platform
                FROM events
                WHERE kind = ? AND target_url = ?
                ORDER BY ts_utc DESC LIMIT 1
                """,
                (PUBLISH_CONFIRMED, url),
            )
            if pub_rows and pub_rows[0]["platform"]:
                platform_map[url] = pub_rows[0]["platform"]

        samples: dict[str, list[float]] = {}
        for r in rows:
            url = r["target_url"]
            platform = platform_map.get(url, "Unattributed")
            published = r["ts_published"]
            first_seen = r["ts_first_seen"]
            if not published or not first_seen:
                continue
            try:
                pub_dt = datetime.fromisoformat(published)
                seen_dt = datetime.fromisoformat(first_seen)
                delta_days = max(
                    0, (seen_dt - pub_dt).total_seconds() / 86400
                )
            except (ValueError, TypeError):
                continue
            samples.setdefault(platform, []).append(round(delta_days, 1))

        out: list[dict] = []
        for platform, vals in sorted(samples.items()):
            vals.sort()
            n = len(vals)
            p50 = vals[n // 2] if n else 0.0
            p90_idx = int(n * 0.9)
            p90 = vals[min(p90_idx, n - 1)] if n else 0.0
            out.append({
                "platform": platform,
                "p50_days": p50,
                "p90_days": p90,
                "count": n,
            })
        out.sort(key=lambda x: -x["count"])
        return out
    except Exception:  # noqa: BLE001 — fail-open, never 500
        return []


def index_rate_by_channel(
    store: EventStore,
    *,
    window_days: int = DEFAULT_WINDOW_DAYS,
) -> list[dict]:
    """Indexed-page ratio per channel (Plan 2026-06-24-001 P1.2).

    ``index_rate = pages_with_impressions / total_published_pages`` per channel.
    Channels with an index rate below ``ADVISORY_THRESHOLD`` (10 %) carry
    ``advisory=True`` so the UI can flag them.

    Returns ``[]`` on any read error (fail-open). Each entry carries
    ``platform``, ``index_rate`` (0–100 float or ``None``), ``indexed``,
    ``total``, ``advisory``.
    """
    ADVISORY_THRESHOLD = 10.0

    try:
        from backlink_publisher.events.kinds import GSC_PAGE_SIGNAL, PUBLISH_CONFIRMED

        since = _window_start(datetime.now(UTC), window_days)
        placeholders = ",".join("?" for _ in _TERMINAL_KINDS)

        # Total confirmed pages per channel in the window.
        total_rows = store.query(
            f"""
            SELECT
                json_extract(payload_json, '$.platform') AS platform,
                COUNT(DISTINCT target_url) AS total
            FROM events
            WHERE kind IN ({placeholders})
              AND ts_utc >= ?
              AND target_url IS NOT NULL
            GROUP BY platform
            """,
            (*_TERMINAL_KINDS, since),
        )

        # Pages that appeared in GSC per channel.
        appeared_rows = store.query(
            """
            SELECT
                json_extract(pc.payload_json, '$.platform') AS platform,
                COUNT(DISTINCT gs.target_url) AS indexed
            FROM events gs
            JOIN events pc
              ON pc.target_url = gs.target_url
             AND pc.kind = ?
             AND pc.ts_utc = (
                 SELECT MIN(ts_utc) FROM events
                 WHERE kind = ? AND target_url = gs.target_url
             )
            WHERE gs.kind = ?
              AND gs.json_extract(payload_json, '$.has_impressions') = 1
              AND gs.ts_utc >= ?
              AND gs.target_url IS NOT NULL
            GROUP BY platform
            """,
            (PUBLISH_CONFIRMED, PUBLISH_CONFIRMED, GSC_PAGE_SIGNAL, since),
        )

        total_by_platform: dict[str, int] = {}
        for r in total_rows:
            plat = r["platform"] or "Unattributed"
            total_by_platform[plat] = int(r["total"] or 0)

        appeared_by_platform: dict[str, int] = {}
        for r in appeared_rows:
            plat = r["platform"] or "Unattributed"
            appeared_by_platform[plat] = int(r["indexed"] or 0)

        out: list[dict] = []
        all_platforms = sorted(set(total_by_platform) | set(appeared_by_platform))
        for plat in all_platforms:
            total = total_by_platform.get(plat, 0)
            indexed = appeared_by_platform.get(plat, 0)
            rate = round(indexed * 100.0 / total, 1) if total else None
            out.append({
                "platform": plat,
                "index_rate": rate,
                "indexed": indexed,
                "total": total,
                "advisory": rate is not None and rate < ADVISORY_THRESHOLD,
            })
        out.sort(key=lambda x: (x["index_rate"] if x["index_rate"] is not None else -1.0), reverse=True)
        return out
    except Exception:  # noqa: BLE001 — fail-open, never 500
        return []


def impression_analysis(
    store: EventStore,
    *,
    window_days: int = DEFAULT_WINDOW_DAYS,
) -> list[dict]:
    """Per-target GSC impression aggregation (Plan 2026-06-24-001 P1.3).

    Sums ``impressions`` from ``gsc.page_signal`` events over the last
    ``window_days`` (default 30 d). A target with no signal in the window
    is omitted.

    Returns ``[]`` on any read error (fail-open). Each entry carries
    ``target_url``, ``impressions``, ``has_indexed`` (boolean derived
    from the latest signal's ``has_impressions``), ``last_probe_ts``.
    """
    try:
        from backlink_publisher.events.kinds import GSC_PAGE_SIGNAL

        since = _window_start(datetime.now(UTC), window_days)
        rows = store.query(
            """
            SELECT
                target_url,
                SUM(CAST(json_extract(payload_json, '$.impressions') AS INTEGER)) AS impressions,
                MAX(ts_utc) AS last_probe_ts,
                MAX(CASE WHEN json_extract(payload_json, '$.has_impressions') = 1 THEN 1 ELSE 0 END) AS has_indexed
            FROM events
            WHERE kind = ?
              AND ts_utc >= ?
              AND target_url IS NOT NULL
            GROUP BY target_url
            ORDER BY impressions DESC
            """,
            (GSC_PAGE_SIGNAL, since),
        )
        return [
            {
                "target_url": r["target_url"],
                "impressions": int(r["impressions"] or 0),
                "has_indexed": bool(r["has_indexed"]),
                "last_probe_ts": r["last_probe_ts"],
            }
            for r in rows
        ]
    except Exception:  # noqa: BLE001 — fail-open, never 500
        return []


def ranking_lift_analysis(
    store: EventStore,
    *,
    window_days: int = DEFAULT_WINDOW_DAYS,
) -> list[dict]:
    """Keyword ranking delta from snapshot history (Plan 2026-06-24-001 P1.4).

    Compares oldest baseline vs latest snapshot per keyword within the
    window. Returns ``[]`` on any read error (fail-open). Each entry carries
    ``keyword``, ``baseline_position``, ``latest_position``, ``delta``,
    ``trend``, ``impressions_latest`` (from the most recent snapshot's payload).
    """
    try:
        from backlink_publisher.events.kinds import RANKING_SNAPSHOT

        since = _window_start(datetime.now(UTC), window_days)
        rows = store.query(
            """
            SELECT
                json_extract(payload_json, '$.keyword') AS keyword,
                json_extract(
                    (SELECT payload_json FROM events e2
                     WHERE e2.kind = ? AND json_extract(e2.payload_json, '$.keyword')
                           = json_extract(e1.payload_json, '$.keyword')
                           AND e1.target_url IS NOT NULL
                     ORDER BY e2.ts_utc ASC LIMIT 1),
                    '$.avg_position'
                ) AS baseline_pos,
                json_extract(
                    (SELECT payload_json FROM events e3
                     WHERE e3.kind = ? AND json_extract(e3.payload_json, '$.keyword')
                           = json_extract(e1.payload_json, '$.keyword')
                           AND e1.target_url IS NOT NULL
                     ORDER BY e3.ts_utc DESC LIMIT 1),
                    '$.avg_position'
                ) AS latest_pos,
                json_extract(
                    (SELECT payload_json FROM events e4
                     WHERE e4.kind = ? AND json_extract(e4.payload_json, '$.keyword')
                           = json_extract(e1.payload_json, '$.keyword')
                     ORDER BY e4.ts_utc DESC LIMIT 1),
                    '$.impressions'
                ) AS latest_impressions
            FROM events e1
            WHERE kind = ?
              AND json_extract(payload_json, '$.keyword') IS NOT NULL
              AND target_url IS NOT NULL
              AND ts_utc >= ?
            GROUP BY json_extract(payload_json, '$.keyword')
            ORDER BY json_extract(payload_json, '$.keyword')
            """,
            (
                RANKING_SNAPSHOT, RANKING_SNAPSHOT,
                RANKING_SNAPSHOT, RANKING_SNAPSHOT,
                since,
            ),
        )

        out = []
        for r in rows:
            kw = r["keyword"]
            baseline = r["baseline_pos"]
            latest = r["latest_pos"]
            latest_impressions = r["latest_impressions"]
            if baseline is not None and latest is not None:
                delta = round(float(baseline) - float(latest), 1)
                trend = "↑" if delta > 0 else ("↓" if delta < 0 else "→")
            else:
                delta = None
                trend = "—"
            out.append({
                "keyword": kw,
                "baseline_position": baseline,
                "latest_position": latest,
                "delta": delta,
                "trend": trend,
                "latest_impressions": int(latest_impressions or 0),
            })
        return out
    except Exception:  # noqa: BLE001 — fail-open, never 500
        return []


def referral_conversion(
    store: EventStore,
    *,
    window_days: int = DEFAULT_WINDOW_DAYS,
) -> list[dict]:
    """Referral-sessions-to-indexed-pages conversion per channel (Plan 2026-06-24-001 P1.5).

    Joins ``referral.observed`` events with ``publish.confirmed`` by
    ``target_url``. ``conversion_rate = referral_sessions / indexed_pages``.

    Returns ``[]`` on any read error (fail-open). Each entry carries
    ``platform``, ``referral_sessions``, ``indexed_pages``, ``conversion_rate``
    (float 0–∞ or ``None`` when denominator is zero).
    """
    try:
        from backlink_publisher.events.kinds import (
            GSC_PAGE_SIGNAL,
            PUBLISH_CONFIRMED,
            REFERRAL_OBSERVED,
        )

        since = _window_start(datetime.now(UTC), window_days)

        # Referral sessions per channel.
        ref_rows = store.query(
            """
            SELECT
                json_extract(payload_json, '$.channel') AS channel,
                SUM(CAST(json_extract(payload_json, '$.sessions') AS INTEGER)) AS sessions
            FROM events
            WHERE kind = ?
              AND ts_utc >= ?
              AND target_url IS NOT NULL
            GROUP BY channel
            """,
            (REFERRAL_OBSERVED, since),
        )
        ref_by_platform: dict[str, int] = {}
        for r in ref_rows:
            ch = r["channel"] or "Unattributed"
            ref_by_platform[ch] = int(r["sessions"] or 0)

        # Indexed pages per channel (latest publish.confirmed platform per target_url).
        platform_rows = store.query(
            """
            SELECT target_url,
                   json_extract(payload_json, '$.platform') AS platform
            FROM events
            WHERE kind = ?
              AND ts_utc >= ?
              AND target_url IS NOT NULL
            """,
            (PUBLISH_CONFIRMED, since),
        )
        platform_by_url: dict[str, str] = {}
        for r in platform_rows:
            if r["platform"]:
                platform_by_url[r["target_url"]] = r["platform"]

        indexed_rows = store.query(
            """
            SELECT target_url FROM events
            WHERE kind = ?
              AND ts_utc >= ?
              AND target_url IS NOT NULL
              AND json_extract(payload_json, '$.has_impressions') = 1
            GROUP BY target_url
            """,
            (GSC_PAGE_SIGNAL, since),
        )
        indexed_urls = {r["target_url"] for r in indexed_rows}

        indexed_by_platform: dict[str, int] = {}
        for url in indexed_urls:
            plat = platform_by_url.get(url, "Unattributed")
            indexed_by_platform[plat] = indexed_by_platform.get(plat, 0) + 1

        out: list[dict] = []
        all_platforms = sorted(set(ref_by_platform) | set(indexed_by_platform))
        for plat in all_platforms:
            ref = ref_by_platform.get(plat, 0)
            idx = indexed_by_platform.get(plat, 0)
            rate = round(ref / idx, 4) if idx else None
            out.append({
                "platform": plat,
                "referral_sessions": ref,
                "indexed_pages": idx,
                "conversion_rate": rate,
            })
        out.sort(key=lambda x: -(x["referral_sessions"]))
        return out
    except Exception:  # noqa: BLE001 — fail-open, never 500
        return []


def cost_metrics(
    store: EventStore,
    *,
    window_days: int = DEFAULT_WINDOW_DAYS,
) -> dict:
    """Publish-effort cost proxies (Plan 2026-06-24-001 P1.6).

    ``total_publish_cost`` is the total count of terminal publish events
    (a coarse effort proxy — no per-publish monetary cost is tracked in
    events.db). Returns ``cost_per_indexed_url`` and
    ``cost_per_ranking_gain``, or ``None`` when the denominator is zero.

    Returns ``{}`` on any read error (fail-open).
    """
    try:
        from backlink_publisher.events.kinds import (
            GSC_PAGE_SIGNAL,
            RANKING_SNAPSHOT,
        )

        since = _window_start(datetime.now(UTC), window_days)
        placeholders = ",".join("?" for _ in _TERMINAL_KINDS)

        cost_rows = store.query(
            f"""
            SELECT COUNT(*) AS total FROM events
            WHERE kind IN ({placeholders}) AND ts_utc >= ?
            """,
            (*_TERMINAL_KINDS, since),
        )
        total_cost = int(cost_rows[0]["total"] or 0) if cost_rows else 0

        indexed_rows = store.query(
            """
            SELECT COUNT(DISTINCT target_url) AS cnt FROM events
            WHERE kind = ? AND ts_utc >= ?
              AND target_url IS NOT NULL
              AND json_extract(payload_json, '$.has_impressions') = 1
            """,
            (GSC_PAGE_SIGNAL, since),
        )
        indexed_count = int(indexed_rows[0]["cnt"] or 0) if indexed_rows else 0

        ranking_rows = store.query(
            """
            SELECT json_extract(payload_json, '$.keyword') AS keyword,
                   json_extract(
                       (SELECT payload_json FROM events e2
                        WHERE e2.kind = ? AND json_extract(e2.payload_json, '$.keyword')
                              = json_extract(e1.payload_json, '$.keyword')
                        ORDER BY e2.ts_utc ASC LIMIT 1),
                       '$.avg_position'
                   ) AS baseline_pos,
                   json_extract(
                       (SELECT payload_json FROM events e3
                        WHERE e3.kind = ? AND json_extract(e3.payload_json, '$.keyword')
                              = json_extract(e1.payload_json, '$.keyword')
                        ORDER BY e3.ts_utc DESC LIMIT 1),
                       '$.avg_position'
                   ) AS latest_pos
            FROM events e1
            WHERE kind = ?
              AND json_extract(payload_json, '$.keyword') IS NOT NULL
              AND target_url IS NOT NULL
              AND ts_utc >= ?
            GROUP BY json_extract(payload_json, '$.keyword')
            """,
            (RANKING_SNAPSHOT, RANKING_SNAPSHOT, RANKING_SNAPSHOT, since),
        )
        ranking_gain = 0.0
        for r in ranking_rows:
            b = r["baseline_pos"]
            latest = r["latest_pos"]
            if b is not None and latest is not None:
                delta = float(b) - float(latest)
                if delta > 0:
                    ranking_gain += delta

        cost_per_indexed = round(total_cost / indexed_count, 2) if indexed_count else None
        cost_per_gain = round(total_cost / ranking_gain, 2) if ranking_gain else None

        return {
            "total_publish_events": total_cost,
            "indexed_pages": indexed_count,
            "ranking_gain": round(ranking_gain, 1),
            "cost_per_indexed_url": cost_per_indexed,
            "cost_per_ranking_gain": cost_per_gain,
        }
    except Exception:  # noqa: BLE001 — fail-open, never 500
        return {}


def decisions_by_platform(
    store: EventStore,
    *,
    window_days: int = DEFAULT_WINDOW_DAYS,
) -> list[dict]:
    """Reliability policy decisions grouped by platform (Plan 2026-06-24-001 P0 follow-up).

    ``reliability.decision`` events are written by ``publishing.reliability.policy``
    but were not surfaced by any existing health query. This helper makes
    observe-mode decisions queryable so the P0 dashboard can show a rollout
    panel.

    Returns ``[]`` on any read error (fail-open). Each entry carries
    ``platform``, ``decision``, ``mode``, ``count``, ``latest_ts``.
    """
    try:
        from backlink_publisher.events.kinds import RELIABILITY_DECISION

        since = _window_start(datetime.now(UTC), window_days)
        rows = store.query(
            """
            SELECT
                json_extract(payload_json, '$.platform') AS platform,
                json_extract(payload_json, '$.decision') AS decision,
                json_extract(payload_json, '$.mode') AS mode,
                COUNT(*) AS count,
                MAX(ts_utc) AS latest_ts
            FROM events
            WHERE kind = ?
              AND ts_utc >= ?
              AND target_url IS NOT NULL
            GROUP BY platform, decision, mode
            ORDER BY platform, decision
            """,
            (RELIABILITY_DECISION, since),
        )
        return [
            {
                "platform": r["platform"] or "Unattributed",
                "decision": r["decision"],
                "mode": r["mode"],
                "count": int(r["count"] or 0),
                "latest_ts": r["latest_ts"],
            }
            for r in rows
        ]
    except Exception:  # noqa: BLE001 — fail-open, never 500
        return []
