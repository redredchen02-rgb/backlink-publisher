"""Tests for publishing._verify_adapters module - helper functions and basic functionality."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from backlink_publisher.publishing._verify import VerifyResult


class TestHelperFunctions:
    """Tests for helper functions in _verify_adapters module."""

    def test_utc_now_iso_format(self) -> None:
        from backlink_publisher.publishing._verify_adapters import _utc_now_iso
        result = _utc_now_iso()
        # Should be ISO format with UTC timezone
        assert isinstance(result, str)
        # Parse to verify format
        dt = datetime.fromisoformat(result)
        assert dt.tzinfo is not None

    def test_ok_result_factory(self) -> None:
        from backlink_publisher.publishing._verify_adapters import _ok_result
        result = _ok_result("test_identity")
        assert result.ok is True
        assert result.last_verify_result == "ok"
        assert result.identity == "test_identity"
        assert result.last_verified_at is not None
        assert result.blockers is None or result.blockers == []

    def test_ok_result_with_dofollow_false(self) -> None:
        from backlink_publisher.publishing._verify_adapters import _ok_result
        result = _ok_result("test_identity", dofollow=False)
        assert result.ok is True
        assert result.last_verify_result == "ok"
        assert result.identity == "test_identity"

    def test_timeout_result_factory(self) -> None:
        from backlink_publisher.publishing._verify_adapters import _timeout_result
        result = _timeout_result("timeout message")
        assert result.ok is False
        assert result.last_verify_result == "timeout"
        assert "timeout message" in str(result.blockers)

    def test_network_error_factory(self) -> None:
        from backlink_publisher.publishing._verify_adapters import _network_error
        exc = Exception("connection failed")
        result = _network_error("platform", exc)
        assert result.ok is False
        assert result.last_verify_result == "never"
        assert "platform" in str(result.blockers)
        assert "connection failed" in str(result.blockers)

    def test_non_json_factory(self) -> None:
        from backlink_publisher.publishing._verify_adapters import _non_json
        result = _non_json("platform")
        assert result.ok is False
        assert result.last_verify_result == "never"
        assert "non-JSON" in str(result.blockers)

    def test_token_expired_factory(self) -> None:
        from backlink_publisher.publishing._verify_adapters import _token_expired
        result = _token_expired("token expired message")
        assert result.ok is False
        assert result.last_verify_result == "token_expired"
        assert "token expired message" in str(result.blockers)

    def test_never_factory(self) -> None:
        from backlink_publisher.publishing._verify_adapters import _never
        result = _never("never verified message")
        assert result.ok is False
        assert result.last_verify_result == "never"
        assert "never verified message" in str(result.blockers)


class TestSetupChecks:
    """Tests for offline setup checks."""

    def test_check_medium_setup_no_config(self) -> None:
        from backlink_publisher.publishing._verify_adapters import _check_medium_setup
        config = MagicMock()
        config.medium_integration_token = None
        config.config_dir = MagicMock()

        with patch("backlink_publisher.config.load_medium_token", return_value=None), \
             patch("backlink_publisher.config.tokens.load_medium_integration_token", return_value=None), \
             patch("backlink_publisher.publishing.adapters.medium_browser.sync_playwright", None):
            result = _check_medium_setup(config)
            assert result is not None
            assert "Medium adapter not ready" in result

    def test_check_ghpages_setup_missing_config(self) -> None:
        from backlink_publisher.publishing._verify_adapters import _check_ghpages_setup
        config = MagicMock()
        config.ghpages = None

        result = _check_ghpages_setup(config)
        assert result is not None
        assert "GitHub Pages config missing" in result

    def test_check_ghpages_setup_missing_token(self) -> None:
        from backlink_publisher.publishing._verify_adapters import _check_ghpages_setup
        config = MagicMock()
        config.ghpages = MagicMock()
        config.ghpages.repo = "owner/repo"
        config.ghpages_token_path = MagicMock()
        config.ghpages_token_path.exists.return_value = False

        result = _check_ghpages_setup(config)
        assert result is not None
        assert "GitHub Pages PAT not stored" in result

    def test_check_velog_setup_missing_cookies(self) -> None:
        from backlink_publisher.publishing._verify_adapters import _check_velog_setup
        config = MagicMock()
        config.velog = None
        config.config_dir = MagicMock()
        config.config_dir.__truediv__ = lambda self, x: MagicMock(exists=MagicMock(return_value=False))

        with patch("pathlib.Path.exists", return_value=False):
            result = _check_velog_setup(config)
            assert result is not None
            assert "velog cookies not found" in result


class TestVerifyAdapterSetup:
    """Tests for verify_adapter_setup function."""

    def test_unknown_platform_offline(self) -> None:
        from backlink_publisher.publishing._verify_adapters import verify_adapter_setup
        config = MagicMock()

        with patch("backlink_publisher.publishing._verify_setup.registered_platforms", return_value=["blogger", "medium"]):
            with pytest.raises(Exception) as exc_info:
                verify_adapter_setup("unknown_platform", config, mode="offline")
            assert "No adapter configured" in str(exc_info.value) or "unknown" in str(exc_info.value).lower()

    def test_dry_run_unknown_platform(self) -> None:
        from backlink_publisher.publishing._verify_adapters import verify_adapter_setup
        config = MagicMock()

        with patch("backlink_publisher.publishing._verify_setup.registered_platforms", return_value=["blogger", "medium"]):
            result = verify_adapter_setup("unknown_platform", config, mode="dry-run")
            assert result.ok is False
            assert result.last_verify_result == "never"

    def test_dry_run_known_platform(self) -> None:
        from backlink_publisher.publishing._verify_adapters import verify_adapter_setup
        config = MagicMock()

        with patch("backlink_publisher.publishing._verify_setup.registered_platforms", return_value=["blogger", "medium"]):
            result = verify_adapter_setup("blogger", config, mode="dry-run")
            assert result.ok is True
            assert result.last_verify_result == "unverifiable_live"


class TestVerifyResult:
    """Tests for VerifyResult dataclass."""

    def test_verify_result_creation(self) -> None:
        result = VerifyResult(
            ok=True,
            last_verify_result="ok",
            identity="test",
            last_verified_at="2024-01-01T00:00:00Z",
            blockers=None,
        )
        assert result.ok is True
        assert result.last_verify_result == "ok"
        assert result.identity == "test"
        assert result.last_verified_at == "2024-01-01T00:00:00Z"
        assert result.blockers is None

    def test_verify_result_with_blockers(self) -> None:
        result = VerifyResult(
            ok=False,
            last_verify_result="timeout",
            blockers=["connection timeout"],
        )
        assert result.ok is False
        assert result.last_verify_result == "timeout"
        assert result.blockers == ["connection timeout"]
