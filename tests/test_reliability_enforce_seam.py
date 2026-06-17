"""Enforce seam acceptance test for the first target, mastodon (Plan 2026-06-15-006, U9).

ACCEPTANCE (wiring) only: a fault-injected trip proves the allowlist→enforce→skip→
persist path is wired end to end. The VALUE criterion — that enforce skipped a
publish a NATURAL trip would otherwise have wasted — is an operational observation
in production over a bounded window, NOT something a test can assert (you cannot
force a genuine ban/session-expiry in a unit test). See the rollout runbook.

mastodon is the chosen first target: the only no-fallback channel that is also
browser-tier, so its per-platform circuit breaker is honest (no per-adapter work
needed) AND it can produce skipped_policy evidence via the health gate.
"""
from __future__ import annotations

__tier__ = "unit"

import json
from unittest.mock import patch

import pytest

from backlink_publisher.events import EventStore
from backlink_publisher.events.kinds import RELIABILITY_DECISION
from backlink_publisher.publishing.reliability.circuit import trip
from backlink_publisher.publishing.reliability.policy import (
    ENFORCE_ALLOWLIST_ENV,
    POLICY_ENV,
    publish_with_policy,
)

_GET_STATUS = "webui_store.channel_status.get_status"
_ADAPTER_PUB = "backlink_publisher.publishing.reliability.policy.adapter_publish"


@pytest.fixture()
def cfg(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("BACKLINK_PUBLISHER_CIRCUIT_COOLDOWN_S", "300")
    monkeypatch.setenv(POLICY_ENV, "enforce")
    monkeypatch.setenv(ENFORCE_ALLOWLIST_ENV, "mastodon")

    class _Cfg:
        config_dir = tmp_path

    return _Cfg()


def _decisions():
    rows = EventStore().query(
        "SELECT payload_json FROM events WHERE kind = ?", (RELIABILITY_DECISION,)
    )
    return [json.loads(r["payload_json"]) for r in rows]


def test_mastodon_enforce_seam_skips_and_persists(cfg):
    """Fault-injected trip → enforce skips mastodon and persists the decision."""
    trip("mastodon", cfg)  # ACCEPTANCE: fault-injected, not a natural trip
    with patch(_GET_STATUS, return_value={"status": "bound"}), \
         patch(_ADAPTER_PUB) as pub:
        out = publish_with_policy("mastodon", payload={"id": "1"}, config=cfg)

    pub.assert_not_called()
    assert out.status == "skipped_circuit_open"
    rows = _decisions()
    assert [r["decision"] for r in rows] == ["skipped_circuit_open"]
    assert rows[0]["mode"] == "enforce"
    assert rows[0]["platform"] == "mastodon"


def test_mastodon_health_gate_skip_is_reachable(cfg):
    """mastodon is browser-tier, so an unbound channel yields skipped_policy evidence."""
    with patch(_GET_STATUS, return_value={"status": "unbound"}), \
         patch(_ADAPTER_PUB) as pub:
        out = publish_with_policy("mastodon", payload={"id": "1"}, config=cfg)

    pub.assert_not_called()
    assert out.status == "skipped_policy"
    assert [r["decision"] for r in _decisions()] == ["skipped_policy"]


# ---------------------------------------------------------------------------
# Phase 0 U3 — mode/allowlist routing locks ("configured != verified": prove the
# gate actually differentiates by mode and allowlist, not just that it can skip).
# ---------------------------------------------------------------------------


def _cfg_with(tmp_path, monkeypatch, *, mode: str, allowlist: str):
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("BACKLINK_PUBLISHER_CIRCUIT_COOLDOWN_S", "300")
    monkeypatch.setenv(POLICY_ENV, mode)
    monkeypatch.setenv(ENFORCE_ALLOWLIST_ENV, allowlist)

    class _Cfg:
        config_dir = tmp_path

    return _Cfg()


def test_observe_mode_records_would_skip_not_skip(tmp_path, monkeypatch):
    """observe mode on an unbound channel must record `would_skip_policy` (NOT
    `skipped_policy`) and must still attempt the publish — proving mode routing,
    not just that a skip can fire."""
    cfg = _cfg_with(tmp_path, monkeypatch, mode="observe", allowlist="mastodon")
    with patch(_GET_STATUS, return_value={"status": "unbound"}), \
         patch(_ADAPTER_PUB) as pub:
        publish_with_policy("mastodon", payload={"id": "1"}, config=cfg)

    decisions = [r["decision"] for r in _decisions()]
    assert "would_skip_policy" in decisions
    assert "skipped_policy" not in decisions  # observe never hard-skips
    pub.assert_called()  # observe proceeds to attempt the publish


def test_enforce_channel_outside_allowlist_does_not_hard_skip(tmp_path, monkeypatch):
    """enforce mode but the channel is NOT in the allowlist → behaves like observe
    (would_skip_policy, no hard skip). Proves the allowlist actually gates which
    channels enforce, rather than enforce applying globally."""
    cfg = _cfg_with(tmp_path, monkeypatch, mode="enforce", allowlist="devto")
    with patch(_GET_STATUS, return_value={"status": "unbound"}), \
         patch(_ADAPTER_PUB) as pub:
        publish_with_policy("mastodon", payload={"id": "1"}, config=cfg)

    decisions = [r["decision"] for r in _decisions()]
    assert "skipped_policy" not in decisions, (
        "mastodon outside allowlist must not be hard-skipped under enforce"
    )
    assert "would_skip_policy" in decisions
    pub.assert_called()
