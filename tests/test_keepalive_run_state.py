"""Tests for KeepaliveRunState (plan 2026-06-05-004 Unit 4)."""
from __future__ import annotations

__tier__ = "integration"


import json
import os

import pytest

from backlink_publisher.keepalive.run_state import _default_state, KeepaliveRunState

# ── fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def state_dir(tmp_path):
    return tmp_path


@pytest.fixture
def state(state_dir):
    return KeepaliveRunState(data_dir=state_dir)


# ── load / save ───────────────────────────────────────────────────────────────


def test_load_missing_file_returns_defaults(state):
    data = state.load()
    assert data == _default_state()


def test_load_corrupt_file_returns_defaults(state, state_dir):
    (state_dir / "keepalive_run_state.json").write_text("NOT JSON", encoding="utf-8")
    data = state.load()
    assert data == _default_state()


def test_load_missing_version_returns_defaults(state, state_dir):
    (state_dir / "keepalive_run_state.json").write_text(
        json.dumps({"retry_counts": {}}), encoding="utf-8"
    )
    data = state.load()
    assert data == _default_state()


def test_save_and_load_roundtrip(state):
    data = _default_state()
    data["last_run_at"] = "2026-06-05T05:00:00+00:00"
    state.save(data)
    loaded = state.load()
    assert loaded["last_run_at"] == "2026-06-05T05:00:00+00:00"


# ── is_exhausted ──────────────────────────────────────────────────────────────


def test_is_exhausted_unseen_target(state):
    assert not state.is_exhausted("https://example.com/page")


def test_is_exhausted_below_max(state):
    data = _default_state()
    data["retry_counts"]["https://example.com/page"] = {
        "attempts": 2, "last_attempt_at": None, "platforms_tried": [], "last_outcome": None
    }
    state.save(data)
    assert not state.is_exhausted("https://example.com/page")


def test_is_exhausted_at_max(state):
    data = _default_state()
    data["retry_counts"]["https://example.com/page"] = {
        "attempts": 3, "last_attempt_at": None, "platforms_tried": [], "last_outcome": None
    }
    state.save(data)
    assert state.is_exhausted("https://example.com/page")


def test_is_exhausted_above_max(state):
    data = _default_state()
    data["retry_counts"]["https://example.com/page"] = {
        "attempts": 5, "last_attempt_at": None, "platforms_tried": [], "last_outcome": None
    }
    state.save(data)
    assert state.is_exhausted("https://example.com/page")


# ── record_attempt ────────────────────────────────────────────────────────────


def test_record_attempt_increments_on_reverify_dead(state):
    state.record_attempt("https://example.com/page", "blogger", "reverify_dead")
    data = state.load()
    entry = data["retry_counts"]["https://example.com/page"]
    assert entry["attempts"] == 1
    assert entry["last_outcome"] == "reverify_dead"
    assert "blogger" in entry["platforms_tried"]


def test_record_attempt_increments_on_link_stripped(state):
    state.record_attempt("https://example.com/page", "blogger", "link_stripped")
    data = state.load()
    assert data["retry_counts"]["https://example.com/page"]["attempts"] == 1


def test_record_attempt_increments_on_host_gone(state):
    state.record_attempt("https://example.com/page", "blogger", "host_gone")
    data = state.load()
    assert data["retry_counts"]["https://example.com/page"]["attempts"] == 1


def test_record_attempt_does_not_increment_on_probe_error(state):
    state.record_attempt("https://example.com/page", "blogger", "probe_error")
    data = state.load()
    entry = data["retry_counts"]["https://example.com/page"]
    assert entry["attempts"] == 0
    assert entry["last_outcome"] == "probe_error"


def test_record_attempt_accumulates_platforms(state):
    state.record_attempt("https://example.com/page", "blogger", "reverify_dead")
    state.record_attempt("https://example.com/page", "blogger", "reverify_dead")
    data = state.load()
    # blogger appears only once (deduplicated)
    entry = data["retry_counts"]["https://example.com/page"]
    assert entry["platforms_tried"].count("blogger") == 1
    assert entry["attempts"] == 2


# ── reset_exhausted ───────────────────────────────────────────────────────────


def test_reset_exhausted_removes_entry(state):
    state.record_attempt("https://example.com/page", "blogger", "reverify_dead")
    state.record_attempt("https://example.com/page", "blogger", "reverify_dead")
    state.record_attempt("https://example.com/page", "blogger", "reverify_dead")
    assert state.is_exhausted("https://example.com/page")
    state.reset_exhausted("https://example.com/page")
    assert not state.is_exhausted("https://example.com/page")


def test_reset_exhausted_noop_for_unseen(state):
    state.reset_exhausted("https://nonexistent.example.com/page")
    assert not state.is_exhausted("https://nonexistent.example.com/page")


# ── update_cycle_summary ──────────────────────────────────────────────────────


def test_update_cycle_summary_persists(state):
    summary = {"gaps_found": 3, "published": 2, "reverified_alive": 1}
    state.update_cycle_summary(summary)
    data = state.load()
    assert data["last_cycle_summary"] == summary
    assert data["last_run_at"] is not None


def test_update_cycle_summary_overwrites_previous(state):
    state.update_cycle_summary({"gaps_found": 1})
    state.update_cycle_summary({"gaps_found": 5})
    data = state.load()
    assert data["last_cycle_summary"]["gaps_found"] == 5


# ── MAX_RETRY env override ────────────────────────────────────────────────────


def test_max_retry_env_override(state, monkeypatch):
    monkeypatch.setenv("KEEPALIVE_MAX_RETRY", "5")
    assert state.MAX_RETRY == 5
    data = _default_state()
    data["retry_counts"]["https://example.com/page"] = {
        "attempts": 3, "last_attempt_at": None, "platforms_tried": [], "last_outcome": None
    }
    state.save(data)
    # With MAX_RETRY=5, 3 attempts is NOT exhausted
    assert not state.is_exhausted("https://example.com/page")


def test_max_retry_default_is_3(state):
    assert state.MAX_RETRY == 3
