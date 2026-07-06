"""Persist reliability.decision events into events.db (Plan 2026-06-15-006, Unit 2).

Asserts the DB ROW is written (not just that emit was called) — the triple-gap
learning: readiness (Unit 4) reads the DB, so a test that only checks emission
would miss a broken writeback.
"""
from __future__ import annotations

__tier__ = "unit"

import json
from unittest.mock import patch

import pytest

from backlink_publisher.events import EventStore
from backlink_publisher.events.kinds import RELIABILITY_DECISION
from backlink_publisher.publishing.adapters.base import AdapterResult
from backlink_publisher.publishing.reliability.events_store import (
    append_reliability_decision,
    DECISIONS,
)
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


def _ok():
    return AdapterResult(status="published", adapter="medium-api", platform="medium")


def _decision_rows():
    """All reliability.decision payloads currently in the default events.db."""
    rows = EventStore().query(
        "SELECT payload_json FROM events WHERE kind = ?", (RELIABILITY_DECISION,)
    )
    return [json.loads(r["payload_json"]) for r in rows]


# ── helper: validation + persistence ─────────────────────────────────────────

def test_helper_persists_valid_decision(tmp_path):
    store = EventStore(path=tmp_path / "e.db")
    rid = append_reliability_decision(
        store, platform="medium", decision="would_skip_policy", mode="observe"
    )
    assert rid >= 0
    rows = store.query(
        "SELECT payload_json FROM events WHERE kind = ?", (RELIABILITY_DECISION,)
    )
    payload = json.loads(rows[0]["payload_json"])
    assert payload["platform"] == "medium"
    assert payload["decision"] == "would_skip_policy"
    assert payload["mode"] == "observe"


def test_helper_quarantines_unknown_decision(tmp_path):
    store = EventStore(path=tmp_path / "e.db")
    rid = append_reliability_decision(
        store, platform="medium", decision="typo_skip", mode="observe"
    )
    assert rid == -1
    # No event row written...
    rows = store.query(
        "SELECT COUNT(*) AS n FROM events WHERE kind = ?", (RELIABILITY_DECISION,)
    )
    assert rows[0]["n"] == 0
    # ...but a quarantine row IS, so the typo surfaces in triage.
    q = store.query("SELECT COUNT(*) AS n FROM quarantine_log", ())
    assert q[0]["n"] == 1


def test_decision_vocabulary_is_closed():
    assert DECISIONS == {
        "would_skip_policy",
        "would_skip_circuit",
        "skipped_policy",
        "skipped_circuit_open",
        "degraded",
        "circuit_state_unreadable",
    }


# ── policy wiring: observe writes would_skip_* rows ──────────────────────────

def test_observe_unbound_persists_would_skip_policy(cfg):
    with patch(_GET_STATUS, return_value={"status": "unbound"}), \
         patch(_ADAPTER_PUB, return_value=_ok()):
        publish_with_policy("medium", payload={"id": "1"}, config=cfg)

    rows = _decision_rows()
    assert len(rows) == 1
    assert rows[0]["decision"] == "would_skip_policy"
    assert rows[0]["mode"] == "observe"
    assert rows[0]["platform"] == "medium"


def test_observe_tripped_persists_would_skip_circuit(cfg):
    from backlink_publisher.publishing.reliability.circuit import trip
    trip("medium", cfg)

    with patch(_GET_STATUS, return_value={"status": "bound"}), \
         patch(_ADAPTER_PUB, return_value=_ok()):
        publish_with_policy("medium", payload={"id": "1"}, config=cfg)

    rows = _decision_rows()
    assert [r["decision"] for r in rows] == ["would_skip_circuit"]
    assert rows[0]["mode"] == "observe"


def test_observe_bound_healthy_persists_nothing(cfg):
    with patch(_GET_STATUS, return_value={"status": "bound"}), \
         patch(_ADAPTER_PUB, return_value=_ok()):
        publish_with_policy("medium", payload={"id": "1"}, config=cfg)
    assert _decision_rows() == []


# ── policy wiring: enforce writes skipped_* rows ─────────────────────────────

def test_enforce_tripped_persists_skipped_circuit_open(cfg, monkeypatch):
    monkeypatch.setenv(POLICY_ENV, "enforce")
    monkeypatch.setenv("BACKLINK_PUBLISHER_RELIABILITY_ENFORCE_CHANNELS", "medium")
    from backlink_publisher.publishing.reliability.circuit import trip
    trip("medium", cfg)

    with patch(_GET_STATUS, return_value={"status": "bound"}), \
         patch(_ADAPTER_PUB) as pub:
        out = publish_with_policy("medium", payload={"id": "1"}, config=cfg)

    pub.assert_not_called()
    assert out.status == "skipped_circuit_open"
    rows = _decision_rows()
    assert [r["decision"] for r in rows] == ["skipped_circuit_open"]
    assert rows[0]["mode"] == "enforce"


def test_enforce_unbound_persists_skipped_policy(cfg, monkeypatch):
    monkeypatch.setenv(POLICY_ENV, "enforce")
    monkeypatch.setenv("BACKLINK_PUBLISHER_RELIABILITY_ENFORCE_CHANNELS", "medium")
    with patch(_GET_STATUS, return_value={"status": "unbound"}), \
         patch(_ADAPTER_PUB) as pub:
        out = publish_with_policy("medium", payload={"id": "1"}, config=cfg)

    pub.assert_not_called()
    assert out.status == "skipped_policy"
    rows = _decision_rows()
    assert [r["decision"] for r in rows] == ["skipped_policy"]
    assert rows[0]["mode"] == "enforce"


# ── off mode: no rows ────────────────────────────────────────────────────────

def test_off_persists_nothing(cfg, monkeypatch):
    monkeypatch.setenv(POLICY_ENV, "0")
    with patch(_GET_STATUS), patch(_ADAPTER_PUB, return_value=_ok()):
        publish_with_policy("medium", payload={"id": "1"}, config=cfg)
    assert _decision_rows() == []


# ── never-raises: events.db fault must not break a publish ────────────────────

def test_record_decision_swallows_eventstore_errors(cfg):
    """A broken events.db write must not propagate into the publish path."""
    boom = "backlink_publisher.events.store.EventStore"
    with patch(_GET_STATUS, return_value={"status": "unbound"}), \
         patch(_ADAPTER_PUB, return_value=_ok()) as pub, \
         patch(boom, side_effect=RuntimeError("db gone")):
        out = publish_with_policy("medium", payload={"id": "1"}, config=cfg)
    # Publish still succeeded despite the events.db fault.
    pub.assert_called_once()
    assert out.status == "published"
