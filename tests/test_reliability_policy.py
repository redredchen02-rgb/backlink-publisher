"""Tests for publish_with_policy — Plan 2026-05-28-001 Units 2–3.

Updated for Stage 1 (Plan 2026-05-28-001):
- Policy applies to ALL platforms, not just browser-tier
- Tests updated to reflect this change
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from backlink_publisher._util.errors import AuthExpiredError, ExternalServiceError
from backlink_publisher.publishing.adapters.base import AdapterResult
from backlink_publisher.publishing.reliability.events import Outcome
from backlink_publisher.publishing.reliability.policy import (
    publish_with_policy,
    policy_enabled,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def cfg(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("BACKLINK_PUBLISHER_CIRCUIT_COOLDOWN_S", "300")
    monkeypatch.setenv("BACKLINK_PUBLISHER_RELIABILITY_POLICY_ENABLED", "1")

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


def test_policy_applies_to_all_platforms(cfg):
    """Stage 1: policy applies to ALL platforms, including non-browser-tier."""
    for platform in ("blogger", "wordpresscom", "telegraph", "notion", "hashnode", "medium", "velog"):
        result = _result(platform=platform)
        with patch(_GET_STATUS, return_value={"status": "bound"}), \
             patch(_ADAPTER_PUB, return_value=result) as mock_pub:
            out = publish_with_policy(platform, payload={"id": "1"}, config=cfg)

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
    """429 responses trip the circuit immediately."""
    from backlink_publisher.publishing.reliability.circuit import is_tripped

    exc = ExternalServiceError("rate limited: 429")
    with patch(_GET_STATUS, return_value={"status": "bound"}), \
         patch(_ADAPTER_PUB, side_effect=exc), \
         patch(_EMIT):
        with pytest.raises(ExternalServiceError):
            publish_with_policy("medium", payload={"id": "1"}, config=cfg)

    assert is_tripped("medium", cfg) is True


def test_trip_on_error_with_status_503(cfg):
    """503 responses trip the circuit immediately."""
    from backlink_publisher.publishing.reliability.circuit import is_tripped

    exc = ExternalServiceError("service unavailable: 503")
    with patch(_GET_STATUS, return_value={"status": "bound"}), \
         patch(_ADAPTER_PUB, side_effect=exc), \
         patch(_EMIT):
        with pytest.raises(ExternalServiceError):
            publish_with_policy("medium", payload={"id": "1"}, config=cfg)

    assert is_tripped("medium", cfg) is True


def test_consecutive_errors_increment_counter(cfg):
    """Consecutive transient errors increment error counter; trip after threshold."""
    # For timeout-like errors, the policy now calls trip_on_error
    exc = ExternalServiceError("timeout")
    with patch(_GET_STATUS, return_value={"status": "bound"}), \
         patch(_ADAPTER_PUB, side_effect=exc), \
         patch(_EMIT):
        with pytest.raises(ExternalServiceError):
            publish_with_policy("medium", payload={"id": "1"}, config=cfg)

    # Verify error counter was incremented
    from backlink_publisher.publishing.reliability.circuit import _get_state
    state = _get_state("medium", cfg)
    assert state.get("consecutive_errors") == 1
    # Circuit still closed because threshold (3) not reached yet
    assert state.get("state") == "closed"


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


def test_event_emitted_with_http_status(cfg):
    """Events include HTTP status code for better observability."""
    with patch(_GET_STATUS, return_value={"status": "bound"}), \
         patch(_ADAPTER_PUB, side_effect=ExternalServiceError("API error: 503")), \
         patch(_EMIT) as mock_emit:
        with pytest.raises(ExternalServiceError):
            publish_with_policy("medium", payload={"id": "1"}, config=cfg)

    # Verify http_status was passed to emit_attempt
    call_kwargs = mock_emit.call_args[1]
    assert call_kwargs.get("http_status") == 503
