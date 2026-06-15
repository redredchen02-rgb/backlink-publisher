"""Corrupt circuit-state degrades to observe under enforce (Plan 2026-06-15-006, U8).

A genuine OPEN trip skips. But an UNREADABLE state file (corruption) is not a real
trip — under enforce it degrades to observe (dispatch this once + a loud
circuit_state_unreadable alert) rather than silently skipping every channel.
"""
from __future__ import annotations

__tier__ = "unit"

import json
from unittest.mock import patch

import pytest

from backlink_publisher.events import EventStore
from backlink_publisher.events.kinds import RELIABILITY_DECISION
from backlink_publisher.publishing.adapters.base import AdapterResult
from backlink_publisher.publishing.reliability.circuit import circuit_status, trip
from backlink_publisher.publishing.reliability.policy import (
    ENFORCE_ALLOWLIST_ENV,
    POLICY_ENV,
    publish_with_policy,
)

_GET_STATUS = "webui_store.channel_status.get_status"
_ADAPTER_PUB = "backlink_publisher.publishing.reliability.policy.adapter_publish"
_STATE_FILE = "publish-circuit-state.json"


@pytest.fixture()
def cfg(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("BACKLINK_PUBLISHER_CIRCUIT_COOLDOWN_S", "300")
    monkeypatch.setenv(POLICY_ENV, "enforce")
    monkeypatch.setenv(ENFORCE_ALLOWLIST_ENV, "medium")

    class _Cfg:
        config_dir = tmp_path

    return _Cfg()


def _ok():
    return AdapterResult(status="published", adapter="medium-api", platform="medium")


def _decisions():
    rows = EventStore().query(
        "SELECT payload_json FROM events WHERE kind = ?", (RELIABILITY_DECISION,)
    )
    return [json.loads(r["payload_json"]) for r in rows]


def _corrupt_state(tmp_path):
    (tmp_path / _STATE_FILE).write_text("{ this is not valid json", encoding="utf-8")


# ── circuit_status discrimination ────────────────────────────────────────────

def test_circuit_status_closed_when_no_file(cfg):
    assert circuit_status("medium", cfg) == "closed"


def test_circuit_status_open_for_valid_trip(cfg):
    trip("medium", cfg)
    assert circuit_status("medium", cfg) == "open"


def test_circuit_status_half_open_after_cooldown(cfg, monkeypatch):
    trip("medium", cfg)
    monkeypatch.setenv("BACKLINK_PUBLISHER_CIRCUIT_COOLDOWN_S", "0")
    assert circuit_status("medium", cfg) == "half-open"  # CircuitState.HALF_OPEN.value


def test_circuit_status_unreadable_for_corrupt_file(cfg, tmp_path):
    _corrupt_state(tmp_path)
    assert circuit_status("medium", cfg) == "unreadable"


def test_circuit_status_unreadable_for_tripped_without_timestamp(cfg, tmp_path):
    (tmp_path / _STATE_FILE).write_text(
        json.dumps({"medium": {"state": "open", "tripped": True, "tripped_at_iso": None}}),
        encoding="utf-8",
    )
    assert circuit_status("medium", cfg) == "unreadable"


# ── enforce degrade vs skip ──────────────────────────────────────────────────

def test_enforce_unreadable_degrades_to_observe(cfg, tmp_path):
    """Corrupt state under enforce → dispatch (degrade), NOT a silent skip."""
    _corrupt_state(tmp_path)
    with patch(_GET_STATUS, return_value={"status": "bound"}), \
         patch(_ADAPTER_PUB, return_value=_ok()) as pub:
        out = publish_with_policy("medium", payload={"id": "1"}, config=cfg)
    pub.assert_called_once()              # dispatched, not skipped
    assert out.status == "published"
    decisions = [d["decision"] for d in _decisions()]
    assert "circuit_state_unreadable" in decisions
    assert "skipped_circuit_open" not in decisions


def test_enforce_valid_open_still_skips(cfg):
    """Regression: a genuine OPEN trip still skips under enforce."""
    trip("medium", cfg)
    with patch(_GET_STATUS, return_value={"status": "bound"}), \
         patch(_ADAPTER_PUB) as pub:
        out = publish_with_policy("medium", payload={"id": "1"}, config=cfg)
    pub.assert_not_called()
    assert out.status == "skipped_circuit_open"


def test_observe_corrupt_state_unchanged(cfg, tmp_path, monkeypatch):
    """Observe + corrupt state behaves as today (dispatch, no skip)."""
    monkeypatch.setenv(POLICY_ENV, "observe")
    _corrupt_state(tmp_path)
    with patch(_GET_STATUS, return_value={"status": "bound"}), \
         patch(_ADAPTER_PUB, return_value=_ok()) as pub:
        out = publish_with_policy("medium", payload={"id": "1"}, config=cfg)
    pub.assert_called_once()
    assert out.status == "published"
    # observe records a would_skip_circuit (the fail-closed is_tripped fired), not unreadable.
    assert "circuit_state_unreadable" not in [d["decision"] for d in _decisions()]
