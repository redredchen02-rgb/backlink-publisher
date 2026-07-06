"""End-to-end integration tests for the continuous optimisation subsystem (U7).

Verifies the full pipeline end-to-end:
  1. collect-signals → writes stats to optimization_state.json
  2. optimize-weights → evaluates rules, adjusts dispatch weights
  3. dispatch_weight() → reads dynamic overrides
  4. show-optimization-state → displays results
  5. WebUI /optimization-status → renders page
"""

from __future__ import annotations

__tier__ = "integration"


import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

import pytest

from backlink_publisher.optimization import OptimizationState
from backlink_publisher.optimization.rules import (
    apply_results,
    evaluate_rules,
    RULE_AGGREGATED_STATS,
    RULE_CANARY_DRIFT,
)
from backlink_publisher.publishing import registry

# ---------------------------------------------------------------------------
# Integration: state → rules → weight override
# ---------------------------------------------------------------------------


class TestStateToRulesToWeight:
    """Ground-truth E2E: set up stats, run rules, verify dispatch_weight changes."""

    def test_full_cycle_drift_penalty(self, tmp_path: Path, monkeypatch):
        """Simulate: canary detects drift → canary_drift rule reduces weight →
        dispatch_weight reflects the reduction."""
        monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
        state = OptimizationState()

        # Step 1: collect-signals equivalent — write stats
        state.update_stats("blogger", {
            "drift_count": 5, "total_published": 10, "alive_count": 8, "dofollow_count": 6,
        })
        state.update_stats("velog", {
            "drift_count": 0, "total_published": 5, "alive_count": 5, "dofollow_count": 5,
        })

        # Step 2: run only the canary_drift rule
        data = state.load()
        results = evaluate_rules(data, rule_filter=RULE_CANARY_DRIFT)
        apply_results(state, results)

        # Step 3: verify weight changed
        blog_w = state.get_weight("blogger", default=1.0)
        velog_w = state.get_weight("velog", default=1.0)
        assert blog_w < 1.0, f"blogger weight should be reduced (got {blog_w})"
        assert velog_w == pytest.approx(1.0), "velog weight should stay at base"

        # Step 4: registry dispatch_weight reads the dynamic value
        blog_dw = registry.dispatch_weight("blogger")
        velog_dw = registry.dispatch_weight("velog")
        assert blog_dw == pytest.approx(blog_w)
        assert velog_dw == pytest.approx(1.0)

    def test_full_cycle_survival_boost(self, tmp_path: Path, monkeypatch):
        """Simulate: recheck confirms strong survival → weight boosted."""
        monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
        state = OptimizationState()

        state.update_stats("telegraph", {
            "drift_count": 0, "total_published": 20, "alive_count": 19, "dofollow_count": 18,
        })

        data = state.load()
        results = evaluate_rules(data)
        apply_results(state, results)

        telegraph_w = state.get_weight("telegraph", default=1.0)
        assert telegraph_w > 1.0, f"telegraph weight should be boosted (got {telegraph_w})"

    def test_cycle_drift_then_clear(self, tmp_path: Path, monkeypatch):
        """Drift triggers penalty → drift clears → weight restored.
        Survival kept low so recheck_survival doesn't interfere."""
        monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
        state = OptimizationState()

        state.update_stats("medium", {
            "drift_count": 4, "total_published": 10, "alive_count": 3, "dofollow_count": 2,
        })
        data = state.load()
        results = evaluate_rules(data)
        apply_results(state, results)
        w1 = state.get_weight("medium", default=1.0)
        assert w1 < 1.0, f"should be penalised (got {w1})"

        # Phase 2: drift cleared — survival still low so only canary resets
        state.update_stats("medium", {
            "drift_count": 0, "total_published": 10, "alive_count": 3, "dofollow_count": 2,
        })
        data = state.load()
        results = evaluate_rules(data)
        apply_results(state, results)
        w2 = state.get_weight("medium", default=1.0)
        assert w2 == pytest.approx(1.0), f"should be restored (got {w2})"

    def test_aggregated_stats_penalty(self, tmp_path: Path, monkeypatch):
        """Rule 3: poor aggregated stats → weight reduced."""
        monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
        state = OptimizationState()

        state.update_stats("blogger", {
            "total_published": 20, "alive_count": 4, "dofollow_count": 1,
        })

        data = state.load()
        results = evaluate_rules(data, rule_filter=RULE_AGGREGATED_STATS)
        apply_results(state, results)

        w = state.get_weight("blogger", default=1.0)
        assert w < 1.0, f"aggregated_stats should reduce weight (got {w})"

        # dispatch_weight reflects the override
        dw = registry.dispatch_weight("blogger")
        assert dw == pytest.approx(w)


# ---------------------------------------------------------------------------
# Regression lock — v2 language-namespace schema (Phase 0 U1, guards PR #24)
# ---------------------------------------------------------------------------


class TestV2NamespaceRegressionLock:
    """Positive characterization lock for the PR #24 bug class.

    PR #24: ``evaluate_rules`` dispatched each rule with the raw, un-resolved
    ``state_data`` instead of the namespace-flattened ``resolved_state_data``.
    With the v2 schema (``stats``/``weights`` nested under the ``"default"``
    language key), the rules iterated the literal key ``"default"`` as if it
    were a platform, matched nothing, and every weight silently stayed 1.0 —
    while shape-only tests stayed green.

    These tests assert the POSITIVE outcome on a real v2-nested state: rules
    actually fire and adjust weight. If a future change re-dispatches the raw
    state_data (or otherwise breaks the namespace unwrap), ``evaluate_rules``
    returns an empty list and these tests go red — by design.
    """

    def test_v2_state_is_namespace_nested(self, tmp_path: Path, monkeypatch):
        """Document the schema the engine must consume: weights/stats nested
        under the 'default' language key (not flat {platform: ...})."""
        monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
        state = OptimizationState()
        state.update_stats("blogger", {
            "drift_count": 5, "total_published": 10, "alive_count": 8, "dofollow_count": 6,
        })
        data = state.load()
        assert data.get("version") == 2
        assert "default" in data["stats"], "v2 stats must be nested under 'default'"
        assert "blogger" in data["stats"]["default"]

    def test_canary_drift_fires_on_v2_nested_state(self, tmp_path: Path, monkeypatch):
        """#24 regression lock: rules must fire (non-empty results with a real
        weight reduction) when fed a v2-nested state. Empty results here == the
        engine is iterating the 'default' key as a platform again (#24)."""
        monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
        state = OptimizationState()
        state.update_stats("blogger", {
            "drift_count": 5, "total_published": 10, "alive_count": 8, "dofollow_count": 6,
        })
        data = state.load()

        # Assert on evaluate_rules' RuleResult objects directly (apply_results
        # returns only an int count, not the results).
        results = evaluate_rules(data, rule_filter=RULE_CANARY_DRIFT)
        assert results, "evaluate_rules returned no results on v2 state — PR #24 regression"
        applied = [r for r in results if r.applied]
        assert applied, "no rule applied a weight change on v2 state — PR #24 regression"
        assert applied[0].platform == "blogger"
        assert applied[0].new_weight < applied[0].old_weight, (
            f"weight not reduced (new={applied[0].new_weight}, old={applied[0].old_weight})"
        )

        # And the applied result reaches the persisted state (output seam).
        count = apply_results(state, results)
        assert count >= 1
        assert state.get_weight("blogger", default=1.0) < 1.0

    def test_no_phantom_default_platform(self, tmp_path: Path, monkeypatch):
        """The literal language key 'default' must never surface as a platform
        in results — that was the visible symptom of #24."""
        monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
        state = OptimizationState()
        state.update_stats("blogger", {
            "drift_count": 5, "total_published": 10, "alive_count": 8, "dofollow_count": 6,
        })
        data = state.load()
        results = evaluate_rules(data)
        assert all(r.platform != "default" for r in results), (
            "'default' language key leaked as a platform — PR #24 regression"
        )


# ---------------------------------------------------------------------------
# Integration: CLI pipeline (subprocess)
# ---------------------------------------------------------------------------


class TestCLIPipeline:
    """Run actual CLI commands as a subprocess pipeline."""

    def test_collect_then_show(self, tmp_path: Path, monkeypatch):
        """collect-signals (dry-run) followed by show-optimization-state.
        Verifies no crash between commands."""
        monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))

        r1 = subprocess.run(
            [sys.executable, "-m", "backlink_publisher.cli.collect_signals", "--dry-run"],
            capture_output=True, text=True, timeout=30,
        )
        assert r1.returncode == 0

        r2 = subprocess.run(
            [sys.executable, "-m", "backlink_publisher.cli.show_optimization_state"],
            capture_output=True, text=True, timeout=30,
        )
        assert r2.returncode == 0

    def test_optimize_weights_no_crash(self, tmp_path: Path, monkeypatch):
        """optimize-weights --dry-run should not crash even with no data."""
        monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))

        r = subprocess.run(
            [sys.executable, "-m", "backlink_publisher.cli.optimize_weights", "--dry-run"],
            capture_output=True, text=True, timeout=30,
        )
        assert r.returncode == 0

    def test_pipeline_then_webui_render(self, tmp_path: Path, monkeypatch):
        """Set up state, then verify WebUI route renders it."""
        monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
        state = OptimizationState()
        state.set_weight("blogger", 0.5, rule=RULE_CANARY_DRIFT, reason="e2e test")
        state.update_stats("blogger", {"alive_count": 5, "total_published": 10})

        import webui
        webui.app.config["TESTING"] = True
        webui.app.config["WTF_CSRF_ENABLED"] = False
        client = webui.app.test_client()
        resp = client.get("/optimization-status/jinja")
        assert resp.status_code == 200
        body = resp.data.decode("utf-8")
        assert "blogger" in body
        assert "Optimization Status" in body
