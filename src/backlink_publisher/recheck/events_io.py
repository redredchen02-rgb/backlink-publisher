"""Emit ``link.rechecked`` events and derive decay counts from the time series.

Write side (``emit_recheck``) is WAL-safe: all appends share ONE transaction and
quarantined floor-misses flush only AFTER the transaction commits — writing a
quarantine row while holding the WAL write lock deadlocks (the projector
silent-drop lesson, docs/solutions/logic-errors/projector-silent-drop-...).

Read side (``derive_decay_counts``) reports the *latest* verdict per link with
NO age window: a link that went ``host_gone`` 40 days ago and was never
re-probed must still count as decayed — windowing it out would make abandonment
look like recovery. (``suspected_dead`` derivation is deferred to a fast-follow,
Plan 2026-05-29-004 D5.)
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import TYPE_CHECKING

from backlink_publisher.events._project_helpers import write_quarantines
from backlink_publisher.events.kinds import LINK_RECHECKED
from backlink_publisher.recheck import indexability, verdicts
from backlink_publisher.recheck.selection import _parse_ts

if TYPE_CHECKING:
    from backlink_publisher.events.store import EventStore

log = logging.getLogger(__name__)


def emit_recheck(store: "EventStore", results: list[dict]) -> int:
    """Append one ``link.rechecked`` event per probed result. Returns the number
    of events written (floor-misses are quarantined, not counted).

    ``results`` are :func:`recheck.probe.recheck_link` outputs; dry-preview rows
    (no ``verdict``) are skipped.
    """
    pending_quarantines: list[dict] = []
    written = 0
    with store.connect() as conn:
        for r in results:
            verdict = r.get("verdict")
            if verdict is None:
                continue
            payload = {
                "verdict": verdict,
                "reason": r.get("reason"),
                "live_url": r.get("live_url"),
                "platform": r.get("platform"),
                "expected_nofollow": bool(r.get("expected_nofollow")),
                "anchor_drift": bool(r.get("anchor_drift")),
                "anchor_baseline_missing": bool(r.get("anchor_baseline_missing")),
                # Orthogonal indexability axis (additive — NOT in the floor).
                # Fail-open to UNKNOWN if absent so a reader never mistakes an
                # unclassified page for indexable. ``indexability_reason`` is
                # clamped to the closed vocab AT THIS SEAM (never raw bytes).
                "indexability": r.get("indexability") or indexability.UNKNOWN,
                "indexability_reason": (
                    r.get("indexability_reason")
                    if r.get("indexability_reason") in indexability.REASON_VOCAB
                    else None
                ),
                "source": r.get("source", "events"),
            }
            event_id = store.append(
                LINK_RECHECKED,
                payload,
                target_url=r.get("target_url"),
                host=r.get("host"),
                article_id=r.get("article_id"),
                conn=conn,
                pending_quarantines=pending_quarantines,
            )
            if event_id != -1:
                written += 1
    # Flush quarantines AFTER the transaction commits (WAL-deadlock avoidance).
    write_quarantines(store, pending_quarantines)
    return written


def derive_decay_counts(store: "EventStore") -> dict[str, int]:
    """Count links by their latest ``link.rechecked`` verdict (current state).

    Returns a count for every verdict in :data:`verdicts.VERDICTS` (0 when
    absent). The dashboard banner (U6) keys off ``host_gone`` / ``link_stripped``
    / ``dofollow_lost``; ``alive`` / ``probe_error`` are returned for context.
    """
    counts = {v: 0 for v in verdicts.VERDICTS}
    latest: dict[int, tuple[datetime | None, str]] = {}  # article_id -> (ts, verdict)
    sql = (
        "SELECT article_id, payload_json, ts_utc FROM events "
        "WHERE kind = ? AND article_id IS NOT NULL"
    )
    for row in store.query(sql, (LINK_RECHECKED,)):
        try:
            verdict = json.loads(row["payload_json"] or "{}").get("verdict")
        except (ValueError, TypeError):
            continue
        if verdict not in verdicts.VERDICTS:
            continue
        ts = _parse_ts(row["ts_utc"])
        aid = row["article_id"]
        prev = latest.get(aid)
        if prev is None or (ts is not None and (prev[0] is None or ts > prev[0])):
            latest[aid] = (ts, verdict)
    for _ts, verdict in latest.values():
        counts[verdict] += 1
    return counts


def derive_per_target_status(store: "EventStore") -> dict[str, dict]:
    """Per-target latest-verdict breakdown (R3 keep-alive scorecard authority).

    Like :func:`derive_decay_counts` but grouped by ``target_url`` instead of
    aggregated globally: returns, for each target that has any ``link.rechecked``
    event, the latest verdict per link (keyed by ``article_id``), the resulting
    per-verdict counts, and the most-recent recheck timestamp. The ledger
    liveness column is stale (recheck→ledger writeback is deferred), so this
    time-series read — not the ledger — is the authority for "is this link
    stripped *now*".
    """
    # link.rechecked.target_url is stored raw; canonicalize so canonically-equal
    # raw variants (utm tags, trailing-slash / default-port drift, mixed publish
    # vintages) merge into ONE scorecard row instead of one silently overwriting
    # the other downstream — reusing the same _canon_target the ledger-overlay
    # join uses. events.id breaks same-ts_utc ties so the "latest verdict" read
    # is deterministic (mirrors overlay._is_newer / R8), independent of SQL row
    # order. Without it a same-second alive could mask a later link_stripped.
    from .overlay import _canon_target, _is_newer

    # (canonical target, article_id) -> (ts, rid, verdict); latest wins.
    latest: dict[tuple[str, int], tuple[datetime | None, int, str]] = {}
    last_seen: dict[str, tuple[datetime | None, int]] = {}
    sql = (
        "SELECT id, target_url, article_id, payload_json, ts_utc FROM events "
        "WHERE kind = ? AND article_id IS NOT NULL AND target_url IS NOT NULL"
    )
    for row in store.query(sql, (LINK_RECHECKED,)):
        try:
            verdict = json.loads(row["payload_json"] or "{}").get("verdict")
        except (ValueError, TypeError):
            continue
        if verdict not in verdicts.VERDICTS:
            continue
        target = _canon_target(row["target_url"])
        if target is None:
            continue
        ts = _parse_ts(row["ts_utc"])
        rid = row["id"]
        key = (target, row["article_id"])
        prev = latest.get(key)
        if prev is None or _is_newer(ts, rid, prev[0], prev[1]):
            latest[key] = (ts, rid, verdict)
        seen = last_seen.get(target)
        if seen is None or _is_newer(ts, rid, seen[0], seen[1]):
            last_seen[target] = (ts, rid)

    out: dict[str, dict] = {}
    for (target, _aid), (_ts, _rid, verdict) in latest.items():
        entry = out.setdefault(
            target,
            {"counts": {v: 0 for v in verdicts.VERDICTS}, "total": 0, "last_verified": None},
        )
        entry["counts"][verdict] += 1
        entry["total"] += 1
    for target, entry in out.items():
        seen = last_seen.get(target)
        ts = seen[0] if seen else None
        entry["last_verified"] = ts.isoformat() if ts is not None else None
    return out
