"""Tests for Rules Engine (U3 — optimize-weights).

Covers:
  - canary_drift: drift_count >= max_strikes → weight reduced
  - canary_drift: drift_count == 0 → weight restored
  - canary_drift: drift_count below threshold → no change
  - recheck_survival: high survival+dofollow → weight boosted (capped)
  - recheck_survival: insufficient data → no change
  - recheck_survival: below thresholds → no change
  - evaluate_rules with rule_filter
  - apply_results writes to state
  - CLI --dry-run / --rule / --json
"""

from __future__ import annotations


__tier__ = "integration"
import datetime
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from backlink_publisher.optimization import OptimizationState
from backlink_publisher.optimization.models import default_state, now_iso
from backlink_publisher.optimization.rules import (
    RULE_AGGREGATED_STATS,
    RULE_CANARY_DRIFT,
    RULE_RECHECK_SURVIVAL,
    RULE_SURVIVAL_THRESHOLD,
    apply_results,
    evaluate_rules,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def state(tmp_path: Path) -> OptimizationState:
    """OptimizationState writing to a temp directory."""
    return OptimizationState(data_dir=str(tmp_path))


def _make_state_data(**overrides: dict) -> dict:
    """Return a default (v2) state dict, merging any *overrides*.

    ``stats`` and ``weights`` overrides are written as flat ``{platform: ...}``
    maps for readability; this helper wraps them into the v2 ``"default"``
    language namespace so they match what ``state.load()`` feeds the engine.
    """
    data = default_state()
    for key in ("stats", "weights"):
        if key in overrides:
            overrides[key] = {"default": overrides[key]}
    data.update(overrides)
    return data


# ---------------------------------------------------------------------------
# canary_drift rule
# ---------------------------------------------------------------------------


class TestCanaryDrift:
    def test_no_drift_no_change(self):
        data = _make_state_data(
            stats={"blogger": {"drift_count": 0, "total_published": 5, "alive_count": 4}},
        )
        results = evaluate_rules(data, rule_filter=RULE_CANARY_DRIFT)

        assert len(results) == 0

    def test_drift_below_threshold_no_change(self):
        data = _make_state_data(
            stats={"velog": {"drift_count": 1, "total_published": 3, "alive_count": 3}},
        )
        results = evaluate_rules(data, rule_filter=RULE_CANARY_DRIFT)
        assert len(results) == 1
        assert results[0].applied is False

    def test_drift_at_threshold_reduces_weight(self):
        data = _make_state_data(
            stats={"medium": {"drift_count": 3, "total_published": 5, "alive_count": 3}},
        )
        results = evaluate_rules(data, rule_filter=RULE_CANARY_DRIFT)
        assert len(results) == 1
        assert results[0].applied is True
        assert results[0].new_weight < results[0].old_weight

    def test_drift_above_threshold_reduces_weight(self):
        data = _make_state_data(
            stats={"telegraph": {"drift_count": 5, "total_published": 10, "alive_count": 8}},
        )
        results = evaluate_rules(data, rule_filter=RULE_CANARY_DRIFT)
        assert len(results) == 1
        assert results[0].applied is True
        assert results[0].new_weight < results[0].old_weight
        assert results[0].rule_name == RULE_CANARY_DRIFT

    def test_drift_cleared_restores_weight(self, state: OptimizationState):
        """State has a previously-suppressed platform; drift_count=0 restores."""
        state.set_weight("blogger", 0.5, rule=RULE_CANARY_DRIFT, reason="initial drift")
        state.update_stats("blogger", {"drift_count": 0, "total_published": 10, "alive_count": 8})

        data = state.load()
        results = evaluate_rules(data, rule_filter=RULE_CANARY_DRIFT)

        assert len(results) == 1
        assert results[0].applied is True
        assert results[0].new_weight > results[0].old_weight

    def test_multiple_platforms(self):
        data = _make_state_data(
            stats={
                "blogger": {"drift_count": 3, "total_published": 10, "alive_count": 8},
                "velog": {"drift_count": 0, "total_published": 5, "alive_count": 5},
            },
        )
        results = evaluate_rules(data, rule_filter=RULE_CANARY_DRIFT)
        # blogger drift=3 triggers; velog drift=0 with base weight → no result
        assert len(results) == 1
        assert results[0].platform == "blogger"
        assert results[0].applied is True

    def test_suppressed_in_cooldown_skips(self):
        """Already suppressed by canary and within cooldown — skip."""
        old_ts = (datetime.datetime.now() - datetime.timedelta(days=2)).isoformat()
        data = _make_state_data(
            weights={
                "blogger": {
                    "base": 1.0, "current": 0.0,
                    "updated_at": old_ts, "rule": RULE_CANARY_DRIFT,
                },
            },
            stats={"blogger": {"drift_count": 5, "total_published": 10, "alive_count": 8}},
        )
        results = evaluate_rules(data, rule_filter=RULE_CANARY_DRIFT)
        assert len(results) == 1
        assert results[0].applied is False
        assert "cooldown" in results[0].reason

    def test_cooldown_expired_recovers(self):
        """Suppressed more than cooldown_days ago — recover to base * 0.3."""
        old_ts = (datetime.datetime.now() - datetime.timedelta(days=14)).isoformat()
        data = _make_state_data(
            weights={
                "blogger": {
                    "base": 1.0, "current": 0.0,
                    "updated_at": old_ts, "rule": RULE_CANARY_DRIFT,
                },
            },
            stats={"blogger": {"drift_count": 5, "total_published": 10, "alive_count": 8}},
        )
        results = evaluate_rules(data, rule_filter=RULE_CANARY_DRIFT)
        assert len(results) == 1
        assert results[0].applied is True
        assert results[0].new_weight == pytest.approx(0.3)  # base(1.0) * 0.3


# ---------------------------------------------------------------------------
# recheck_survival rule
# ---------------------------------------------------------------------------


class TestRecheckSurvival:
    def test_insufficient_data_skipped(self):
        data = _make_state_data(
            stats={"blogger": {"total_published": 1, "alive_count": 1, "dofollow_count": 1}},
        )
        results = evaluate_rules(data, rule_filter=RULE_RECHECK_SURVIVAL)
        assert len(results) == 0  # total=1 < min_confirmations=2

    def test_high_survival_boosts_weight(self):
        data = _make_state_data(
            stats={"blogger": {"total_published": 10, "alive_count": 9, "dofollow_count": 8}},
        )
        results = evaluate_rules(data, rule_filter=RULE_RECHECK_SURVIVAL)

        assert len(results) == 1
        assert results[0].applied is True
        assert results[0].new_weight > results[0].old_weight
        assert results[0].rule_name == RULE_RECHECK_SURVIVAL

    def test_boost_capped_at_max_cap(self):
        data = _make_state_data(
            stats={"blogger": {"total_published": 50, "alive_count": 48, "dofollow_count": 45}},
            weights={"blogger": {"base": 3.0, "current": 2.8}},
        )
        results = evaluate_rules(data, rule_filter=RULE_RECHECK_SURVIVAL)
        assert len(results) == 1
        if results[0].applied:
            assert results[0].new_weight <= 3.0  # max_cap

    def test_low_dofollow_no_boost(self):
        data = _make_state_data(
            stats={"blogger": {"total_published": 10, "alive_count": 9, "dofollow_count": 2}},
        )
        results = evaluate_rules(data, rule_filter=RULE_RECHECK_SURVIVAL)
        assert len(results) == 1
        assert results[0].applied is False


# ---------------------------------------------------------------------------
# aggregated_stats rule (Rule 3)
# ---------------------------------------------------------------------------


class TestAggregatedStats:
    def test_insufficient_data_skipped(self):
        data = _make_state_data(
            stats={"blogger": {"total_published": 1, "alive_count": 1, "dofollow_count": 1}},
        )
        results = evaluate_rules(data, rule_filter=RULE_AGGREGATED_STATS)
        assert len(results) == 0  # total=1 < min_confirmations=2

    def test_high_survival_no_change(self):
        data = _make_state_data(
            stats={"blogger": {"total_published": 10, "alive_count": 8, "dofollow_count": 7}},
        )
        results = evaluate_rules(data, rule_filter=RULE_AGGREGATED_STATS)
        assert len(results) == 1
        assert results[0].applied is False  # above floor

    def test_low_survival_reduces_weight(self):
        """survival=20% < 30% floor — reduces weight."""
        data = _make_state_data(
            stats={"blogger": {"total_published": 10, "alive_count": 2, "dofollow_count": 2}},
        )
        results = evaluate_rules(data, rule_filter=RULE_AGGREGATED_STATS)
        assert len(results) == 1
        assert results[0].applied is True
        assert results[0].new_weight < results[0].old_weight
        assert results[0].rule_name == RULE_AGGREGATED_STATS

    def test_very_low_survival_reduces_weight(self):
        """survival=10% << 30% floor — reduces weight by multiplier."""
        data = _make_state_data(
            stats={"blogger": {"total_published": 10, "alive_count": 1, "dofollow_count": 1}},
        )
        results = evaluate_rules(data, rule_filter=RULE_AGGREGATED_STATS)
        assert len(results) == 1
        assert results[0].applied is True
        assert results[0].new_weight == pytest.approx(0.5)

    def test_low_dofollow_reduces_weight(self):
        """dofollow=10% < 20% floor — reduces weight."""
        data = _make_state_data(
            stats={"blogger": {"total_published": 10, "alive_count": 10, "dofollow_count": 1}},
        )
        results = evaluate_rules(data, rule_filter=RULE_AGGREGATED_STATS)
        assert len(results) == 1
        assert results[0].applied is True
        assert results[0].new_weight < results[0].old_weight

    def test_both_conditions_compound(self):
        """Both survival and dofollow below floor — weight *= 0.5 * 0.5 = 0.25."""
        data = _make_state_data(
            stats={"blogger": {"total_published": 10, "alive_count": 2, "dofollow_count": 0}},
        )
        results = evaluate_rules(data, rule_filter=RULE_AGGREGATED_STATS)
        assert len(results) == 1
        assert results[0].applied is True
        assert results[0].new_weight == pytest.approx(0.25)  # 1.0 * 0.5 * 0.5

    def test_weight_floor_prevents_routing_exclusion(self):
        """min_weight=0.1 clamp: even with terrible signals, weight stays >= min_weight."""
        data = _make_state_data(
            stats={"blogger": {"total_published": 10, "alive_count": 1, "dofollow_count": 0}},
            weights={"blogger": {"base": 0.05, "current": 0.05}},
            rules={"aggregated_stats": {"enabled": True, "min_weight": 0.1}},
        )
        results = evaluate_rules(data, rule_filter=RULE_AGGREGATED_STATS)
        assert len(results) == 1
        assert results[0].new_weight >= 0.1

    def test_min_weight_in_default_config_is_nonzero(self):
        """default_state() must include aggregated_stats with min_weight > 0."""
        from backlink_publisher.optimization.models import default_state as ds
        state = ds()
        agg = state["rules"].get("aggregated_stats", {})
        assert agg, "aggregated_stats missing from default_state — P0 safety net not seeded"
        assert agg.get("enabled") is True
        assert float(agg.get("min_weight", 0)) > 0

    def test_canary_and_aggregated_independent(self):
        """Both rules evaluate without interference."""
        data = _make_state_data(
            stats={
                "blogger": {
                    "drift_count": 3, "total_published": 10,
                    "alive_count": 2, "dofollow_count": 1,
                },
            },
        )
        results = evaluate_rules(data, rule_filter=None)
        rule_names = {r.rule_name for r in results}
        assert RULE_AGGREGATED_STATS in rule_names
        assert RULE_CANARY_DRIFT in rule_names


# ---------------------------------------------------------------------------
# survival_threshold rule (U1.3)
# ---------------------------------------------------------------------------


class TestSurvivalThreshold:
    def test_insufficient_data_skipped(self):
        data = _make_state_data(
            stats={"blogger": {"total_published": 3, "alive_count": 3, "dofollow_count": 3}},
        )
        results = evaluate_rules(data, rule_filter=RULE_SURVIVAL_THRESHOLD)
        assert len(results) == 0  # total=3 < min_samples=5

    def test_low_survival_reduces_weight(self):
        """survival=20% < 30% → weight *= 0.3."""
        data = _make_state_data(
            stats={"blogger": {"total_published": 10, "alive_count": 2, "dofollow_count": 2}},
        )
        results = evaluate_rules(data, rule_filter=RULE_SURVIVAL_THRESHOLD)
        assert len(results) == 1
        assert results[0].applied is True
        assert results[0].new_weight == pytest.approx(0.3)  # 1.0 * 0.3
        assert results[0].rule_name == RULE_SURVIVAL_THRESHOLD

    def test_low_dofollow_reduces_weight(self):
        """dofollow=10% < 20% → weight *= 0.4."""
        data = _make_state_data(
            stats={"blogger": {"total_published": 10, "alive_count": 10, "dofollow_count": 1}},
        )
        results = evaluate_rules(data, rule_filter=RULE_SURVIVAL_THRESHOLD)
        assert len(results) == 1
        assert results[0].applied is True
        assert results[0].new_weight == pytest.approx(0.4)  # 1.0 * 0.4

    def test_both_conditions_compound(self):
        """survival < 30% AND dofollow < 20% → weight *= 0.3 * 0.4 = 0.12."""
        data = _make_state_data(
            stats={"blogger": {"total_published": 10, "alive_count": 2, "dofollow_count": 0}},
        )
        results = evaluate_rules(data, rule_filter=RULE_SURVIVAL_THRESHOLD)
        assert len(results) == 1
        assert results[0].applied is True
        assert results[0].new_weight == pytest.approx(0.12)  # 1.0 * 0.3 * 0.4

    def test_high_survival_and_dofollow_boosts(self):
        """survival=90% > 80% AND dofollow=89% > 80% → weight *= 1.15."""
        data = _make_state_data(
            stats={"blogger": {"total_published": 10, "alive_count": 9, "dofollow_count": 8}},
        )
        results = evaluate_rules(data, rule_filter=RULE_SURVIVAL_THRESHOLD)
        assert len(results) == 1
        assert results[0].applied is True
        assert results[0].new_weight == pytest.approx(1.15)  # 1.0 * 1.15
        assert results[0].reason == (
            "survival=90%>80% dofollow=89%>80% — boost"
        )

    def test_boost_capped_at_max_cap(self):
        """Boost caps at max_cap=3.0."""
        data = _make_state_data(
            weights={"blogger": {"base": 3.0, "current": 2.8}},
            stats={"blogger": {"total_published": 50, "alive_count": 48, "dofollow_count": 45}},
        )
        results = evaluate_rules(data, rule_filter=RULE_SURVIVAL_THRESHOLD)
        assert len(results) == 1
        if results[0].applied:
            assert results[0].new_weight <= 3.0

    def test_mid_range_no_penalty_no_boost(self):
        """survival=50% dofollow=50% — above penalty thresholds, below boost."""
        data = _make_state_data(
            stats={"blogger": {"total_published": 10, "alive_count": 5, "dofollow_count": 5}},
        )
        results = evaluate_rules(data, rule_filter=RULE_SURVIVAL_THRESHOLD)
        assert len(results) == 1
        assert results[0].applied is False
        assert results[0].new_weight == results[0].old_weight

    def test_weight_floor_applied(self):
        """min_weight=0.01 prevents weight from reaching 0."""
        data = _make_state_data(
            stats={"blogger": {"total_published": 10, "alive_count": 1, "dofollow_count": 0}},
        )
        results = evaluate_rules(data, rule_filter=RULE_SURVIVAL_THRESHOLD)
        assert len(results) == 1
        assert results[0].new_weight >= 0.01


# ---------------------------------------------------------------------------
# evaluate_rules integration
# ---------------------------------------------------------------------------


class TestEvaluateRules:
    def test_rule_filter_none_runs_all(self):
        data = _make_state_data(
            stats={"blogger": {"drift_count": 3, "total_published": 10, "alive_count": 8}},
        )
        results = evaluate_rules(data, rule_filter=None)
        # Both rules should run
        rule_names = {r.rule_name for r in results}
        assert RULE_CANARY_DRIFT in rule_names
        assert RULE_RECHECK_SURVIVAL in rule_names

    def test_disabled_rule_skipped(self):
        data = _make_state_data(
            stats={
                "blogger": {"drift_count": 5, "total_published": 10, "alive_count": 9, "dofollow_count": 8},
            },
            rules={
                "canary_drift": {"enabled": False},
                "recheck_survival": {"enabled": True},
            },
        )
        results = evaluate_rules(data, rule_filter=None)
        rule_names = {r.rule_name for r in results}
        assert RULE_CANARY_DRIFT not in rule_names
        assert RULE_RECHECK_SURVIVAL in rule_names

    def test_empty_stats_no_results(self):
        data = _make_state_data(stats={})
        results = evaluate_rules(data, rule_filter=None)
        assert len(results) == 0


# ---------------------------------------------------------------------------
# apply_results
# ---------------------------------------------------------------------------


class TestApplyResults:
    def test_applied_results_persisted(self, state: OptimizationState):
        from backlink_publisher.optimization.rules import RuleResult

        results = [
            RuleResult(
                platform="blogger", rule_name=RULE_CANARY_DRIFT,
                old_weight=1.0, new_weight=0.5,
                multiplier=0.5, reason="drift test", applied=True,
            ),
        ]
        count = apply_results(state, results)
        assert count == 1
        assert state.get_weight("blogger", default=1.0) == 0.5

    def test_non_applied_results_skipped(self, state: OptimizationState):
        from backlink_publisher.optimization.rules import RuleResult

        results = [
            RuleResult(
                platform="blogger", rule_name=RULE_CANARY_DRIFT,
                old_weight=1.0, new_weight=0.5,
                multiplier=0.5, reason="drift test", applied=False,
            ),
        ]
        count = apply_results(state, results)
        assert count == 0
        assert state.get_weight("blogger", default=1.0) == 1.0


# ---------------------------------------------------------------------------
# CLI end-to-end
# ---------------------------------------------------------------------------


class TestOptimizeWeightsCLI:
    def test_help(self):
        result = subprocess.run(
            [sys.executable, "-m", "backlink_publisher.cli.optimize_weights", "--help"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "usage:" in result.stdout

    def test_dry_run_no_crash(self):
        result = subprocess.run(
            [sys.executable, "-m", "backlink_publisher.cli.optimize_weights", "--dry-run"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0

    def test_json_output(self):
        result = subprocess.run(
            [sys.executable, "-m", "backlink_publisher.cli.optimize_weights",
             "--dry-run", "--json"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert isinstance(data, list)

    def test_rule_filter(self):
        result = subprocess.run(
            [sys.executable, "-m", "backlink_publisher.cli.optimize_weights",
             "--dry-run", "--rule", "canary_drift"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
