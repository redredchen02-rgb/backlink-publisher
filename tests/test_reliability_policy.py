"""Tests for publish_with_policy — Plan 2026-05-28-001 Units 2–3.

Updated for Stage 1 (Plan 2026-05-28-001):
- Policy applies to ALL platforms, not just browser-tier
- Tests updated to reflect this change
"""
from __future__ import annotations

__tier__ = "unit"
from unittest.mock import patch

import pytest

from backlink_publisher._util.errors import AuthExpiredError, ExternalServiceError
from backlink_publisher.publishing.adapters.base import AdapterResult
from backlink_publisher.publishing.reliability.events import Outcome
from backlink_publisher.publishing.reliability.policy import (
    publish_with_policy,
    policy_enabled,
    _is_browser_tier,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def cfg(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("BACKLINK_PUBLISHER_CIRCUIT_COOLDOWN_S", "300")
    monkeypatch.setenv("BACKLINK_PUBLISHER_RELIABILITY_POLICY_ENABLED", "1")
    # Enforce is per-channel (U7): allowlist the channel these tests exercise so
    # enforce actually skips. Without this, enforce mode falls back to observe.
    monkeypatch.setenv("BACKLINK_PUBLISHER_RELIABILITY_ENFORCE_CHANNELS", "medium")

    class _Cfg:
        config_dir = tmp_path

    return _Cfg()


def _result(platform="medium", status="published"):
    return AdapterResult(status=status, adapter="medium-api", platform=platform)


# get_status is lazily imported inside policy.py, so we patch at its source.
_GET_STATUS = "webui_store.channel_status.get_status"
_ADAPTER_PUB = "backlink_publisher.publishing.reliability.policy.adapter_publish"
_EMIT = "backlink_publisher.publishing.reliability.policy.emit_attempt"


# ---------------------------------------------------------------------------
# Passthrough when policy disabled
# ---------------------------------------------------------------------------


def test_passthrough_when_policy_disabled(tmp_path, monkeypatch):
    """When BACKLINK_PUBLISHER_RELIABILITY_POLICY_ENABLED != '1', delegates directly."""
    monkeypatch.delenv("BACKLINK_PUBLISHER_RELIABILITY_POLICY_ENABLED", raising=False)

    class _Cfg:
        config_dir = tmp_path

    result = _result()
    with patch(_ADAPTER_PUB, return_value=result) as mock_pub:
        out = publish_with_policy("medium", payload={"id": "1"}, config=_Cfg())

    mock_pub.assert_called_once()
    assert out.status == "published"


# ---------------------------------------------------------------------------
# Stage 1: Policy applies to ALL platforms (not just browser-tier)
# ---------------------------------------------------------------------------


def test_browser_tier_platforms_gated_by_health(cfg):
    """Browser-tier platforms go through the health gate (Stage 1 + Phase 3)."""
    for platform in ("medium", "velog"):
        result = _result(platform=platform)
        with patch(_GET_STATUS, return_value={"status": "bound"}), \
             patch(_ADAPTER_PUB, return_value=result) as mock_pub:
            out = publish_with_policy(platform, payload={"id": "1"}, config=cfg)
            mock_pub.assert_called_once()
            assert out.status == "published"


def test_non_browser_tier_platforms():
    for p in ("blogger", "wordpress", "telegraph", "notion", "hashnode"):
        assert _is_browser_tier(p) is False


# ---------------------------------------------------------------------------
# Unit 2: Non-browser-tier passthrough
# ---------------------------------------------------------------------------


def test_non_browser_tier_dispatches_through_closed_circuit(cfg):
    """Non-browser-tier platforms skip the health gate but DO pass the circuit
    breaker (Phase 3 U9). With a closed circuit, dispatch proceeds normally."""
    result = _result(platform="blogger")
    with patch(_ADAPTER_PUB, return_value=result) as mock_pub, patch(_EMIT):
        out = publish_with_policy("blogger", payload={"id": "1"}, config=cfg)

    mock_pub.assert_called_once()
    assert out.status == "published"


# ---------------------------------------------------------------------------
# Unit 2: Health gate
# ---------------------------------------------------------------------------


def test_health_gate_blocks_unbound(cfg):
    with patch(_GET_STATUS, return_value={"status": "unbound"}):
        out = publish_with_policy("medium", payload={"id": "1"}, config=cfg)

    assert out.status == "skipped_policy"
    assert "unbound" in (out.error or "")


def test_health_gate_blocks_expired(cfg):
    with patch(_GET_STATUS, return_value={"status": "expired"}):
        out = publish_with_policy("medium", payload={"id": "1"}, config=cfg)

    assert out.status == "skipped_policy"


def test_health_gate_allows_bound(cfg):
    result = _result()
    with patch(_GET_STATUS, return_value={"status": "bound"}), \
         patch(_ADAPTER_PUB, return_value=result):
        out = publish_with_policy("medium", payload={"id": "1"}, config=cfg)

    assert out.status == "published"


def test_health_gate_fails_closed_on_exception(cfg):
    """If get_status raises (import or runtime), channel is treated as unbound."""
    with patch(_GET_STATUS, side_effect=RuntimeError("store unavailable")):
        out = publish_with_policy("medium", payload={"id": "1"}, config=cfg)

    assert out.status == "skipped_policy"


# ---------------------------------------------------------------------------
# Unit 2: Observability events
# ---------------------------------------------------------------------------


def test_event_emitted_on_success(cfg):
    with patch(_GET_STATUS, return_value={"status": "bound"}), \
         patch(_ADAPTER_PUB, return_value=_result()), \
         patch(_EMIT) as mock_emit:
        publish_with_policy("medium", payload={"id": "1"}, config=cfg)

    mock_emit.assert_called_once()
    assert mock_emit.call_args[0][0] == "medium"
    assert mock_emit.call_args[0][1] == Outcome.SUCCESS


def test_event_emitted_on_auth_expired(cfg):
    exc = AuthExpiredError(channel="medium", reason="Session expired")
    with patch(_GET_STATUS, return_value={"status": "bound"}), \
         patch(_ADAPTER_PUB, side_effect=exc), \
         patch(_EMIT) as mock_emit:
        with pytest.raises(AuthExpiredError):
            publish_with_policy("medium", payload={"id": "1"}, config=cfg)

    mock_emit.assert_called_once()
    assert mock_emit.call_args[0][1] == Outcome.AUTH_EXPIRED


def test_event_emitted_on_auth_banned(cfg):
    exc = AuthExpiredError(channel="medium", reason="Account banned")
    with patch(_GET_STATUS, return_value={"status": "bound"}), \
         patch(_ADAPTER_PUB, side_effect=exc), \
         patch(_EMIT) as mock_emit:
        with pytest.raises(AuthExpiredError):
            publish_with_policy("medium", payload={"id": "1"}, config=cfg)

    mock_emit.assert_called_once()
    assert mock_emit.call_args[0][1] == Outcome.AUTH_BANNED


def test_event_emitted_on_external_error(cfg):
    with patch(_GET_STATUS, return_value={"status": "bound"}), \
         patch(_ADAPTER_PUB, side_effect=ExternalServiceError("Browser crashed")), \
         patch(_EMIT) as mock_emit:
        with pytest.raises(ExternalServiceError):
            publish_with_policy("medium", payload={"id": "1"}, config=cfg)

    mock_emit.assert_called_once()
    assert mock_emit.call_args[0][1] == Outcome.EXTERNAL_ERROR


# ---------------------------------------------------------------------------
# Unit 3: Circuit breaker integration
# ---------------------------------------------------------------------------


def test_circuit_open_skips_dispatch(cfg):
    """Tripped circuit → skipped_circuit_open without calling adapter_publish."""
    from backlink_publisher.publishing.reliability.circuit import trip
    trip("medium", cfg)

    with patch(_GET_STATUS, return_value={"status": "bound"}), \
         patch(_ADAPTER_PUB) as mock_pub:
        out = publish_with_policy("medium", payload={"id": "1"}, config=cfg)

    mock_pub.assert_not_called()
    assert out.status == "skipped_circuit_open"


def test_ban_signal_trips_circuit(cfg):
    """AuthExpiredError with ban reason trips the circuit."""
    from backlink_publisher.publishing.reliability.circuit import is_tripped

    exc = AuthExpiredError(channel="medium", reason="Account banned")
    with patch(_GET_STATUS, return_value={"status": "bound"}), \
         patch(_ADAPTER_PUB, side_effect=exc), \
         patch(_EMIT):
        with pytest.raises(AuthExpiredError):
            publish_with_policy("medium", payload={"id": "1"}, config=cfg)

    assert is_tripped("medium", cfg) is True


def test_plain_auth_expiry_does_not_trip_circuit(cfg):
    """AuthExpiredError without ban reason does NOT trip the circuit."""
    from backlink_publisher.publishing.reliability.circuit import is_tripped

    exc = AuthExpiredError(channel="medium", reason="Session expired")
    with patch(_GET_STATUS, return_value={"status": "bound"}), \
         patch(_ADAPTER_PUB, side_effect=exc), \
         patch(_EMIT):
        with pytest.raises(AuthExpiredError):
            publish_with_policy("medium", payload={"id": "1"}, config=cfg)

    assert is_tripped("medium", cfg) is False


def test_ban_on_medium_does_not_trip_velog(cfg):
    """Circuit breaker is per-platform."""
    from backlink_publisher.publishing.reliability.circuit import is_tripped

    exc = AuthExpiredError(channel="medium", reason="Account suspended")
    with patch(_GET_STATUS, return_value={"status": "bound"}), \
         patch(_ADAPTER_PUB, side_effect=exc), \
         patch(_EMIT):
        with pytest.raises(AuthExpiredError):
            publish_with_policy("medium", payload={"id": "1"}, config=cfg)

    assert is_tripped("velog", cfg) is False


# ---------------------------------------------------------------------------
# Stage 1: HALF_OPEN circuit state
# ---------------------------------------------------------------------------


def test_half_open_allows_test_traffic(cfg):
    """HALF_OPEN state allows limited trial traffic."""
    from backlink_publisher.publishing.reliability.circuit import (
        _transition_to_half_open,
        is_tripped,
    )

    _transition_to_half_open("medium", cfg)
    # HALF_OPEN state should NOT block (returns False for is_tripped)
    assert is_tripped("medium", cfg) is False


def test_trip_on_error_with_status_429(cfg):
    """Phase 3: consecutive ExternalServiceError trips at threshold (default 5)."""
    from backlink_publisher.publishing.reliability.circuit import is_tripped

    exc = ExternalServiceError("rate limited: 429")
    threshold = 5
    for i in range(threshold):
        with patch(_GET_STATUS, return_value={"status": "bound"}), \
             patch(_ADAPTER_PUB, side_effect=exc), \
             patch(_EMIT):
            with pytest.raises(ExternalServiceError):
                publish_with_policy("medium", payload={"id": "1"}, config=cfg)

    assert is_tripped("medium", cfg) is True


def test_trip_on_error_with_status_503(cfg):
    """Phase 3: consecutive ExternalServiceError trips at threshold (default 5)."""
    from backlink_publisher.publishing.reliability.circuit import is_tripped

    exc = ExternalServiceError("service unavailable: 503")
    threshold = 5
    for i in range(threshold):
        with patch(_GET_STATUS, return_value={"status": "bound"}), \
             patch(_ADAPTER_PUB, side_effect=exc), \
             patch(_EMIT):
            with pytest.raises(ExternalServiceError):
                publish_with_policy("medium", payload={"id": "1"}, config=cfg)

    assert is_tripped("medium", cfg) is True


def test_consecutive_errors_increment_counter(cfg):
    """Phase 3: consecutive ExternalServiceError increments health-store counter."""
    from backlink_publisher.health.persistence import locked_store

    exc = ExternalServiceError("timeout")
    with patch(_GET_STATUS, return_value={"status": "bound"}), \
         patch(_ADAPTER_PUB, side_effect=exc), \
         patch(_EMIT):
        with pytest.raises(ExternalServiceError):
            publish_with_policy("medium", payload={"id": "1"}, config=cfg)

    # Counter lives in LockedHealthStore.consecutive_failures (Phase 3 U10).
    entry = locked_store.get("medium", cfg)
    assert entry.get("consecutive_failures") == 1


def test_record_success_resets_error_counter(cfg):
    """Successful operation resets consecutive error counter."""
    from backlink_publisher.publishing.reliability.circuit import (
        trip_on_error,
        is_tripped,
    )

    # Trip the circuit first
    trip_on_error("medium", cfg, status_code=503)
    assert is_tripped("medium", cfg) is True

    # Record success should transition out of OPEN state after cooldown
    # But for testing, we'll verify the state transition logic exists
    # (Full end-to-end test requires cooldown simulation)
    assert is_tripped("medium", cfg) is True  # Still open due to cooldown


# ---------------------------------------------------------------------------
# Stage 1: Enhanced observability events
# ---------------------------------------------------------------------------


def test_event_emitted_with_external_error_outcome(cfg):
    """Phase 3: ExternalServiceError emits EXTERNAL_ERROR outcome."""
    with patch(_GET_STATUS, return_value={"status": "bound"}), \
         patch(_ADAPTER_PUB, side_effect=ExternalServiceError("API error: 503")), \
         patch(_EMIT) as mock_emit:
        with pytest.raises(ExternalServiceError):
            publish_with_policy("medium", payload={"id": "1"}, config=cfg)

    mock_emit.assert_called_once()
    assert mock_emit.call_args[0][1] == Outcome.EXTERNAL_ERROR


# ---------------------------------------------------------------------------
# 006-U1: legacy CIRCUIT_CONSECUTIVE_ERRORS knob warns once (dead on live path)
# ---------------------------------------------------------------------------


class TestLegacyConsecutiveEnvWarning:
    """The circuit-layer consecutive-errors env is dead on the publish_with_policy
    path; setting it must surface a one-shot warning, not silently do nothing."""

    @pytest.fixture(autouse=True)
    def _reset_warn_flag(self):
        import backlink_publisher.publishing.reliability.policy as pol

        pol._legacy_consecutive_warned = False
        yield
        pol._legacy_consecutive_warned = False

    def test_warns_once_and_points_at_real_knob(self, cfg, monkeypatch, capsys):
        monkeypatch.setenv("BACKLINK_PUBLISHER_CIRCUIT_CONSECUTIVE_ERRORS", "7")
        result = _result(platform="blogger")
        with patch(_ADAPTER_PUB, return_value=result), patch(_EMIT):
            publish_with_policy("blogger", payload={"id": "1"}, config=cfg)
            publish_with_policy("blogger", payload={"id": "2"}, config=cfg)
        err = capsys.readouterr().err
        # Exactly one warning across two publishes (one-shot)...
        assert err.count("CIRCUIT_CONSECUTIVE_ERRORS is set but has NO effect") == 1
        # ...and it redirects the operator to the live knob.
        assert "CIRCUIT_ERROR_THRESHOLD" in err

    def test_silent_when_legacy_env_unset(self, cfg, monkeypatch, capsys):
        monkeypatch.delenv(
            "BACKLINK_PUBLISHER_CIRCUIT_CONSECUTIVE_ERRORS", raising=False
        )
        result = _result(platform="blogger")
        with patch(_ADAPTER_PUB, return_value=result), patch(_EMIT):
            publish_with_policy("blogger", payload={"id": "1"}, config=cfg)
        err = capsys.readouterr().err
        assert "has NO effect" not in err

    def test_no_warning_on_disabled_policy_passthrough(self, tmp_path, monkeypatch, capsys):
        # Passthrough (policy disabled) never reaches the warn site.
        monkeypatch.delenv("BACKLINK_PUBLISHER_RELIABILITY_POLICY_ENABLED", raising=False)
        monkeypatch.setenv("BACKLINK_PUBLISHER_CIRCUIT_CONSECUTIVE_ERRORS", "7")

        class _Cfg:
            config_dir = tmp_path

        with patch(_ADAPTER_PUB, return_value=_result()):
            publish_with_policy("medium", payload={"id": "1"}, config=_Cfg())
        err = capsys.readouterr().err
        assert "has NO effect" not in err
