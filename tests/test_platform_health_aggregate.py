"""Tests for build_platform_health — Plan 2026-06-03-004 Unit 1."""

from __future__ import annotations

import json

import pytest

from backlink_publisher.health.aggregate import PlatformHealthRecord, build_platform_health, _redact


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
    from backlink_publisher.config import load_config
    return load_config()


# ── _redact ───────────────────────────────────────────────────────────────────

def test_redact_replaces_long_tokens():
    msg = "Auth failed: token=abcdefghij1234567890xyz extra"
    result = _redact(msg)
    assert "[REDACTED]" in result
    assert "abcdefghij1234567890xyz" not in result


def test_redact_leaves_short_strings():
    assert _redact("short") == "short"


def test_redact_none():
    assert _redact(None) is None


def test_redact_preserves_known_short_identifiers():
    assert _redact("medium blogger velog") == "medium blogger velog"


# ── build_platform_health ─────────────────────────────────────────────────────

def test_returns_empty_dict_on_error(cfg, monkeypatch):
    """build_platform_health never raises — returns {} on top-level failure."""
    def _crash(config):
        raise RuntimeError("simulated crash")

    monkeypatch.setattr("backlink_publisher.health.aggregate._build", _crash)
    result = build_platform_health(cfg)
    assert result == {}


def test_platform_with_no_events_returns_none_timestamps(cfg, monkeypatch):
    """Platform registered but no events yet → all None timestamps, 0 failures."""
    monkeypatch.setattr(
        "backlink_publisher.publishing.registry.registered_platforms",
        lambda: ["medium"],
    )
    monkeypatch.setattr(
        "backlink_publisher.publishing.reliability.circuit.is_tripped",
        lambda platform, config: False,
    )

    result = build_platform_health(cfg)
    assert "medium" in result
    rec = result["medium"]
    assert rec.last_success_at is None
    assert rec.last_failure_at is None
    assert rec.last_error_msg is None
    assert rec.consecutive_failures == 0
    assert rec.circuit_tripped is False


def test_circuit_tripped_propagates(cfg, monkeypatch):
    monkeypatch.setattr(
        "backlink_publisher.publishing.registry.registered_platforms",
        lambda: ["medium"],
    )
    monkeypatch.setattr(
        "backlink_publisher.publishing.reliability.circuit.is_tripped",
        lambda platform, config: True,
    )

    result = build_platform_health(cfg)
    assert result["medium"].circuit_tripped is True


def test_last_error_msg_redacted(cfg, monkeypatch, tmp_path):
    """EventStore error field with token is redacted before returning."""
    from backlink_publisher.events import EventStore

    monkeypatch.setattr(
        "backlink_publisher.publishing.registry.registered_platforms",
        lambda: ["blogger"],
    )
    monkeypatch.setattr(
        "backlink_publisher.publishing.reliability.circuit.is_tripped",
        lambda platform, config: False,
    )

    # Insert a fake failure event with a token in the error field.
    store = EventStore()
    store.append(
        kind="publish.failed",
        payload={
            "platform": "blogger",
            "error": "Auth failed: token=abcdefghij1234567890xyz",
        },
    )

    result = build_platform_health(cfg)
    rec = result.get("blogger")
    if rec and rec.last_error_msg:
        assert "abcdefghij1234567890xyz" not in rec.last_error_msg
        assert "[REDACTED]" in rec.last_error_msg


def test_mutable_state_from_locked_store(cfg, monkeypatch):
    """consecutive_failures and paused come from LockedHealthStore."""
    from backlink_publisher.health.persistence import locked_store

    monkeypatch.setattr(
        "backlink_publisher.publishing.registry.registered_platforms",
        lambda: ["devto"],
    )
    monkeypatch.setattr(
        "backlink_publisher.publishing.reliability.circuit.is_tripped",
        lambda platform, config: False,
    )

    locked_store.update("devto", lambda e: {"consecutive_failures": 4, "paused": True}, cfg)

    result = build_platform_health(cfg)
    rec = result["devto"]
    assert rec.consecutive_failures == 4
    assert rec.paused is True


def test_returns_all_registered_platforms(cfg, monkeypatch):
    platforms = ["medium", "blogger", "velog", "devto"]
    monkeypatch.setattr(
        "backlink_publisher.publishing.registry.registered_platforms",
        lambda: platforms,
    )
    monkeypatch.setattr(
        "backlink_publisher.publishing.reliability.circuit.is_tripped",
        lambda platform, config: False,
    )

    result = build_platform_health(cfg)
    assert set(result.keys()) == set(platforms)


def test_tripped_non_browser_platform_surfaces_with_timestamp(cfg, monkeypatch):
    """Phase 3 U12: a real tripped non-browser circuit surfaces in the aggregate,
    with circuit_tripped_at populated from the real state file (regression: the
    aggregate previously read the wrong key and always returned None)."""
    from backlink_publisher.publishing.reliability import circuit

    monkeypatch.setattr(
        "backlink_publisher.publishing.registry.registered_platforms",
        lambda: ["blogger"],
    )
    circuit.trip("blogger", cfg)  # real trip, real state file

    rec = build_platform_health(cfg)["blogger"]
    assert rec.circuit_tripped is True
    assert rec.circuit_tripped_at is not None  # timestamp read from tripped_at_iso
