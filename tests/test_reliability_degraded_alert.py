"""Degraded-channel proactive alert (Plan 2026-06-15-006, Unit 5/R5a).

When a channel ENTERS a degraded state (circuit trip / ban) the policy layer
records a ``degraded`` reliability.decision — in observe mode too, independent of
enforce — so the external alert stack can proactively notify the operator.
Transition-deduped: not re-emitted on every re-dispatch into an already-degraded
channel.
"""
from __future__ import annotations

__tier__ = "unit"

import json
from unittest.mock import patch

import pytest

from backlink_publisher._util.errors import AuthExpiredError, ExternalServiceError
from backlink_publisher.events import EventStore
from backlink_publisher.events.kinds import RELIABILITY_DECISION
from backlink_publisher.publishing.reliability.policy import (
    POLICY_ENV,
    publish_with_policy,
)

_GET_STATUS = "webui_store.channel_status.get_status"
_ADAPTER_PUB = "backlink_publisher.publishing.reliability.policy.adapter_publish"


@pytest.fixture()
def cfg(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("BACKLINK_PUBLISHER_CIRCUIT_COOLDOWN_S", "300")
    monkeypatch.setenv(POLICY_ENV, "observe")

    class _Cfg:
        config_dir = tmp_path

    return _Cfg()


def _degraded_rows():
    rows = EventStore().query(
        "SELECT payload_json FROM events WHERE kind = ?", (RELIABILITY_DECISION,)
    )
    out = [json.loads(r["payload_json"]) for r in rows]
    return [r for r in out if r["decision"] == "degraded"]


def test_ban_emits_degraded_in_observe(cfg):
    """A ban trips the circuit and records degraded — even in observe mode."""
    exc = AuthExpiredError(channel="medium", reason="Account banned")
    with patch(_GET_STATUS, return_value={"status": "bound"}), \
         patch(_ADAPTER_PUB, side_effect=exc):
        with pytest.raises(AuthExpiredError):
            publish_with_policy("medium", payload={"id": "1"}, config=cfg)

    rows = _degraded_rows()
    assert len(rows) == 1
    assert rows[0]["reason"] == "ban"
    assert rows[0]["mode"] == "observe"
    assert rows[0]["platform"] == "medium"


def test_repeat_ban_does_not_re_emit_degraded(cfg):
    """A second ban into the already-tripped channel must NOT re-alert."""
    exc = AuthExpiredError(channel="medium", reason="Account banned")
    with patch(_GET_STATUS, return_value={"status": "bound"}), \
         patch(_ADAPTER_PUB, side_effect=exc):
        for _ in range(3):
            with pytest.raises(AuthExpiredError):
                publish_with_policy("medium", payload={"id": "1"}, config=cfg)

    # Only the first (transition into degraded) emitted.
    assert len(_degraded_rows()) == 1


def test_re_ban_after_cooldown_does_not_re_emit(cfg, monkeypatch):
    """A re-ban after cooldown (channel now HALF_OPEN) must NOT re-alert.

    Regression for the is_tripped-vs-is_degraded dedup: is_tripped returns False
    in HALF_OPEN, so using it would re-emit a degraded alert every cooldown cycle.
    is_degraded reports the raw tripped flag, so HALF_OPEN counts as already-degraded.
    """
    monkeypatch.setenv("BACKLINK_PUBLISHER_CIRCUIT_COOLDOWN_S", "0")  # cooldown always elapsed
    exc = AuthExpiredError(channel="medium", reason="Account banned")
    with patch(_GET_STATUS, return_value={"status": "bound"}), \
         patch(_ADAPTER_PUB, side_effect=exc):
        for _ in range(3):
            with pytest.raises(AuthExpiredError):
                publish_with_policy("medium", payload={"id": "1"}, config=cfg)

    assert len(_degraded_rows()) == 1


def test_consecutive_errors_trip_emits_degraded(cfg, monkeypatch):
    """Reaching the consecutive-error threshold trips → one degraded(circuit_trip)."""
    monkeypatch.setenv("BACKLINK_PUBLISHER_CIRCUIT_ERROR_THRESHOLD", "2")
    exc = ExternalServiceError("upstream 500")
    with patch(_GET_STATUS, return_value={"status": "bound"}), \
         patch(_ADAPTER_PUB, side_effect=exc):
        for _ in range(2):
            with pytest.raises(ExternalServiceError):
                publish_with_policy("medium", payload={"id": "1"}, config=cfg)

    rows = _degraded_rows()
    assert len(rows) == 1
    assert rows[0]["reason"] == "circuit_trip"


def test_healthy_publish_emits_no_degraded(cfg):
    from backlink_publisher.publishing.adapters.base import AdapterResult

    ok = AdapterResult(status="published", adapter="medium-api", platform="medium")
    with patch(_GET_STATUS, return_value={"status": "bound"}), \
         patch(_ADAPTER_PUB, return_value=ok):
        publish_with_policy("medium", payload={"id": "1"}, config=cfg)
    assert _degraded_rows() == []
