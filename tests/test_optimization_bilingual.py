"""Tests for bilingual weight separation (v1→v2 upgrade + language spaces)."""


__tier__ = "unit"
from __future__ import annotations

import json
from pathlib import Path
import tempfile

import pytest

from backlink_publisher.optimization import OptimizationState
from backlink_publisher.optimization.models import default_state
from backlink_publisher.publishing import registry

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_state() -> OptimizationState:
    """Return an OptimizationState pointed at a temp directory."""
    tmp = Path(tempfile.mkdtemp())
    return OptimizationState(data_dir=str(tmp))


@pytest.fixture
def v1_state_json(tmp_path: Path) -> Path:
    """Write a version 1 (flat) state file and return its path."""
    data = {
        "version": 1,
        "weights": {
            "blogger": {
                "base": 1.0,
                "current": 0.5,
                "locked": False,
                "updated_at": "2026-06-10T00:00:00Z",
                "adjustments": [
                    {"rule": "canary_drift", "multiplier": 0.5, "reason": "drift test"},
                ],
            },
            "medium": {
                "base": 1.0,
                "current": 1.2,
                "locked": False,
                "updated_at": "2026-06-10T00:00:00Z",
                "adjustments": [],
            },
        },
        "stats": {
            "blogger": {"total_published": 10, "alive_count": 8, "dofollow_count": 7},
            "medium": {"total_published": 5, "alive_count": 1, "dofollow_count": 0},
        },
    }
    p = tmp_path / "optimization_state.json"
    p.write_text(json.dumps(data))
    return p


# ---------------------------------------------------------------------------
# V1 → V2 upgrade
# ---------------------------------------------------------------------------


class TestV1ToV2Upgrade:
    def test_v1_json_auto_upgraded_on_load(self, v1_state_json: Path, monkeypatch):
        """version 1 flat schema loads and auto-upgrades to version 2."""
        monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(v1_state_json.parent))
        state = OptimizationState()
        data = state.load()
        assert data["version"] == 2
        # weights should now be nested under "default"
        assert "default" in data["weights"]
        assert "blogger" in data["weights"]["default"]
        assert data["weights"]["default"]["blogger"]["current"] == 0.5
        assert "medium" in data["weights"]["default"]
        # stats too
        assert "default" in data["stats"]
        assert data["stats"]["default"]["blogger"]["alive_count"] == 8

    def test_v1_json_data_preserved_after_upgrade(self, v1_state_json: Path, monkeypatch):
        """All original weight/stats values survive the version 1→2 upgrade."""
        monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(v1_state_json.parent))
        state = OptimizationState()
        data = state.load()
        assert data["version"] == 2
        # Check adjustments survived
        adj = data["weights"]["default"]["blogger"]["adjustments"]
        assert len(adj) == 1
        assert adj[0]["rule"] == "canary_drift"
        # Check stats survived
        assert data["stats"]["default"]["medium"]["total_published"] == 5

    def test_v1_json_get_weight_backward_compat(self, v1_state_json: Path, monkeypatch):
        """get_weight() reads v1 data correctly after auto-upgrade (default language)."""
        monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(v1_state_json.parent))
        state = OptimizationState()
        # Force load+upgrade by touching state
        _ = state.load()
        w = state.get_weight("blogger", default=1.0)
        assert w == 0.5
        w2 = state.get_weight("medium", default=1.0)
        assert w2 == 1.2
        w3 = state.get_weight("unknown", default=0.8)
        assert w3 == 0.8

    def test_v1_json_save_writes_v2_format(self, v1_state_json: Path, monkeypatch):
        """After loading a v1 file, save() writes version 2 schema."""
        monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(v1_state_json.parent))
        state = OptimizationState()
        _ = state.load()
        # Now set a weight — this triggers save internally
        state.set_weight("telegraph", 0.3, rule="manual", reason="test")
        # Re-read from disk
        raw = json.loads(state.path.read_text())
        assert raw["version"] == 2
        assert "default" in raw["weights"]
        assert raw["weights"]["default"]["telegraph"]["current"] == 0.3
        # Original data should also be in default
        assert raw["weights"]["default"]["blogger"]["current"] == 0.5


# ---------------------------------------------------------------------------
# Language-specific weights
# ---------------------------------------------------------------------------


class TestLanguageSpecificWeights:
    def test_language_specific_weight(self, tmp_state):
        """zh-CN and en can have different weights for the same platform."""
        tmp_state.set_weight("blogger", 0.5, rule="canary_drift",
                             reason="cn_drift", language="zh-CN")
        tmp_state.set_weight("blogger", 1.2, rule="recheck_survival",
                             reason="en_good", language="en")

        w_cn = tmp_state.get_weight("blogger", language="zh-CN")
        w_en = tmp_state.get_weight("blogger", language="en")
        assert w_cn == 0.5
        assert w_en == 1.2
        assert w_cn != w_en

    def test_language_isolated_stats(self, tmp_state):
        """Stats for different languages are isolated."""
        tmp_state.update_stats("blogger", {"alive_count": 8}, language="zh-CN")
        tmp_state.update_stats("blogger", {"alive_count": 3}, language="en")

        data = tmp_state.load()
        assert data["stats"]["zh-CN"]["blogger"]["alive_count"] == 8
        assert data["stats"]["en"]["blogger"]["alive_count"] == 3

    def test_lock_weight_language_scoped(self, tmp_state):
        """Locking a weight in one language does not affect another."""
        tmp_state.set_weight("blogger", 0.0, rule="manual",
                             reason="test", language="zh-CN")
        tmp_state.set_weight("blogger", 0.8, rule="manual",
                             reason="test", language="en")
        tmp_state.lock_weight("blogger", True, language="zh-CN")

        data = tmp_state.load()
        # zh-CN entry should be locked
        assert data["weights"]["zh-CN"]["blogger"]["locked"] is True
        # en entry should NOT be locked
        assert data["weights"]["en"]["blogger"].get("locked", False) is False


# ---------------------------------------------------------------------------
# Language fallback to default
# ---------------------------------------------------------------------------


class TestLanguageFallback:
    def test_language_fallback_default(self, tmp_state):
        """When the requested language has no data, fall back to 'default'."""
        tmp_state.set_weight("blogger", 0.7, rule="manual",
                             reason="set_in_default", language="default")

        w = tmp_state.get_weight("blogger", language="zh-CN")
        assert w == 0.7, "should fall back to default language"

    def test_fallback_does_not_apply_when_language_has_data(self, tmp_state):
        """When requested language has its own data, fallback is NOT used."""
        tmp_state.set_weight("blogger", 0.5, rule="manual",
                             reason="cn", language="zh-CN")
        tmp_state.set_weight("blogger", 0.9, rule="manual",
                             reason="default", language="default")

        w = tmp_state.get_weight("blogger", language="zh-CN")
        assert w == 0.5  # zh-CN specific data, not default

    def test_get_weight_with_language_no_data_no_default_fallback(self, tmp_state):
        """When neither the language nor 'default' has data, returns the default value."""
        w = tmp_state.get_weight("unknown_plat", default=0.5, language="zh-CN")
        assert w == 0.5


# ---------------------------------------------------------------------------
# Legacy backward compat (existing callers without language)
# ---------------------------------------------------------------------------


class TestLegacyBackwardCompat:
    def test_legacy_read_new_file(self, tmp_state):
        """A caller without language= keyword can still read from 'default' space."""
        tmp_state.set_weight("blogger", 0.5, rule="manual",
                             reason="test", language="default")
        # Call without language
        w = tmp_state.get_weight("blogger", default=1.0)
        assert w == 0.5

    def test_legacy_set_weight_default_language(self, tmp_state):
        """set_weight() without language writes to 'default' (backward compat)."""
        tmp_state.set_weight("blogger", 0.3, rule="manual", reason="test")
        data = tmp_state.load()
        assert data["weights"]["default"]["blogger"]["current"] == 0.3

    def test_legacy_update_stats_default_language(self, tmp_state):
        """update_stats() without language writes to 'default' (backward compat)."""
        tmp_state.update_stats("blogger", {"alive_count": 5})
        data = tmp_state.load()
        assert data["stats"]["default"]["blogger"]["alive_count"] == 5

    def test_legacy_reset_weights_all(self, tmp_state):
        """reset_weights() without language clears ALL weights (backward compat)."""
        tmp_state.set_weight("blogger", 0.5, rule="manual", reason="test")
        tmp_state.reset_weights()
        data = tmp_state.load()
        assert data["weights"] == {}

    def test_legacy_to_summary_no_language(self, tmp_state):
        """to_summary() without language reads from 'default'."""
        tmp_state.set_weight("blogger", 0.5, rule="canary_drift",
                             reason="drift")
        tmp_state.update_stats("blogger", {"total_published": 10})
        summary = tmp_state.to_summary()
        assert len(summary["platforms"]) == 1
        assert summary["platforms"][0]["name"] == "blogger"
        assert summary["platforms"][0]["current"] == 0.5


# ---------------------------------------------------------------------------
# dispatch_weight with language
# ---------------------------------------------------------------------------


class TestDispatchWeightWithLanguage:
    def test_dispatch_weight_with_language(self, tmp_path: Path, monkeypatch):
        """dispatch_weight() reads language-specific weights."""
        monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
        state = OptimizationState()
        state.set_weight("blogger", 0.4, rule="manual",
                         reason="cn_low", language="zh-CN")
        state.set_weight("blogger", 1.3, rule="manual",
                         reason="en_high", language="en")

        w_cn = registry.dispatch_weight("blogger", language="zh-CN")
        w_en = registry.dispatch_weight("blogger", language="en")
        w_def = registry.dispatch_weight("blogger")  # default

        assert w_cn == pytest.approx(0.4)
        assert w_en == pytest.approx(1.3)
        # default falls back: zh-CN and en exist, but "default" space has no entry
        # → dispatch_weight returns static 1.0
        assert w_def == pytest.approx(1.0)

    def test_dispatch_weight_locked_zero_language_scoped(self, tmp_path: Path, monkeypatch):
        """A locked 0 in one language does not affect dispatch_weight for another."""
        monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
        state = OptimizationState()
        state.set_weight("telegraph", 0.0, rule="manual",
                         reason="off", language="zh-CN")
        state.lock_weight("telegraph", True, language="zh-CN")
        state.set_weight("telegraph", 0.8, rule="manual",
                         reason="on", language="en")

        w_cn = registry.dispatch_weight("telegraph", language="zh-CN")
        w_en = registry.dispatch_weight("telegraph", language="en")

        assert w_cn == pytest.approx(0.0), "locked 0 in zh-CN must be honoured"
        assert w_en == pytest.approx(0.8), "en weight must be unaffected"

    def test_dispatch_weight_zero_default_language_clamped(self, tmp_path: Path, monkeypatch):
        """A legacy 0 in the 'default' space is still clamped above 0."""
        monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
        state = OptimizationState()
        state.set_weight("telegraph", 0.0, rule="aggregated_stats",
                         reason="legacy zero", language="default")

        w = registry.dispatch_weight("telegraph", language="default")
        assert w > 0.0, "legacy 0 in default space must be clamped"


# ---------------------------------------------------------------------------
# CLI --lang flag
# ---------------------------------------------------------------------------


class TestCliLangFlag:
    def test_show_cli_lang_flag(self, tmp_state, monkeypatch):
        """weights show --lang works."""
        tmp_state.set_weight("blogger", 0.5, rule="manual",
                             reason="test", language="zh-CN")
        monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR",
                          str(tmp_state.path.parent))

        from backlink_publisher.cli.weights import main as weights_main
        exit_code = weights_main(["show", "--lang", "zh-CN"])
        assert exit_code == 0

    def test_show_cli_default_lang(self, tmp_state, monkeypatch):
        """weights show without --lang works (backward compat)."""
        tmp_state.set_weight("blogger", 0.5, rule="manual",
                             reason="test", language="default")
        monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR",
                          str(tmp_state.path.parent))

        from backlink_publisher.cli.weights import main as weights_main
        exit_code = weights_main(["show"])
        assert exit_code == 0

    def test_collect_cli_lang_flag(self, tmp_state, monkeypatch):
        """weights collect --lang does not crash (integration surface only)."""
        monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR",
                          str(tmp_state.path.parent))
        from backlink_publisher.cli.weights import main as weights_main
        exit_code = weights_main(["collect", "--lang", "en", "--dry-run"])
        assert exit_code == 0

    def test_optimize_cli_lang_flag(self, tmp_state, monkeypatch):
        """weights optimize --lang does not crash (integration surface only)."""
        monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR",
                          str(tmp_state.path.parent))
        from backlink_publisher.cli.weights import main as weights_main
        exit_code = weights_main(["optimize", "--lang", "zh-CN", "--dry-run"])
        assert exit_code == 0
