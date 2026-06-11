"""Rules Engine — evaluate optimisation rules against platform stats.

Two v1 rules:

**Rule 1 — ``canary_drift``**: When a platform's ``drift_count`` exceeds
*max_strikes* (default 3), its dispatch weight is reduced by *multiplier*
(default 0.5). The strike count is measured since the last time the rule
applied (the rule records a "strike-reset" each time it applies, so
subsequent cycles start fresh). When drift_count returns to 0, the rule
restores the weight to its base value.

**Rule 2 — ``recheck_survival``**: When a platform has *min_confirmations*
(default 2) or more recheck cycles where
``alive_count / total_published >= survival_threshold`` (0.5) AND
``dofollow_count / alive_count >= dofollow_threshold`` (0.5), its weight
is boosted by *multiplier* (default 1.2), capped at *max_cap* (default 3.0).
"""

from __future__ import annotations

import datetime
import logging
from typing import Any

from .models import RuleResult, now_iso

logger = logging.getLogger(__name__)

# Rule names
RULE_CANARY_DRIFT = "canary_drift"
RULE_RECHECK_SURVIVAL = "recheck_survival"
RULE_AGGREGATED_STATS = "aggregated_stats"
RULE_SURVIVAL_THRESHOLD = "survival_threshold"


def evaluate_rules(
    state_data: dict[str, Any],
    rule_filter: str | None = None,
) -> list[RuleResult]:
    """Evaluate all enabled rules against the current state.

    Returns a list of ``RuleResult`` dataclass instances describing every
    weight change (or attempted change). When *rule_filter* is set, only
    that rule is evaluated.
    """
    results: list[RuleResult] = []
    rules_config = state_data.get("rules", {})

    for rule_name in (RULE_CANARY_DRIFT, RULE_RECHECK_SURVIVAL, RULE_AGGREGATED_STATS, RULE_SURVIVAL_THRESHOLD):
        if rule_filter is not None and rule_name != rule_filter:
            continue
        config = rules_config.get(rule_name, {})
        if not config.get("enabled", True):
            logger.debug("Rule %s is disabled — skipping", rule_name)
            continue

        fn = _RULE_REGISTRY.get(rule_name)
        if fn is None:
            logger.warning("Unknown rule %s — skipping", rule_name)
            continue

        try:
            rule_results = fn(state_data, config)
            results.extend(rule_results)
        except Exception:
            logger.exception("Rule %s raised unexpectedly — skipping", rule_name)

    return results


# ---------------------------------------------------------------------------
# Rule 1: Canary Drift → Fuse
# ---------------------------------------------------------------------------


def _rule_canary_drift(
    state_data: dict[str, Any],
    config: dict[str, Any],
) -> list[RuleResult]:
    """Reduce weight for platforms with sustained forward-path drift.

    When ``drift_count >= max_strikes`` the platform weight is set to **0**
    and a cooldown timer starts.  During the ``cooldown_days`` window the
    rule skips the platform entirely.  After cooldown the weight recovers to
    ``base_weight * canary_recovery`` (a slow-start multiplier, default 0.3)
    so the platform gets a second chance.
    """
    multiplier = float(config.get("multiplier", 0.5))
    max_strikes = int(config.get("max_strikes", 3))
    cooldown_days = int(config.get("cooldown_days", 7))
    canary_recovery = float(config.get("canary_recovery", 0.3))
    weights = state_data.get("weights", {})
    stats = state_data.get("stats", {})
    results: list[RuleResult] = []

    for platform, platform_stats in stats.items():
        drift_count = int(platform_stats.get("drift_count", 0))
        entry = weights.get(platform, {})
        current_weight = _get_current_weight(weights, platform)
        base_weight = _get_base_weight(weights, platform, 1.0)

        if drift_count == 0:
            # No drift — restore base weight if currently suppressed
            if current_weight < base_weight:
                results.append(
                    _make_result(
                        platform, RULE_CANARY_DRIFT,
                        old_weight=current_weight, new_weight=base_weight,
                        multiplier=1.0,
                        reason=f"drift cleared (drift_count=0) — restored to base {base_weight}",
                        applied=True,
                    )
                )
            continue

        if drift_count >= max_strikes:
            if current_weight == 0 and entry.get("rule") == RULE_CANARY_DRIFT:
                updated_at_str = entry.get("updated_at", "")
                if updated_at_str:
                    try:
                        suppressed_dt = datetime.datetime.fromisoformat(updated_at_str)
                        elapsed = (datetime.datetime.now() - suppressed_dt).total_seconds()
                        if elapsed < cooldown_days * 86400:
                            results.append(
                                _make_result(
                                    platform, RULE_CANARY_DRIFT,
                                    old_weight=current_weight, new_weight=current_weight,
                                    multiplier=1.0,
                                    reason=f"in cooldown ({int(elapsed // 86400)}d/{cooldown_days}d) — skip",
                                    applied=False,
                                )
                            )
                            continue
                        new_weight = max(base_weight * canary_recovery, 0.01)
                        results.append(
                            _make_result(
                                platform, RULE_CANARY_DRIFT,
                                old_weight=current_weight, new_weight=new_weight,
                                multiplier=canary_recovery,
                                reason=f"cooldown expired — slow-start recovery to {new_weight}",
                                applied=True,
                            )
                        )
                        continue
                    except ValueError:
                        pass

            new_weight = 0.0
            if new_weight < current_weight:
                results.append(
                    _make_result(
                        platform, RULE_CANARY_DRIFT,
                        old_weight=current_weight, new_weight=new_weight,
                        multiplier=multiplier,
                        reason=f"drift_count={drift_count} >= max_strikes={max_strikes} — suppress to 0",
                        applied=True, intentional_zero=True,
                    )
                )
        elif drift_count > 0:
            # Drift exists but below threshold — leave weight unchanged
            results.append(
                _make_result(
                    platform, RULE_CANARY_DRIFT,
                    old_weight=current_weight, new_weight=current_weight,
                    multiplier=1.0,
                    reason=f"drift_count={drift_count} < max_strikes={max_strikes} — no change",
                    applied=False,
                )
            )

    return results


# ---------------------------------------------------------------------------
# Rule 2: Recheck Survival → Boost
# ---------------------------------------------------------------------------


def _rule_recheck_survival(
    state_data: dict[str, Any],
    config: dict[str, Any],
) -> list[RuleResult]:
    """Boost weight for platforms with strong survival + dofollow rates."""
    multiplier = float(config.get("multiplier", 1.2))
    max_cap = float(config.get("max_cap", 3.0))
    min_confirmations = int(config.get("min_confirmations", 2))
    survival_threshold = 0.5
    dofollow_threshold = 0.5

    weights = state_data.get("weights", {})
    stats = state_data.get("stats", {})
    results: list[RuleResult] = []

    for platform, platform_stats in stats.items():
        total = int(platform_stats.get("total_published", 0))
        alive = int(platform_stats.get("alive_count", 0))
        dofollow = int(platform_stats.get("dofollow_count", 0))

        if total < min_confirmations:
            continue  # Not enough data

        survival_rate = alive / total
        dofollow_rate = dofollow / alive if alive > 0 else 0.0

        if survival_rate >= survival_threshold and dofollow_rate >= dofollow_threshold:
            current_weight = _get_current_weight(weights, platform)
            new_weight = min(current_weight * multiplier, max_cap)
            if new_weight > current_weight:
                results.append(
                    _make_result(
                        platform, RULE_RECHECK_SURVIVAL,
                        old_weight=current_weight, new_weight=new_weight,
                        multiplier=multiplier,
                        reason=f"survival={survival_rate:.0%} >=50% dofollow={dofollow_rate:.0%} >=50% — boost",
                        applied=True,
                    )
                )
            else:
                results.append(
                    _make_result(
                        platform, RULE_RECHECK_SURVIVAL,
                        old_weight=current_weight, new_weight=current_weight,
                        multiplier=1.0,
                        reason=f"already at or above cap={max_cap} — no change",
                        applied=False,
                    )
                )
        else:
            current_weight = _get_current_weight(weights, platform)
            results.append(
                _make_result(
                    platform, RULE_RECHECK_SURVIVAL,
                    old_weight=current_weight, new_weight=current_weight,
                    multiplier=1.0,
                    reason=f"survival={survival_rate:.0%} or dofollow={dofollow_rate:.0%} below threshold — no change",
                    applied=False,
                )
            )

    return results


# ---------------------------------------------------------------------------
# Rule 3: Aggregated Stats → Low-Survival Penalty
# ---------------------------------------------------------------------------


def _rule_aggregated_stats(
    state_data: dict[str, Any],
    config: dict[str, Any],
) -> list[RuleResult]:
    """Reduce weight for platforms with persistently poor survival/dofollow.

    Fires when the platform's accumulated data (across all recheck cycles)
    falls below a hard floor:
      - survival_rate < survival_low_threshold (default 0.3)
      - dofollow_rate < dofollow_low_threshold (default 0.2)

    Each condition that triggers reduces weight by *multiplier* (default 0.5).
    Both can fire simultaneously (weight *= 0.5 * 0.5).
    """
    multiplier = float(config.get("multiplier", 0.5))
    survival_floor = float(config.get("survival_low_threshold", 0.3))
    dofollow_floor = float(config.get("dofollow_low_threshold", 0.2))
    min_confirmations = int(config.get("min_confirmations", 2))
    min_weight = float(config.get("min_weight", 0.1))

    weights = state_data.get("weights", {})
    stats = state_data.get("stats", {})
    results: list[RuleResult] = []

    for platform, platform_stats in stats.items():
        total = int(platform_stats.get("total_published", 0))
        alive = int(platform_stats.get("alive_count", 0))
        dofollow = int(platform_stats.get("dofollow_count", 0))

        if total < min_confirmations:
            continue

        survival_rate = alive / total
        dofollow_rate = dofollow / alive if alive > 0 else 0.0

        current_weight = _get_current_weight(weights, platform)
        new_weight = current_weight
        triggers: list[str] = []

        if survival_rate < survival_floor:
            new_weight *= multiplier
            triggers.append(f"survival={survival_rate:.0%}<{survival_floor:.0%}")

        if dofollow_rate < dofollow_floor:
            new_weight *= multiplier
            triggers.append(f"dofollow={dofollow_rate:.0%}<{dofollow_floor:.0%}")

        new_weight = max(new_weight, min_weight)

        if not triggers:
            results.append(_make_result(
                platform, RULE_AGGREGATED_STATS,
                old_weight=current_weight, new_weight=current_weight,
                multiplier=1.0,
                reason=f"survival={survival_rate:.0%} dofollow={dofollow_rate:.0%} — above floor",
                applied=False,
            ))
        elif new_weight != current_weight:
            results.append(_make_result(
                platform, RULE_AGGREGATED_STATS,
                old_weight=current_weight, new_weight=new_weight,
                multiplier=multiplier,
                reason=f"{' & '.join(triggers)} — reduce (floor={min_weight})",
                applied=True,
            ))
        else:
            results.append(_make_result(
                platform, RULE_AGGREGATED_STATS,
                old_weight=current_weight, new_weight=current_weight,
                multiplier=1.0,
                reason=f"already at min_weight={min_weight} — no change",
                applied=False,
            ))

    return results


# ---------------------------------------------------------------------------
# Rule 4: Survival Threshold → Tiered Scaling
# ---------------------------------------------------------------------------


def _rule_survival_threshold(
    state_data: dict[str, Any],
    config: dict[str, Any],
) -> list[RuleResult]:
    """Scale weight by accumulated survival/dofollow stats.

    Conditions (``total_published >= min_samples``, default 5):

    Penalty:
      - ``survival_rate < 30%``  → weight *= 0.3
      - ``dofollow_rate < 20%``  → weight *= 0.4

    Boost (mutually exclusive with penalty):
      - ``survival_rate > 80%`` AND ``dofollow_rate > 80%`` → weight *= 1.15 (cap 3.0)
    """
    min_samples = int(config.get("min_samples", 5))
    survival_penalty = float(config.get("survival_penalty", 0.3))
    dofollow_penalty = float(config.get("dofollow_penalty", 0.4))
    boost_multiplier = float(config.get("boost_multiplier", 1.15))
    max_cap = float(config.get("max_cap", 3.0))
    survival_high = float(config.get("survival_high", 0.8))
    dofollow_high = float(config.get("dofollow_high", 0.8))
    min_weight = float(config.get("min_weight", 0.01))

    weights = state_data.get("weights", {})
    stats = state_data.get("stats", {})
    results: list[RuleResult] = []

    for platform, platform_stats in stats.items():
        total = int(platform_stats.get("total_published", 0))
        alive = int(platform_stats.get("alive_count", 0))
        dofollow = int(platform_stats.get("dofollow_count", 0))

        if total < min_samples:
            continue

        survival_rate = alive / total
        dofollow_rate = dofollow / alive if alive > 0 else 0.0

        current_weight = _get_current_weight(weights, platform)
        new_weight = current_weight
        triggers: list[str] = []

        if survival_rate < 0.3:
            new_weight *= survival_penalty
            triggers.append(f"survival={survival_rate:.0%}<30%")

        if dofollow_rate < 0.2:
            new_weight *= dofollow_penalty
            triggers.append(f"dofollow={dofollow_rate:.0%}<20%")

        if not triggers:
            if survival_rate > survival_high and dofollow_rate > dofollow_high:
                new_weight = min(current_weight * boost_multiplier, max_cap)
                if new_weight > current_weight:
                    results.append(_make_result(
                        platform, RULE_SURVIVAL_THRESHOLD,
                        old_weight=current_weight, new_weight=new_weight,
                        multiplier=boost_multiplier,
                        reason=f"survival={survival_rate:.0%}>80% dofollow={dofollow_rate:.0%}>80% — boost",
                        applied=True,
                    ))
                else:
                    results.append(_make_result(
                        platform, RULE_SURVIVAL_THRESHOLD,
                        old_weight=current_weight, new_weight=current_weight,
                        multiplier=1.0,
                        reason=f"already at cap={max_cap} — no change",
                        applied=False,
                    ))
            else:
                results.append(_make_result(
                    platform, RULE_SURVIVAL_THRESHOLD,
                    old_weight=current_weight, new_weight=current_weight,
                    multiplier=1.0,
                    reason=f"survival={survival_rate:.0%} dofollow={dofollow_rate:.0%} — above penalty thresholds but below boost",
                    applied=False,
                ))
        else:
            new_weight = max(new_weight, min_weight)
            if new_weight != current_weight:
                results.append(_make_result(
                    platform, RULE_SURVIVAL_THRESHOLD,
                    old_weight=current_weight, new_weight=new_weight,
                    multiplier=survival_penalty if "survival" in triggers[0] else dofollow_penalty,
                    reason=" & ".join(triggers) + f" — reduce (floor={min_weight})",
                    applied=True,
                ))
            else:
                results.append(_make_result(
                    platform, RULE_SURVIVAL_THRESHOLD,
                    old_weight=current_weight, new_weight=current_weight,
                    multiplier=1.0,
                    reason=f"already at min_weight={min_weight} — no change",
                    applied=False,
                ))

    return results


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_RULE_REGISTRY: dict[str, Any] = {
    RULE_CANARY_DRIFT: _rule_canary_drift,
    RULE_RECHECK_SURVIVAL: _rule_recheck_survival,
    RULE_AGGREGATED_STATS: _rule_aggregated_stats,
    RULE_SURVIVAL_THRESHOLD: _rule_survival_threshold,
}


def _get_current_weight(weights: dict[str, Any], platform: str) -> float:
    entry = weights.get(platform, {})
    return float(entry.get("current", 1.0))


def _get_base_weight(weights: dict[str, Any], platform: str, default: float) -> float:
    entry = weights.get(platform, {})
    return float(entry.get("base", default))


def _make_result(
    platform: str,
    rule_name: str,
    old_weight: float,
    new_weight: float,
    multiplier: float,
    reason: str,
    applied: bool,
    intentional_zero: bool = False,
) -> RuleResult:
    return RuleResult(
        platform=platform,
        rule_name=rule_name,
        old_weight=old_weight,
        new_weight=new_weight,
        multiplier=multiplier,
        reason=reason,
        applied=applied,
        intentional_zero=intentional_zero,
    )


def apply_results(state: Any, results: list[RuleResult]) -> int:
    """Write applicable ``RuleResult`` s to the provided *state* object.

    Only results where ``applied=True`` are persisted. Returns the count of
    applied results.
    """
    count = 0
    for r in results:
        if not r.applied:
            continue
        state.set_weight(
            r.platform,
            r.new_weight,
            rule=r.rule_name,
            reason=r.reason,
            intentional_zero=r.intentional_zero,
        )
        count += 1
    return count
