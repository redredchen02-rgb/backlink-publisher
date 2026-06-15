"""Observe→enforce rollout for the reliability policy (Plan 2026-06-15-001).

observe mode runs the health-gate + circuit checks and EMITS what they would do
(would_skip_policy / would_skip_circuit) but still dispatches — never actually
skips. enforce mode (covered by test_reliability_policy.py) actually skips.
"""
from __future__ import annotations

__tier__ = "unit"

from unittest.mock import patch

import pytest

from backlink_publisher.publishing.adapters.base import AdapterResult
from backlink_publisher.publishing.reliability.events import Outcome
from backlink_publisher.publishing.reliability.policy import (
    POLICY_ENV,
    policy_enabled,
    policy_mode,
    publish_with_policy,
)

_GET_STATUS = "webui_store.channel_status.get_status"
_ADAPTER_PUB = "backlink_publisher.publishing.reliability.policy.adapter_publish"
_EMIT = "backlink_publisher.publishing.reliability.policy.emit_attempt"


@pytest.fixture()
def cfg(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("BACKLINK_PUBLISHER_CIRCUIT_COOLDOWN_S", "300")
    monkeypatch.setenv(POLICY_ENV, "observe")

    class _Cfg:
        config_dir = tmp_path

    return _Cfg()


def _ok():
    return AdapterResult(status="published", adapter="medium-api", platform="medium")


# ── mode resolution ──────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "env,expected",
    [
        (None, "off"),
        ("", "off"),
        ("0", "off"),
        ("garbage", "off"),
        ("observe", "observe"),
        ("OBSERVE", "observe"),
        ("enforce", "enforce"),
        ("1", "enforce"),  # back-compat
    ],
)
def test_policy_mode_resolution(monkeypatch, env, expected):
    if env is None:
        monkeypatch.delenv(POLICY_ENV, raising=False)
    else:
        monkeypatch.setenv(POLICY_ENV, env)
    assert policy_mode() == expected
    assert policy_enabled() is (expected != "off")


# ── observe: health gate ─────────────────────────────────────────────────────

def test_observe_unbound_dispatches_anyway(cfg):
    """An unbound browser channel is NOT skipped in observe — it dispatches."""
    with patch(_GET_STATUS, return_value={"status": "unbound"}), \
         patch(_ADAPTER_PUB, return_value=_ok()) as pub, \
         patch(_EMIT) as emit:
        out = publish_with_policy("medium", payload={"id": "1"}, config=cfg)

    pub.assert_called_once()
    assert out.status == "published"
    outcomes = [c.args[1] for c in emit.call_args_list]
    assert Outcome.WOULD_SKIP_POLICY in outcomes


def test_observe_bound_does_not_emit_would_skip_policy(cfg):
    with patch(_GET_STATUS, return_value={"status": "bound"}), \
         patch(_ADAPTER_PUB, return_value=_ok()), \
         patch(_EMIT) as emit:
        publish_with_policy("medium", payload={"id": "1"}, config=cfg)
    outcomes = [c.args[1] for c in emit.call_args_list]
    assert Outcome.WOULD_SKIP_POLICY not in outcomes


# ── observe: circuit breaker ─────────────────────────────────────────────────

def test_observe_tripped_circuit_dispatches_anyway(cfg):
    """A tripped circuit is NOT skipped in observe — it dispatches + emits."""
    from backlink_publisher.publishing.reliability.circuit import trip
    trip("medium", cfg)

    with patch(_GET_STATUS, return_value={"status": "bound"}), \
         patch(_ADAPTER_PUB, return_value=_ok()) as pub, \
         patch(_EMIT) as emit:
        out = publish_with_policy("medium", payload={"id": "1"}, config=cfg)

    pub.assert_called_once()
    assert out.status == "published"
    outcomes = [c.args[1] for c in emit.call_args_list]
    assert Outcome.WOULD_SKIP_CIRCUIT in outcomes


def test_enforce_still_skips_tripped_circuit(cfg, monkeypatch):
    """Sanity: flipping to enforce restores the hard skip."""
    monkeypatch.setenv(POLICY_ENV, "enforce")
    from backlink_publisher.publishing.reliability.circuit import trip
    trip("medium", cfg)

    with patch(_GET_STATUS, return_value={"status": "bound"}), \
         patch(_ADAPTER_PUB) as pub:
        out = publish_with_policy("medium", payload={"id": "1"}, config=cfg)

    pub.assert_not_called()
    assert out.status == "skipped_circuit_open"


def test_off_is_transparent_passthrough(cfg, monkeypatch):
    monkeypatch.setenv(POLICY_ENV, "0")
    with patch(_GET_STATUS) as status, \
         patch(_ADAPTER_PUB, return_value=_ok()) as pub:
        out = publish_with_policy("medium", payload={"id": "1"}, config=cfg)
    pub.assert_called_once()
    status.assert_not_called()  # off never consults the health gate
    assert out.status == "published"
