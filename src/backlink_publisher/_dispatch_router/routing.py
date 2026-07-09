"""Routing engine core — platform selection logic for dispatch-backlinks.

Determines the best platform for each row given signal data, ledger
coverage, and the selected strategy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, UTC
from typing import Any

from .signals import PlatformSignal

#: Current routing engine version. Bump when routing logic changes
#: in a way that may produce different output for the same input.
ENGINE_VERSION = 2

#: Default stale-days for canary data (no env override for v1).
DEFAULT_CANARY_STALE_DAYS = 7

#: Dofollow tier scores for ranking.
_DOFOLLOW_TIER: dict[str, int] = {
    "dofollow": 4,
    "uncertain": 2,
    "nofollow": 1,
}
#: Referral bonus (added to tier score).
_REFERRAL_BONUS: dict[str, int] = {
    "high": 1,
    "low": 0,
}
#: Max spread bonus (applied when platform has fewest existing covers).
_MAX_SPREAD_BONUS = 3


def _score_dofollow_tier(dofollow: bool | str | None) -> int:
    """Map dofollow status to a numeric tier."""
    if dofollow is True:
        return _DOFOLLOW_TIER["dofollow"]
    if dofollow == "uncertain":
        return _DOFOLLOW_TIER["uncertain"]
    # False means nofollow; None means unknown/unregistered
    return _DOFOLLOW_TIER["nofollow"]


def _score_nofollow_bonus(dofollow: bool | str | None, referral: str | None) -> int:
    """For nofollow platforms, add referral value bonus."""
    if dofollow is True or dofollow == "uncertain":
        return 0
    return _REFERRAL_BONUS.get(referral or "low", 0)


def _downgrade_if_stale(
    sig: PlatformSignal,
    stale_days: int | None,
    now: datetime,
) -> bool | str | None:
    """If canary data is too old, downgrade dofollow confidence.

    Returns the original or downgraded dofollow value.
    """
    if stale_days is None:
        # Use default unless explicitly disabled (0 = no downgrade).
        stale_days = DEFAULT_CANARY_STALE_DAYS
    if stale_days <= 0:
        return sig.dofollow

    if not sig.canary_last_ok_at:
        return sig.dofollow  # no canary data yet

    try:
        last_ok = datetime.fromisoformat(sig.canary_last_ok_at)
    except (ValueError, TypeError):
        return sig.dofollow

    # Make last_ok timezone-aware if naive (assume UTC)
    if last_ok.tzinfo is None:
        last_ok = last_ok.replace(tzinfo=UTC)

    age = (now - last_ok).total_seconds() / 86400
    if age <= stale_days:
        return sig.dofollow

    # Downgrade: True -> uncertain, uncertain -> nofollow
    if sig.dofollow is True:
        return "uncertain"
    if sig.dofollow == "uncertain":
        return False  # effectively nofollow
    return sig.dofollow


@dataclass
class RouteResult:
    """Result of routing one row."""

    # Assigned platform (None = no suitable platform found)
    platform: str | None
    # Dispatch metadata for the output _dispatch block
    dispatch: dict[str, Any] = field(default_factory=dict)


def _filter_candidates(
    signals: dict[str, PlatformSignal],
    row_language: str,
) -> tuple[list[PlatformSignal], dict[str, str]]:
    """Phase 1: exclude unavailable platforms.

    Gates (in order): visibility, binding, language whitelist, quarantine.
    Returns (surviving candidates, {excluded_name: reason}).
    """
    candidates: list[PlatformSignal] = []
    excluded: dict[str, str] = {}

    for name, sig in signals.items():
        # Visibility gate
        if sig.visibility in ("retired", "hidden"):
            excluded[name] = "visibility"
            continue

        # Binding gate (bound/anon only)
        if sig.binding not in ("bound",):
            excluded[name] = "binding"
            continue

        # Language whitelist gate
        if sig.language_whitelist and row_language:
            if row_language not in sig.language_whitelist:
                excluded[name] = "language"
                continue

        # Canary quarantine gate
        if sig.quarantined:
            excluded[name] = "quarantined"
            continue

        candidates.append(sig)

    return candidates, excluded


def _resolve_live_dofollow_platforms(
    row: dict[str, Any],
    ledger_map: dict[str, dict[str, Any]] | None,
) -> list[str]:
    """Look up the live-dofollow platform list for this row's target URL."""
    target_url = row.get("url") or row.get("target_url") or row.get("uri") or ""
    if ledger_map and target_url in ledger_map:
        lr = ledger_map[target_url]
        return lr.get("live_dofollow_platforms", [])
    return []


def _strategy_score(
    strategy: str,
    base_score: float,
    spread_bonus: int,
) -> float:
    """Combine base score and spread bonus per strategy (pre dispatch_weight)."""
    if strategy == "quality":
        # Pure quality: dofollow/referral only
        return base_score

    if strategy == "spread":
        # Favor platforms that have fewer existing covers
        return base_score * 0.5 + float(spread_bonus) * 3.0

    # balanced (default)
    return base_score + float(spread_bonus)


def _score_candidate(
    sig: PlatformSignal,
    strategy: str,
    canary_stale_days: int | None,
    now: datetime,
    live_dofollow_platforms: list[str],
) -> float:
    """Phase 2 (per-candidate): apply staleness downgrade, tier/referral
    scoring, strategy combination, and dispatch_weight scaling.
    """
    # Apply canary-stale downgrade
    effective_dofollow = _downgrade_if_stale(sig, canary_stale_days, now)

    tier_score = _score_dofollow_tier(effective_dofollow)
    referral_bonus = _score_nofollow_bonus(effective_dofollow, sig.referral)
    base_score = float(tier_score + referral_bonus)

    cover_count = live_dofollow_platforms.count(sig.name)
    spread_bonus = max(0, _MAX_SPREAD_BONUS - cover_count)

    score = _strategy_score(strategy, base_score, spread_bonus)
    return score * sig.dispatch_weight


def _build_reason(
    strategy: str,
    sig: PlatformSignal | None,
    live_dofollow_platforms: list[str],
) -> str:
    """Phase 3: build the human-readable reason string for the winner."""
    reason_parts: list[str] = [strategy]

    if sig:
        dof_str = str(sig.dofollow) if sig.dofollow is not None else "unknown"
        reason_parts.append(f"dofollow={dof_str}")
        if sig.dispatch_weight != 1.0:
            reason_parts.append(f"dispatch_weight={sig.dispatch_weight}")
        if live_dofollow_platforms:
            if sig.name not in live_dofollow_platforms:
                reason_parts.append("new_platform")
            else:
                n = live_dofollow_platforms.count(sig.name)
                reason_parts.append(f"existing_cover={n}")

    return ", ".join(reason_parts)


def route(
    row: dict[str, Any],
    signals: dict[str, PlatformSignal],
    ledger_map: dict[str, dict[str, Any]] | None = None,
    strategy: str = "balanced",
    canary_stale_days: int | None = None,
) -> RouteResult:
    """Determine the best platform for ``row`` given available signals.

    The routing pipeline:
    1. Filter: exclude unavailable platforms (not bound, language mismatch,
       quarantined, retired, hidden).
    2. Score: rank remaining platforms by strategy-specific criteria.
    3. Select: pick the highest-scored platform.

    Args:
        row: A single plan-backlinks output row (dict).
        signals: Collected PlatformSignal mapping (from collect_all()).
        ledger_map: Target URL -> LedgerRow dict for spread analysis.
            None or empty when ledger data is unavailable.
        strategy: One of "balanced", "quality", "spread".
        canary_stale_days: Max age (days) for canary data before dofollow
            downgrade. 0 = disable downgrade.

    Returns:
        RouteResult with platform name (or None) and dispatch metadata.
    """
    now = datetime.now(UTC)
    row_language = row.get("language") or row.get("lang") or ""

    # ── Phase 1: Filter ──────────────────────────────────────────────
    candidates, excluded = _filter_candidates(signals, row_language)

    if not candidates:
        return RouteResult(
            platform=None,
            dispatch={
                "strategy": strategy,
                "engine_version": ENGINE_VERSION,
                "candidates": [],
                "excluded": excluded,
                "reason": "no_available_platforms",
            },
        )

    # ── Phase 2: Score ───────────────────────────────────────────────
    live_dofollow_platforms = _resolve_live_dofollow_platforms(row, ledger_map)

    scored: list[tuple[float, str]] = [
        (
            _score_candidate(sig, strategy, canary_stale_days, now, live_dofollow_platforms),
            sig.name,
        )
        for sig in candidates
    ]

    # ── Phase 3: Select ──────────────────────────────────────────────
    scored.sort(key=lambda x: (-x[0], x[1]))  # desc score, asc name tiebreak
    best_name = scored[0][1] if scored else None

    sig = signals.get(best_name) if best_name else None
    reason = _build_reason(strategy, sig, live_dofollow_platforms)

    return RouteResult(
        platform=best_name,
        dispatch={
            "strategy": strategy,
            "engine_version": ENGINE_VERSION,
            "candidates": [s.name for s in candidates],
            "excluded": excluded,
            "reason": reason,
        },
    )
