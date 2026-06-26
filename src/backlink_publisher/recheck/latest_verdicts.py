"""Shared latest-``link.rechecked``-verdict-per-link reader.

The "latest verdict per link, keyed on canonical ``live_url`` (article_id
fallback), recency by ``(ts_utc, events.id)``" invariant is load-bearing in two
places: the equity overlay (``overlay.build_discount_map``) and the scorecard
per-link drawer (``scorecard.links.derive_links_by_channel``). It lives here — a
stable module — so both read through one implementation and the NULL-article_id
safety cannot drift between them (the "two truths" risk).

Keying on canonical ``live_url`` — NOT ``article_id``, which is NULL on
stdin-sourced rechecks — and NOT filtering ``article_id IS NOT NULL`` is the whole
point: ``derive_per_target_status`` does filter it and silently drops exactly the
headless verdicts a per-link reader must surface.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import logging
import sqlite3
from typing import Any, TYPE_CHECKING

from backlink_publisher._util.errors import DependencyError
from backlink_publisher._util.url import canonicalize_url
from backlink_publisher.events.kinds import LINK_RECHECKED
from backlink_publisher.recheck.selection import _parse_ts

if TYPE_CHECKING:
    from backlink_publisher.events.store import EventStore

log = logging.getLogger(__name__)


@dataclass
class LatestVerdict:
    """The freshest ``link.rechecked`` row for one link.

    ``target_url`` is the raw events column (may be ``None``); ``payload`` is the
    decoded JSON payload; ``rid`` is the ``events.id`` recency tiebreaker.
    """

    ts: datetime | None
    rid: int
    payload: dict[str, Any]
    target_url: str | None
    article_id: int | None


def _canon_target(value: object) -> str | None:
    """Canonicalize a URL for matching; ``None`` for null/blank/unparseable.

    Defensive against a malformed URL whose invalid port makes ``urlsplit``
    raise (the url-parse-never-raises lesson): reported unusable, never a crash.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return canonicalize_url(value)
    except ValueError:
        return None


def _is_newer(
    ts: datetime | None,
    rid: int,
    prev_ts: datetime | None,
    prev_rid: int,
) -> bool:
    """True if ``(ts, rid)`` is a later verdict than ``(prev_ts, prev_rid)``.

    ``ts_utc`` is primary (a real timestamp beats ``None``); ``events.id`` breaks a
    same-``ts_utc`` tie. Deterministic given a fixed event set.
    """
    if ts is None and prev_ts is None:
        return rid > prev_rid
    if prev_ts is None:
        return True
    if ts is None:
        return False
    if ts != prev_ts:
        return ts > prev_ts
    return rid > prev_rid


def latest_link_verdicts(
    store: EventStore,
) -> tuple[dict[str, LatestVerdict], int]:
    """Read the latest ``link.rechecked`` verdict per link. Read-only.

    Returns ``(latest_by_key, unkeyable_count)`` where the key is the canonical
    ``live_url`` (``"aid:<article_id>"`` fallback). A row with neither ``live_url``
    nor ``article_id`` is unidentifiable: counted in ``unkeyable_count``, never
    silently dropped (the projector-silent-drop lesson).

    Returns empty when no events.db exists. Raises ``DependencyError`` (exit 3)
    when an existing events.db is unreadable.
    """
    latest: dict[str, LatestVerdict] = {}
    unkeyable = 0
    # Absent events.db → nothing to read. Check before any connect() so a
    # read-only verb never materializes an empty database as a side effect.
    if not store.path.exists():
        return latest, unkeyable

    try:
        rows = store.query(
            "SELECT article_id, target_url, payload_json, ts_utc, id "
            "FROM events WHERE kind = ?",
            (LINK_RECHECKED,),
        )
    except sqlite3.Error as exc:
        raise DependencyError(
            f"latest-verdicts: events.db unreadable: {exc}"
        ) from exc

    for row in rows:
        try:
            payload = json.loads(row["payload_json"] or "{}")
        except (ValueError, TypeError):
            payload = {}
        live_url = payload.get("live_url")
        key = _canon_target(live_url) if isinstance(live_url, str) else None
        if key is None:
            aid = row["article_id"]
            key = f"aid:{aid}" if aid is not None else None
        if key is None:
            unkeyable += 1
            continue
        ts = _parse_ts(row["ts_utc"])
        rid = row["id"]
        prev = latest.get(key)
        if prev is None or _is_newer(ts, rid, prev.ts, prev.rid):
            latest[key] = LatestVerdict(
                ts, rid, payload, row["target_url"], row["article_id"]
            )
    return latest, unkeyable
