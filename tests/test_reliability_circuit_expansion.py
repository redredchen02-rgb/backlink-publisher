"""Circuit breaker expansion — Plan 2026-06-03-004 Phase 3 (U9-U11).

The reliability policy's circuit breaker, previously browser-tier only and
ban-signal only, now:
  - U9:  applies to ALL platforms (not just browser-tier)
  - U10: trips after N consecutive AuthExpiredError (no ban keyword)
  - U11: trips after N consecutive ExternalServiceError

Consecutive failures are counted in LockedHealthStore.consecutive_failures
(the field Phase 1 surfaced but never incremented). A success resets it; a
trip resets it so the post-cooldown window starts fresh. Thresholds are
configurable via env.
"""
from __future__ import annotations

__tier__ = "unit"
from unittest.mock import patch

import pytest

from backlink_publisher._util.errors import AuthExpiredError, ExternalServiceError
from backlink_publisher.publishing.adapters.base import AdapterResult
from backlink_publisher.publishing.reliability.policy import publish_with_policy


@pytest.fixture()
def cfg(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("BACKLINK_PUBLISHER_CIRCUIT_COOLDOWN_S", "300")
    monkeypatch.setenv("BACKLINK_PUBLISHER_RELIABILITY_POLICY_ENABLED", "1")
    # Enforce is per-channel (U7); allowlist the channel these tests exercise.
    monkeypatch.setenv("BACKLINK_PUBLISHER_RELIABILITY_ENFORCE_CHANNELS", "blogger")

    class _Cfg:
        config_dir = tmp_path

    return _Cfg()


_GET_STATUS = "webui_store.channel_status.get_status"
_ADAPTER_PUB = "backlink_publisher.publishing.reliability.policy.adapter_publish"
_EMIT = "backlink_publisher.publishing.reliability.policy.emit_attempt"


def _ok(platform="blogger"):
    return AdapterResult(status="published", adapter=f"{platform}-api", platform=platform)


# ── U9: circuit applies to non-browser-tier platforms ──────────────────────────

def test_non_browser_tier_dispatches_when_circuit_closed(cfg):
    """blogger (non-browser) now goes through the circuit; closed → dispatches."""
    with patch(_ADAPTER_PUB, return_value=_ok()) as mock_pub, patch(_EMIT):
        out = publish_with_policy("blogger", payload={"id": "1"}, config=cfg)
    mock_pub.assert_called_once()
    assert out.status == "published"


def test_non_browser_tier_blocked_when_circuit_open(cfg):
    """A tripped circuit blocks a non-browser platform (U9 — previously bypassed)."""
    from backlink_publisher.publishing.reliability.circuit import trip
    trip("blogger", cfg)

    with patch(_ADAPTER_PUB) as mock_pub, patch(_EMIT):
        out = publish_with_policy("blogger", payload={"id": "1"}, config=cfg)
    mock_pub.assert_not_called()
    assert out.status == "skipped_circuit_open"


def test_non_browser_tier_skips_health_gate(cfg):
    """Non-browser platforms have no channel binding → health gate is not applied."""
    # get_status must NOT be consulted for blogger; if it were and returned
    # unbound, dispatch would be skipped. We assert dispatch happens.
    with patch(_ADAPTER_PUB, return_value=_ok()) as mock_pub, patch(_EMIT), \
         patch(_GET_STATUS, return_value={"status": "unbound"}) as mock_status:
        out = publish_with_policy("blogger", payload={"id": "1"}, config=cfg)
    mock_pub.assert_called_once()
    mock_status.assert_not_called()
    assert out.status == "published"


# ── U10: consecutive AuthExpired (non-ban) trips ───────────────────────────────

def test_auth_expired_trips_after_threshold(cfg, monkeypatch):
    from backlink_publisher.publishing.reliability.circuit import is_tripped
    monkeypatch.setenv("BACKLINK_PUBLISHER_CIRCUIT_AUTH_THRESHOLD", "3")

    exc = AuthExpiredError(channel="blogger", reason="Session expired")
    with patch(_ADAPTER_PUB, side_effect=exc), patch(_EMIT):
        for i in range(2):
            with pytest.raises(AuthExpiredError):
                publish_with_policy("blogger", payload={"id": str(i)}, config=cfg)
            assert is_tripped("blogger", cfg) is False, f"tripped too early at {i+1}"
        # 3rd consecutive failure → trips
        with pytest.raises(AuthExpiredError):
            publish_with_policy("blogger", payload={"id": "2"}, config=cfg)
    assert is_tripped("blogger", cfg) is True


def test_auth_expired_below_threshold_does_not_trip(cfg, monkeypatch):
    from backlink_publisher.publishing.reliability.circuit import is_tripped
    monkeypatch.setenv("BACKLINK_PUBLISHER_CIRCUIT_AUTH_THRESHOLD", "5")

    exc = AuthExpiredError(channel="blogger", reason="Session expired")
    with patch(_ADAPTER_PUB, side_effect=exc), patch(_EMIT):
        for i in range(4):
            with pytest.raises(AuthExpiredError):
                publish_with_policy("blogger", payload={"id": str(i)}, config=cfg)
    assert is_tripped("blogger", cfg) is False


def test_success_resets_consecutive_failures(cfg, monkeypatch):
    from backlink_publisher.health.persistence import locked_store
    monkeypatch.setenv("BACKLINK_PUBLISHER_CIRCUIT_AUTH_THRESHOLD", "3")

    exc = AuthExpiredError(channel="blogger", reason="Session expired")
    with patch(_ADAPTER_PUB, side_effect=exc), patch(_EMIT):
        for i in range(2):
            with pytest.raises(AuthExpiredError):
                publish_with_policy("blogger", payload={"id": str(i)}, config=cfg)
    assert locked_store.get("blogger", cfg)["consecutive_failures"] == 2

    with patch(_ADAPTER_PUB, return_value=_ok()), patch(_EMIT):
        publish_with_policy("blogger", payload={"id": "ok"}, config=cfg)
    assert locked_store.get("blogger", cfg)["consecutive_failures"] == 0


# ── U11: consecutive ExternalServiceError trips ────────────────────────────────

def test_external_error_trips_after_threshold(cfg, monkeypatch):
    from backlink_publisher.publishing.reliability.circuit import is_tripped
    monkeypatch.setenv("BACKLINK_PUBLISHER_CIRCUIT_ERROR_THRESHOLD", "2")

    with patch(_ADAPTER_PUB, side_effect=ExternalServiceError("API 503")), patch(_EMIT):
        with pytest.raises(ExternalServiceError):
            publish_with_policy("blogger", payload={"id": "0"}, config=cfg)
        assert is_tripped("blogger", cfg) is False
        with pytest.raises(ExternalServiceError):
            publish_with_policy("blogger", payload={"id": "1"}, config=cfg)
    assert is_tripped("blogger", cfg) is True


# ── trip resets the counter so post-cooldown starts fresh ──────────────────────

def test_trip_resets_counter(cfg, monkeypatch):
    from backlink_publisher.health.persistence import locked_store
    monkeypatch.setenv("BACKLINK_PUBLISHER_CIRCUIT_ERROR_THRESHOLD", "2")

    with patch(_ADAPTER_PUB, side_effect=ExternalServiceError("API 503")), patch(_EMIT):
        for i in range(2):
            with pytest.raises(ExternalServiceError):
                publish_with_policy("blogger", payload={"id": str(i)}, config=cfg)
    # Tripped → counter reset to 0 (re-armed for the next cooldown window).
    assert locked_store.get("blogger", cfg)["consecutive_failures"] == 0


# ── ban still trips immediately (regression) ───────────────────────────────────

def test_ban_signal_still_trips_immediately(cfg):
    from backlink_publisher.publishing.reliability.circuit import is_tripped

    exc = AuthExpiredError(channel="blogger", reason="Account banned")
    with patch(_ADAPTER_PUB, side_effect=exc), patch(_EMIT):
        with pytest.raises(AuthExpiredError):
            publish_with_policy("blogger", payload={"id": "0"}, config=cfg)
    assert is_tripped("blogger", cfg) is True
