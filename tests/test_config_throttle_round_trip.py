"""U3 plan 008 — [throttle.*] TOML section: load, precedence, and round-trip.

Verifies:
  - Config.platform_throttle populated from [throttle.<slug>] delay_s
  - Empty dict when no [throttle.*] sections present
  - Env var overrides TOML (precedence)
  - TOML overrides hardcoded default when env var absent
  - save_config() does NOT drop [throttle.*] (round-trip / R4)
  - InputValidationError on non-numeric delay_s
  - Unknown slug loaded without error
"""
from __future__ import annotations

__tier__ = "integration"


from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_toml(config_dir: Path, content: str) -> Path:
    cfg = config_dir / "config.toml"
    cfg.write_text(content)
    return cfg


# ---------------------------------------------------------------------------
# Parser-level tests (Config.platform_throttle field)
# ---------------------------------------------------------------------------

class TestPlatformThrottleField:
    def test_no_throttle_section_gives_empty_dict(self, tmp_path):
        from backlink_publisher.config.loader import load_config
        cfg_path = _write_toml(tmp_path, "# no throttle section\n")
        cfg = load_config(cfg_path)
        assert cfg.platform_throttle == {}

    def test_single_platform_loaded(self, tmp_path):
        from backlink_publisher.config.loader import load_config
        cfg_path = _write_toml(tmp_path, "[throttle.hackmd]\ndelay_s = 45.0\n")
        cfg = load_config(cfg_path)
        assert cfg.platform_throttle["hackmd"] == pytest.approx(45.0)

    def test_multiple_platforms_loaded(self, tmp_path):
        from backlink_publisher.config.loader import load_config
        cfg_path = _write_toml(
            tmp_path,
            "[throttle.hackmd]\ndelay_s = 45.0\n[throttle.devto]\ndelay_s = 20.0\n",
        )
        cfg = load_config(cfg_path)
        assert cfg.platform_throttle["hackmd"] == pytest.approx(45.0)
        assert cfg.platform_throttle["devto"] == pytest.approx(20.0)

    def test_subtable_without_delay_s_skipped_silently(self, tmp_path):
        from backlink_publisher.config.loader import load_config
        cfg_path = _write_toml(tmp_path, "[throttle.unknown_platform]\nsome_key = 1\n")
        cfg = load_config(cfg_path)
        assert "unknown_platform" not in cfg.platform_throttle

    def test_invalid_delay_s_raises(self, tmp_path):
        from backlink_publisher._util.errors import InputValidationError
        from backlink_publisher.config.loader import load_config
        cfg_path = _write_toml(tmp_path, '[throttle.hackmd]\ndelay_s = "not-a-number"\n')
        with pytest.raises(InputValidationError, match="delay_s"):
            load_config(cfg_path)

    def test_unknown_slug_loaded_without_error(self, tmp_path):
        from backlink_publisher.config.loader import load_config
        cfg_path = _write_toml(tmp_path, "[throttle.totally_unknown_platform]\ndelay_s = 5.0\n")
        cfg = load_config(cfg_path)
        assert cfg.platform_throttle["totally_unknown_platform"] == pytest.approx(5.0)


# ---------------------------------------------------------------------------
# Adapter getter precedence tests (hackmd as representative)
# ---------------------------------------------------------------------------

class TestAdapterGetterPrecedence:
    def test_toml_overrides_default_when_env_absent(self, tmp_path, monkeypatch):
        """TOML delay_s = 45 and no env var → getter returns 45."""
        monkeypatch.delenv("HACKMD_PUBLISH_DELAY_S", raising=False)
        monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
        _write_toml(tmp_path, "[throttle.hackmd]\ndelay_s = 45.0\n")
        from backlink_publisher.publishing.adapters.hackmd_api import _post_publish_delay_s
        assert _post_publish_delay_s() == 45

    def test_env_overrides_toml(self, tmp_path, monkeypatch):
        """Env var = 20, TOML delay_s = 45 → getter returns 20 (env wins)."""
        monkeypatch.setenv("HACKMD_PUBLISH_DELAY_S", "20")
        monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
        _write_toml(tmp_path, "[throttle.hackmd]\ndelay_s = 45.0\n")
        from backlink_publisher.publishing.adapters.hackmd_api import _post_publish_delay_s
        assert _post_publish_delay_s() == 20

    def test_default_when_neither_env_nor_toml(self, tmp_path, monkeypatch):
        """No env var, no TOML → getter returns hardcoded default (30)."""
        monkeypatch.delenv("HACKMD_PUBLISH_DELAY_S", raising=False)
        monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
        _write_toml(tmp_path, "# no throttle section\n")
        from backlink_publisher.publishing.adapters.hackmd_api import _post_publish_delay_s
        assert _post_publish_delay_s() == 30


# ---------------------------------------------------------------------------
# Round-trip (R4): save_config must not drop [throttle.*]
# ---------------------------------------------------------------------------

class TestThrottleRoundTrip:
    def test_save_config_preserves_throttle_section(self, tmp_path):
        """save_config() writing [targets.*] must not drop [throttle.hackmd]."""
        from backlink_publisher.config.loader import load_config
        from backlink_publisher.config.writer import save_config

        initial = (
            "[throttle.hackmd]\n"
            "delay_s = 45.0\n"
            "\n"
            '[targets."example.com"]\n'
            'main_url = "https://example.com/"\n'
            'list_url = "https://example.com/list/"\n'
            'branded_pool = ["example"]\n'
            'partial_pool = ["example service"]\n'
            'exact_pool = ["example thing"]\n'
        )
        cfg_path = _write_toml(tmp_path, initial)

        cfg = load_config(cfg_path)
        save_config(cfg, cfg_path, target_three_url=cfg.target_three_url)

        cfg2 = load_config(cfg_path)
        assert "hackmd" in cfg2.platform_throttle
        assert cfg2.platform_throttle["hackmd"] == pytest.approx(45.0)

    def test_save_config_preserves_multiple_throttle_entries(self, tmp_path):
        """Multiple [throttle.*] entries all survive a save_config() call."""
        from backlink_publisher.config.loader import load_config
        from backlink_publisher.config.writer import save_config

        initial = (
            "[throttle.hackmd]\ndelay_s = 45.0\n"
            "[throttle.devto]\ndelay_s = 20.0\n"
        )
        cfg_path = _write_toml(tmp_path, initial)
        cfg = load_config(cfg_path)
        save_config(cfg, cfg_path, target_three_url=cfg.target_three_url)

        cfg2 = load_config(cfg_path)
        assert cfg2.platform_throttle["hackmd"] == pytest.approx(45.0)
        assert cfg2.platform_throttle["devto"] == pytest.approx(20.0)
