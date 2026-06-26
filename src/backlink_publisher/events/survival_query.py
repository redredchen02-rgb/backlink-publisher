"""30-day link survival cohort query (plan 008 R5).

Computes the survival rate for links published ≥ 30 days ago — the percentage
whose *latest definitive* ``link.rechecked`` verdict is "alive".  Distinct from:

- ``optimization/rules.py``  per-platform ``survival_rate``  (no cohort)
- ``gates/g5_footprint_survival.py``  (DOM fingerprint gate)
- keep-alive scorecard  (per-target strip counts)

Derives survival from ``link.rechecked`` verdicts written by the CLI weekly
job; does NOT read ``articles.verified_at`` (stale — CLI doesn't write it).

``probe_error`` is indeterminate and does NOT clobber a prior definitive verdict;
the latest DEFINITIVE verdict wins per article.
"""

from __future__ import annotations

from datetime import datetime, UTC
import json
from typing import Any

from backlink_publisher.events.store import EventStore
from backlink_publisher.recheck import verdicts as _v

#: Hosts excluded from the operator dashboard (test fixtures).
_EXCLUDED_HOSTS = frozenset({"example.com"})

#: Minimum days since publish for a link to count as "mature".
MATURITY_DAYS = 30

#: Minimum cohort size to show a meaningful percentage.
MIN_COHORT_N = 2

KIND_CONFIRMED = "publish.confirmed"
KIND_RECHECKED = "link.rechecked"

#: Indeterminate verdicts that don't clobber a prior definitive verdict.
_INDETERMINATE = frozenset({_v.PROBE_ERROR})


def _utcnow() -> datetime:
    return datetime.now(tz=UTC)


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


def compute_survival(
    store: EventStore | None = None,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return the 30-day survival payload for the dashboard.

    ``store`` may be positional for test convenience.

    Return shape::

        {
            "state": "ok" | "insufficient" | "empty",
            "survival_rate": float | None,   # None when state != "ok"
            "sample_size": int,              # mature articles with any recheck event
            "survived": int,                 # latest-definitive alive count
            "mature_count": int,             # all mature articles (incl. stale)
            "maturing_count": int,           # published < MATURITY_DAYS old
            "stale": bool,                   # any mature articles never rechecked
            "stale_count": int,              # count of never-rechecked mature articles
            "partial": bool,                 # same as stale
            "stale_days": int | None,        # age (days) of oldest stale article
        }
    """
    store = store or EventStore()
    now = now or _utcnow()
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)

    with store.connect() as conn:
        # Anchor cohort on publish.confirmed events. Group by article_id to get
        # the earliest confirmed publish per article (some articles may have
        # multiple confirmed events after republish cycles).
        # Exclude test-fixture hosts in the query to avoid picking up example.com
        # article_ids that might appear in recheck events too.
        placeholder = ",".join("?" * len(_EXCLUDED_HOSTS))
        article_rows = conn.execute(
            f"""
            SELECT
                article_id,
                host,
                MIN(ts_utc) AS publish_ts
            FROM events
            WHERE kind = ?
              AND article_id IS NOT NULL
              AND (host IS NULL OR host NOT IN ({placeholder}))
            GROUP BY article_id
            """,
            (KIND_CONFIRMED, *_EXCLUDED_HOSTS),
        ).fetchall()

        # All link.rechecked events ordered by id (ascending) for definitive-wins logic.
        recheck_rows = conn.execute(
            """
            SELECT article_id, payload_json, ts_utc
            FROM events
            WHERE kind = ? AND article_id IS NOT NULL
            ORDER BY id
            """,
            (KIND_RECHECKED,),
        ).fetchall()

    # Build per-article recheck index:
    # {article_id: (has_any_recheck, latest_definitive_verdict)}
    # Indeterminate verdicts (probe_error) do NOT clobber a prior definitive one.
    _any_recheck: set[int] = set()
    _definitive: dict[int, str | None] = {}
    for aid, pj, _ in recheck_rows:
        _any_recheck.add(aid)
        try:
            payload = json.loads(pj) if pj else {}
        except (ValueError, TypeError):
            payload = {}
        verdict = payload.get("verdict")
        if verdict not in _INDETERMINATE:
            _definitive[aid] = verdict

    # Classify articles by maturity.
    mature: list[tuple[int, int]] = []  # (article_id, age_days)
    maturing_count = 0
    for aid, host, publish_ts_str in article_rows:
        publish_ts = _parse_ts(publish_ts_str)
        if publish_ts is None:
            continue
        age_days = (now - publish_ts).days
        if age_days >= MATURITY_DAYS:
            mature.append((aid, age_days))
        else:
            maturing_count += 1

    mature_count = len(mature)

    if mature_count == 0:
        return {
            "state": "empty",
            "survival_rate": None,
            "sample_size": 0,
            "survived": 0,
            "mature_count": 0,
            "maturing_count": maturing_count,
            "stale": False,
            "stale_count": 0,
            "partial": False,
            "stale_days": None,
        }

    # Among mature articles, separate rechecked (in sample) from stale (never rechecked).
    rechecked_ids = [aid for aid, _ in mature if aid in _any_recheck]
    stale_articles = [(aid, age) for aid, age in mature if aid not in _any_recheck]

    sample_size = len(rechecked_ids)
    stale_count = len(stale_articles)
    stale = stale_count > 0
    partial = stale
    stale_days = max((age for _, age in stale_articles), default=None)

    survived = sum(1 for aid in rechecked_ids if _definitive.get(aid) == _v.ALIVE)

    if sample_size < MIN_COHORT_N:
        return {
            "state": "insufficient",
            "survival_rate": None,
            "sample_size": sample_size,
            "survived": survived,
            "mature_count": mature_count,
            "maturing_count": maturing_count,
            "stale": stale,
            "stale_count": stale_count,
            "partial": partial,
            "stale_days": stale_days,
        }

    survival_rate = round(survived / sample_size, 4)
    return {
        "state": "ok",
        "survival_rate": survival_rate,
        "sample_size": sample_size,
        "survived": survived,
        "mature_count": mature_count,
        "maturing_count": maturing_count,
        "stale": stale,
        "stale_count": stale_count,
        "partial": partial,
        "stale_days": stale_days,
    }


# Alias for service layer — keeps backward-compat without a re-export shim.
query_survival = compute_survival
