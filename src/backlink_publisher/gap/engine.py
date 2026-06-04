"""Pure deficit-driven re-plan engine (``plan-gap``).

Transforms ``equity-ledger`` rows into ``plan-backlinks`` seed rows: for each
target it computes the live-dofollow deficit (``D - live_dofollow``) and fans it
out across the distinct active dofollow platforms the target does NOT already
hold a live-dofollow link on.

Pure engine (mirrors the contract in ``validate/engine.py`` and
``ledger/aggregate.py``): this module MUST NOT touch ``sys.stdout`` /
``sys.stderr``, call ``set_log_level``, raise ``SystemExit``, read stdin, write
stdout, emit the ``config_echo`` banner, or do network I/O. Registry lookups
(``active_platforms`` / ``dofollow_status``) are in-memory pure reads.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from urllib.parse import urlsplit

from backlink_publisher._util.url import canonicalize_url
from backlink_publisher.bulk_input import derive_main_domain
from backlink_publisher.publishing._registry_manifest import active_platforms
from backlink_publisher.publishing.registry import dofollow_status

#: Liveness values the engine recognizes (mirror ``ledger.model.LivenessStatus``).
#: Anything else is the fail-safe ``unknown_liveness`` outcome (R9) — never a raise.
_KNOWN_LIVENESS = frozenset({"live", "stale", "failed", "unverified"})


@dataclass
class GapOptions:
    """Operator-supplied knobs for one ``plan-gap`` run."""

    desired: int
    language: str
    url_mode: str = "A"
    publish_mode: str = "draft"
    desired_map: dict[str, int] = field(default_factory=dict)
    emit_stale: bool = False
    include_failed: bool = False
    #: Freshness floor in days; ``None`` disables it. A target whose
    #: ``liveness_verified_at`` is older than this (or absent) is suppressed.
    stale_after_days: int | None = None


@dataclass
class SuppressionCounts:
    """Per-reason tally so every dropped target is a loud, counted signal."""

    satisfied: int = 0
    suppressed_stale: int = 0
    suppressed_unverified: int = 0
    suppressed_stale_floor: int = 0
    failed: int = 0
    unknown_liveness: int = 0
    #: Rows that are valid JSON objects but lack a usable ``target_url`` — the
    #: engine skips them fail-safe (never raises) rather than crashing the pipe.
    malformed: int = 0
    channel_exhausted: int = 0
    #: Named targets that have a real deficit but no remaining candidate platform.
    channel_exhausted_targets: list[str] = field(default_factory=list)


def active_dofollow_platforms() -> list[str]:
    """Active platforms whose registry dofollow verdict is exactly ``True``.

    ``"uncertain"`` / ``None`` / ``False`` are excluded. Order follows
    ``active_platforms()`` (sorted) for deterministic fan-out.
    """
    return [p for p in active_platforms() if dofollow_status(p) is True]


def _coerce_live_dofollow(value: object) -> int:
    """Treat a missing/``None``/non-int ``live_dofollow`` as 0 (full deficit)."""
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return max(0, value)


def _verified_older_than(verified_at: object, days: int, now: datetime) -> bool:
    """True when ``verified_at`` is absent, unparseable, or older than ``days``."""
    if not isinstance(verified_at, str) or not verified_at:
        return True
    try:
        dt = datetime.fromisoformat(verified_at)
    except ValueError:
        return True
    if dt.tzinfo is not None:
        dt = dt.astimezone().replace(tzinfo=None)
    return (now - dt).days > days


def plan_gap(
    rows,
    opts: GapOptions,
    *,
    active_dofollow: list[str] | None = None,
    now: datetime | None = None,
):
    """Transform ledger rows → (seed_rows, suppression_counts, liveness_meta).

    ``rows`` is an iterable of equity-ledger dicts (already weakest-first).
    ``active_dofollow`` is injectable for tests; defaults to the live registry.
    ``now`` is injectable for the freshness floor; defaults to ``datetime.now()``.
    """
    candidates_universe = (
        list(active_dofollow) if active_dofollow is not None else active_dofollow_platforms()
    )
    now = now or datetime.now()
    counts = SuppressionCounts()
    seeds: list[dict] = []
    as_of: str | None = None

    for row in rows:
        # Fail-safe: a valid-JSON row missing target_url is skipped + counted,
        # never a KeyError that would crash the pipe (R9 spirit / pure-engine).
        target = row.get("target_url")
        if not isinstance(target, str) or not target:
            counts.malformed += 1
            continue

        verified_at = row.get("liveness_verified_at")
        # as_of: latest verification stamp seen (advisory). Relies on ISO-8601
        # lexical order == chronological order (the build_ledger contract).
        if isinstance(verified_at, str) and (as_of is None or verified_at > as_of):
            as_of = verified_at

        liveness = row.get("liveness", "unverified")
        live_dofollow = _coerce_live_dofollow(row.get("live_dofollow"))

        # --- Classify (R6/R9): EMIT / SUPPRESSED-with-reason / unknown_liveness.
        if liveness not in _KNOWN_LIVENESS:
            counts.unknown_liveness += 1
            continue
        if liveness == "failed":
            if not opts.include_failed:
                counts.failed += 1
                continue
        elif liveness in ("stale", "unverified") and live_dofollow == 0:
            # Deficit unverifiable: no live-dofollow evidence to trust.
            if not opts.emit_stale:
                if liveness == "stale":
                    counts.suppressed_stale += 1
                else:
                    counts.suppressed_unverified += 1
                continue
        # Freshness floor: even an otherwise-eligible target is held if its
        # liveness evidence is older than the operator's threshold.
        if (
            opts.stale_after_days is not None
            and not opts.emit_stale
            and _verified_older_than(verified_at, opts.stale_after_days, now)
        ):
            counts.suppressed_stale_floor += 1
            continue

        # --- Deficit (R3).
        desired = opts.desired_map.get(target, opts.desired)
        deficit = max(0, desired - live_dofollow)
        if deficit == 0:
            counts.satisfied += 1
            continue

        # --- Channel-aware fan-out (R4): subtract the LIVE-DOFOLLOW platform set.
        already_live_df = set(row.get("live_dofollow_platforms") or [])
        candidates = [p for p in candidates_universe if p not in already_live_df]
        emitted = candidates[:deficit]  # one seed per distinct candidate, capped
        if emitted:
            main_domain = derive_main_domain(target)
            for platform in emitted:
                seeds.append({
                    "target_url": target,
                    "platform": platform,
                    "main_domain": main_domain,
                    "language": opts.language,
                    "url_mode": opts.url_mode,
                    "publish_mode": opts.publish_mode,
                })
        # Couldn't fully close the deficit under the current roster — name it so
        # the operator knows the target maxes out below D (incl. the 0-candidate
        # case). Distinct from a silent partial.
        if deficit > len(candidates):
            counts.channel_exhausted += 1
            counts.channel_exhausted_targets.append(target)

    return seeds, counts, {"as_of": as_of}


#: Sticky republish destinations (D2 hard allowlist) — platforms measured at
#: ~0% strip. telegra.ph is deliberately excluded (it causes most strips).
#: Injectable so the runtime can narrow it (e.g. drop ghpages while GitHub is
#: down) without the pure engine knowing about credential availability.
KEEPALIVE_STICKY_PLATFORMS = ("blogger", "ghpages")

#: Hosts that are test fixtures, never a real keep-alive target. The events.db
#: is dominated by example.com test data (seed hygiene — see plan 2026-06-04-001
#: Unit 1 gate finding); a keep-alive gap must never republish to one.
KEEPALIVE_EXCLUDED_HOSTS = frozenset({"example.com"})

#: A link is a republishable gap only when its latest verdict is deterministically
#: dead. ``probe_error`` (timeout/unreachable) is NOT a gap (R1-a) and
#: ``dofollow_lost`` is a separate signal — neither emits a republish seed.
_DEAD_VERDICTS = ("link_stripped", "host_gone")


@dataclass
class KeepaliveGap:
    """One target with ≥1 deterministically-dead link, and where to republish it."""

    target_url: str
    stripped: int                       # link_stripped + host_gone on this target
    emitted_platforms: list[str]        # sticky destinations chosen (may be empty)
    channel_exhausted: bool             # dead links but no free sticky destination


def plan_keepalive_gap(
    rows,
    per_target_status,
    opts: GapOptions,
    *,
    sticky_platforms=KEEPALIVE_STICKY_PLATFORMS,
    exclude_hosts=KEEPALIVE_EXCLUDED_HOSTS,
):
    """Per-link stripped-aware gap (D1): a gap is "a previously-live-dofollow
    link is now stripped", not "page has < N links". Emits republish seeds onto
    sticky platforms for each target with ≥1 dead link.

    This is the **deduped, authoritative** S2 gap set: still-live targets are
    excluded (D6) so the count the operator first sees is the real deficit, and
    test-data hosts are dropped. Unit 7 consumes this set and re-derives it
    server-side at publish time (defense in depth).

    ``rows`` — equity-ledger dicts (``target_url``, ``live_dofollow_platforms``).
    ``per_target_status`` — ``{canonical_target: {"counts": {verdict: n}, ...}}``
    from :func:`recheck.events_io.derive_per_target_status` (the liveness
    authority, keyed by canonical URL). Pure: no I/O, no raises on bad rows.
    """
    seeds: list[dict] = []
    gaps: list[KeepaliveGap] = []

    for row in rows:
        target = row.get("target_url")
        if not isinstance(target, str) or not target:
            continue
        if (urlsplit(target).hostname or "").lower() in exclude_hosts:
            continue
        status = per_target_status.get(canonicalize_url(target))
        if not status:
            continue  # never rechecked → not a known gap (probe_error is a no-op)
        counts = status.get("counts", {})
        stripped = sum(int(counts.get(v, 0)) for v in _DEAD_VERDICTS)
        if stripped == 0:
            continue  # D6: a still-live target is never in the gap set

        already_live = set(row.get("live_dofollow_platforms") or [])
        sticky_avail = [p for p in sticky_platforms if p not in already_live]
        # One republish per dead link, cycling the free sticky destinations
        # (multiple posts to one sticky platform are distinct articles).
        emitted_platforms = (
            [sticky_avail[i % len(sticky_avail)] for i in range(stripped)]
            if sticky_avail else []
        )
        main_domain = derive_main_domain(target)
        for platform in emitted_platforms:
            seeds.append({
                "target_url": target,
                "platform": platform,
                "main_domain": main_domain,
                "language": opts.language,
                "url_mode": opts.url_mode,
                "publish_mode": opts.publish_mode,
            })
        gaps.append(KeepaliveGap(
            target_url=target,
            stripped=stripped,
            emitted_platforms=emitted_platforms,
            channel_exhausted=not sticky_avail,
        ))

    return seeds, gaps
