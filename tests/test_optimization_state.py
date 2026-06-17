"""Tests for backlink_publisher.optimization.state.OptimizationState."""

from __future__ import annotations

__tier__ = "integration"


import json
import os
import tempfile
from pathlib import Path

import pytest

from backlink_publisher.optimization import OptimizationState
from backlink_publisher.optimization.models import default_state


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_state() -> OptimizationState:
    """Return an OptimizationState pointed at a temp directory."""
    tmp = Path(tempfile.mkdtemp())
    return OptimizationState(data_dir=str(tmp))


# ---------------------------------------------------------------------------
# Load / Save
# ---------------------------------------------------------------------------


class TestLoad:
    def test_load_non_existent_file_returns_default(self, tmp_state):
        """Loading when no file exists returns default state, not error."""
        assert not tmp_state.path.exists()
        data = tmp_state.load()
        assert data["version"] == 2
        assert data["weights"] == {"default": {}}
        assert data["stats"] == {"default": {}}

    def test_save_then_load_roundtrip(self, tmp_state):
        """Save then load returns identical data."""
        original = default_state()
        original["weights"]["test_plat"] = {
            "base": 1.0,
            "current": 0.5,
            "updated_at": "2026-06-05T00:00:00Z",
            "adjustments": [],
        }
        tmp_state.save(original)
        loaded = tmp_state.load()
        assert loaded["version"] == original["version"]
        assert loaded["weights"]["test_plat"]["current"] == 0.5

    def test_corrupt_file_returns_default_with_warning(self, tmp_state):
        """Corrupt JSON loads as default state (graceful fallback)."""
        tmp_state.path.write_text("not-json{{{")
        data = tmp_state.load()
        assert data["version"] == 2
        assert data["weights"] == {"default": {}}

    def test_missing_version_key_treated_as_corrupt(self, tmp_state):
        """Missing 'version' key triggers fallback to defaults."""
        tmp_state.path.write_text(json.dumps({"weights": {}}))
        data = tmp_state.load()
        assert data["version"] == 2


# ---------------------------------------------------------------------------
# Get / Set weight
# ---------------------------------------------------------------------------


class TestGetSetWeight:
    def test_get_weight_returns_default_when_no_entry(self, tmp_state):
        assert tmp_state.get_weight("unknown", default=0.8) == 0.8

    def test_get_weight_returns_default_for_missing_file(self, tmp_state):
        assert not tmp_state.path.exists()
        assert tmp_state.get_weight("anything", default=1.0) == 1.0

    def test_set_weight_creates_entry_when_missing(self, tmp_state):
        tmp_state.set_weight("blogger", 0.5, rule="canary_drift",
                              reason="forward_path_drift")
        w = tmp_state.get_weight("blogger", default=1.0)
        assert w == 0.5

    def test_set_weight_appends_adjustment(self, tmp_state):
        tmp_state.set_weight("blogger", 0.5, rule="canary_drift",
                              reason="first_drift")
        data = tmp_state.load()
        adj = data["weights"]["default"]["blogger"]["adjustments"]
        assert len(adj) == 1
        assert adj[0]["rule"] == "canary_drift"

        tmp_state.set_weight("blogger", 0.25, rule="canary_drift",
                              reason="second_drift")
        data = tmp_state.load()
        adj = data["weights"]["default"]["blogger"]["adjustments"]
        assert len(adj) == 2
        assert adj[1]["multiplier"] == 0.5  # 0.25/0.5

    def test_get_weight_returns_current_after_set(self, tmp_state):
        tmp_state.set_weight("medium", 1.2, rule="recheck_survival",
                              reason="alive_2x")
        assert tmp_state.get_weight("medium", default=1.0) == 1.2


# ---------------------------------------------------------------------------
# Update stats
# ---------------------------------------------------------------------------


class TestUpdateStats:
    def test_update_stats_creates_entry(self, tmp_state):
        tmp_state.update_stats("blogger", {"total_published": 10, "alive_count": 8})
        data = tmp_state.load()
        assert data["stats"]["default"]["blogger"]["total_published"] == 10
        assert data["stats"]["default"]["blogger"]["alive_count"] == 8

    def test_update_stats_merges_without_overwrite(self, tmp_state):
        tmp_state.update_stats("blogger", {"total_published": 10})
        tmp_state.update_stats("blogger", {"alive_count": 8})
        data = tmp_state.load()
        assert data["stats"]["default"]["blogger"]["total_published"] == 10
        assert data["stats"]["default"]["blogger"]["alive_count"] == 8

    def test_update_stats_separate_platforms(self, tmp_state):
        tmp_state.update_stats("blogger", {"total_published": 5})
        tmp_state.update_stats("medium", {"total_published": 3})
        data = tmp_state.load()
        assert data["stats"]["default"]["blogger"]["total_published"] == 5
        assert data["stats"]["default"]["medium"]["total_published"] == 3


# ---------------------------------------------------------------------------
# Rules config
# ---------------------------------------------------------------------------


class TestRulesConfig:
    def test_get_rules_config_returns_defaults_without_state(self, tmp_state):
        """Without a state file, get_rules_config returns default rule config."""
        assert not tmp_state.path.exists()
        rc = tmp_state.get_rules_config()
        assert "canary_drift" in rc
        assert rc["canary_drift"]["enabled"] is True
        assert rc["canary_drift"]["multiplier"] == 0.5

    def test_get_rules_config_after_default_save(self, tmp_state):
        tmp_state.save(default_state())
        rc = tmp_state.get_rules_config()
        assert "canary_drift" in rc
        assert "recheck_survival" in rc


# ---------------------------------------------------------------------------
# Reset & Summary
# ---------------------------------------------------------------------------


class TestResetAndSummary:
    def test_reset_clears_weights_preserves_stats(self, tmp_state):
        tmp_state.set_weight("blogger", 0.5, rule="canary_drift", reason="drift")
        tmp_state.update_stats("blogger", {"total_published": 10})
        tmp_state.reset_weights()
        data = tmp_state.load()
        assert data["weights"] == {}
        assert data["stats"]["default"]["blogger"]["total_published"] == 10

    def test_to_summary_empty(self, tmp_state):
        summary = tmp_state.to_summary()
        assert summary["platforms"] == []
        assert summary["last_updated"] is None

    def test_to_summary_with_data(self, tmp_state):
        tmp_state.set_weight("blogger", 0.5, rule="canary_drift",
                              reason="drift")
        tmp_state.update_stats("blogger", {"total_published": 12, "alive_count": 8})
        summary = tmp_state.to_summary()
        assert len(summary["platforms"]) == 1
        p = summary["platforms"][0]
        assert p["name"] == "blogger"
        assert p["base"] == 1.0
        assert p["current"] == 0.5
        assert p["delta_pct"] == -50.0
        assert p["adjustment_count"] == 1
        assert p["stats"]["total_published"] == 12
        assert p["stats"]["alive_count"] == 8


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


class TestPersistence:
    def test_survives_process_restart(self, tmp_state):
        """State persists on disk and can be read by a new instance."""
        tmp_state.set_weight("blogger", 0.5, rule="canary_drift",
                              reason="drift")
        path = tmp_state.path

        # Simulate a new instance reading the same file
        state2 = OptimizationState(data_dir=str(path.parent))
        w = state2.get_weight("blogger", default=1.0)
        assert w == 0.5

    def test_custom_data_dir(self):
        """Custom data_dir is respected."""
        tmp = Path(tempfile.mkdtemp())
        state = OptimizationState(data_dir=str(tmp))
        assert str(tmp) in str(state.path)
        assert state.path.name == "optimization_state.json"
