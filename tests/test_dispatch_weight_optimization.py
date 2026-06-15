"""Tests for ``dispatch_weight()`` dynamic override from optimisation state (U4).

Verifies that the routing reliability discount can be overridden by entries
in ``optimization_state.json``.
"""

from __future__ import annotations

__tier__ = "integration"


import os
from pathlib import Path

import pytest

from backlink_publisher.optimization import OptimizationState
from backlink_publisher.publishing import registry


# ---------------------------------------------------------------------------
# dispatch_weight — static vs dynamic
# ---------------------------------------------------------------------------


class TestDispatchWeightDynamic:
    def test_static_weight_when_no_state(self):
        """Without optimisation state, returns the registry static weight."""
        w = registry.dispatch_weight("blogger")
        # blogger has no special dispatch_weight in registry → default 1.0
        assert w == pytest.approx(1.0)

    def test_dynamic_weight_overrides_static(self, tmp_path: Path, monkeypatch):
        """When optimisation state has a dynamic weight, it takes precedence.

        Sets ``BACKLINK_PUBLISHER_CONFIG_DIR`` so that ``dispatch_weight()``
        (which creates its own ``OptimizationState`` internally) reads from
        the same temp directory.
        """
        monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
        state = OptimizationState()
        state.set_weight("telegraph", 0.3, rule="canary_drift", reason="drift test")

        w = registry.dispatch_weight("telegraph")
        assert w == pytest.approx(0.3)

    def test_unregistered_platform_returns_one(self):
        """Unregistered platforms return 1.0."""
        w = registry.dispatch_weight("nonexistent_platform")
        assert w == pytest.approx(1.0)

    def test_zero_dynamic_weight_clamped_above_zero(self, tmp_path: Path, monkeypatch):
        """A legacy 0 in state must not route-exclude a platform (belt-and-suspenders clamp)."""
        monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
        state = OptimizationState()
        state.set_weight("telegraph", 0.0, rule="aggregated_stats", reason="legacy zero")

        w = registry.dispatch_weight("telegraph")
        assert w > 0.0, "dispatch_weight must never return 0 — routing exclusion is irreversible"

    def test_locked_zero_weight_respected(self, tmp_path: Path, monkeypatch):
        """An operator's manual lock at 0 wins over the defensive floor — the
        clamp must not undo a deliberate operator weight lock."""
        monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
        state = OptimizationState()
        state.set_weight("telegraph", 0.0, rule="manual", reason="operator off")
        state.lock_weight("telegraph", True)

        w = registry.dispatch_weight("telegraph")
        assert w == pytest.approx(0.0), "locked weight must be honoured over the floor"

    def test_low_positive_weight_from_other_rule_preserved(self, tmp_path: Path, monkeypatch):
        """The floor lifts only a non-positive (legacy-zero) weight; a
        legitimately-low positive weight (e.g. canary_drift suppressing a
        low-base channel) must NOT be re-promoted back up to the floor."""
        monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
        state = OptimizationState()
        state.set_weight("telegraph", 0.05, rule="canary_drift", reason="low base suppress")

        w = registry.dispatch_weight("telegraph")
        assert w == pytest.approx(0.05), "low positive weight must be preserved, not floored"

    def test_read_time_floor_honors_tuned_min_weight(self, tmp_path: Path, monkeypatch):
        """The read-time floor uses the operator-tuned min_weight, not a hardcoded value."""
        monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
        state = OptimizationState()
        state.set_weight("telegraph", 0.0, rule="aggregated_stats", reason="legacy zero")
        data = state.load()
        data.setdefault("rules", {}).setdefault("aggregated_stats", {})["min_weight"] = 0.2
        state.save(data)

        assert registry.dispatch_weight("telegraph") == pytest.approx(0.2)
