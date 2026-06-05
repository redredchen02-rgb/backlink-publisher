"""30-day survival-rate cohort query (R5) — sibling to ``history_query.py``.

Computes "% of links published >= ``cohort_days`` ago whose latest definitive
``link.rechecked`` verdict is ``alive`` (live + dofollow)". Deliberately small
and self-contained: it does **not** overload ``events_io.py`` or the optimisation
rules engine, and it derives survival from the ``link.rechecked`` time series
(which the weekly CLI job writes) — never from ``articles.verified_at`` (which
the CLI does not write).

Honesty is the contract, not a non-empty number: immature links are surfaced
separately (not folded into the rate), an ``n < MIN_SAMPLE`` cohort suppresses
the percentage, mature links with no definitive verdict are flagged ``stale``
(rate marked partial), and ``example.com`` test hosts never count.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit
from typing import Any

from . import kinds as _kinds
from .store import EventStore
from backlink_publisher.recheck import verdicts
from backlink_publisher.recheck.selection import _parse_ts

#: Test-fixture hosts, never counted in the operator-facing rate.
_EXCLUDED_HOSTS = frozenset({"example.com"})

#: Default maturity window: a link must be at least this old to enter the rate.
COHORT_DAYS = 30

#: Below this many *judged* links the percentage is statistically meaningless
#: and is suppressed (the sample size is still surfaced).
MIN_SAMPLE = 2

#: Verdicts that constitute a definitive judgement (probe_error is indeterminate
#: and never overwrites a real verdict nor counts toward the denominator).
_DEFINITIVE = frozenset(
    {verdicts.ALIVE, verdicts.HOST_GONE, verdicts.LINK_STRIPPED, verdicts.DOFOLLOW_LOST}
)


def _host(url: str | None) -> str:
    if not url:
        return ""
    return (urlsplit(url).hostname or "").lower()


def _loads(raw: str | None) -> dict:
    try:
        data = json.loads(raw or "{}")
        return data if isinstance(data, dict) else {}
    except (ValueError, TypeError):
        return {}


def _aware(ts: datetime | None) -> datetime | None:
    if ts is None:
        return None
    return ts if ts.tzinfo is not None else ts.replace(tzinfo=timezone.utc)


def compute_survival(
    store: EventStore | None = None,
    *,
    now: datetime | None = None,
    cohort_days: int = COHORT_DAYS,
) -> dict[str, Any]:
    """Return the survival cohort summary (JSON-serializable, no sets).

    ``store``/``now`` are injectable for tests.
    """
    store = store or EventStore()
    now = _aware(now) or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=cohort_days)

    # 1. Latest publish.confirmed per article_id → cohort anchor (ts + host).
    confirmed: dict[int, dict] = {}
    for row in store.query(
        "SELECT ts_utc, host, article_id, payload_json FROM events "
        "WHERE kind = ? ORDER BY ts_utc, id",
        (_kinds.PUBLISH_CONFIRMED,),
    ):
        aid = row["article_id"]
        if aid is None:
            continue
        payload = _loads(row["payload_json"])
        host = (row["host"] or _host(payload.get("live_url")) or "").lower()
        confirmed[aid] = {"ts": _aware(_parse_ts(row["ts_utc"])), "host": host}

    # 2. Latest *definitive* link.rechecked verdict per article_id (latest-wins;
    #    probe_error is skipped so it never clobbers a real verdict).
    verdict_by_aid: dict[int, str] = {}
    for row in store.query(
        "SELECT ts_utc, article_id, payload_json FROM events "
        "WHERE kind = ? ORDER BY ts_utc, id",
        (_kinds.LINK_RECHECKED,),
    ):
        aid = row["article_id"]
        if aid is None:
            continue
        v = _loads(row["payload_json"]).get("verdict")
        if v in _DEFINITIVE:
            verdict_by_aid[aid] = v

    # 3. Classify the cohort.
    mature_total = maturing = survived = definitive = 0
    stale_days_max = 0
    for aid, info in confirmed.items():
        if info["host"] in _EXCLUDED_HOSTS:
            continue
        ts = info["ts"]
        if ts is None:
            continue
        if ts > cutoff:
            maturing += 1
            continue
        mature_total += 1
        v = verdict_by_aid.get(aid)
        if v is None:
            stale_days_max = max(stale_days_max, (now - ts).days)
            continue
        definitive += 1
        if v == verdicts.ALIVE:
            survived += 1

    stale_count = mature_total - definitive

    if mature_total == 0:
        state, rate = ("empty" if maturing == 0 else "maturing"), None
    elif definitive < MIN_SAMPLE:
        state, rate = "insufficient", None
    else:
        state, rate = "ok", survived / definitive

    return {
        "state": state,
        "cohort_days": cohort_days,
        "survival_rate": rate,
        "survival_pct": None if rate is None else round(rate * 100, 1),
        "survived": survived,
        "sample_size": definitive,      # the rate denominator (judged links)
        "mature_count": mature_total,
        "maturing_count": maturing,
        "stale_count": stale_count,
        "stale": stale_count > 0,
        "stale_days": stale_days_max if stale_count > 0 else None,
        "partial": stale_count > 0,     # rate computed over a partial cohort
    }
