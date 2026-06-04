"""Tests for LockedHealthStore — Plan 2026-06-03-004 Unit 2."""
from __future__ import annotations

__tier__ = "unit"
import json
import multiprocessing
import os
import time

import pytest

from backlink_publisher.health.persistence import locked_store


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
    from backlink_publisher.config import load_config
    return load_config()


# ── get ───────────────────────────────────────────────────────────────────────

def test_get_returns_safe_defaults_when_file_missing(cfg):
    rec = locked_store.get("medium", cfg)
    assert rec == {"consecutive_failures": 0, "paused": False}


def test_get_returns_safe_defaults_on_corrupt_json(cfg, tmp_path):
    (tmp_path / "platform-health.json").write_text("NOT JSON", encoding="utf-8")
    rec = locked_store.get("medium", cfg)
    assert rec == {"consecutive_failures": 0, "paused": False}


def test_get_returns_saved_values(cfg):
    locked_store.update("medium", lambda e: {"consecutive_failures": 3, "paused": False}, cfg)
    rec = locked_store.get("medium", cfg)
    assert rec["consecutive_failures"] == 3
    assert rec["paused"] is False


def test_get_returns_safe_defaults_for_unknown_platform(cfg):
    locked_store.update("blogger", lambda e: {"consecutive_failures": 1, "paused": False}, cfg)
    rec = locked_store.get("medium", cfg)
    assert rec == {"consecutive_failures": 0, "paused": False}


# ── update ────────────────────────────────────────────────────────────────────

def test_update_round_trip(cfg):
    locked_store.update("velog", lambda e: {**e, "consecutive_failures": 5}, cfg)
    assert locked_store.get("velog", cfg)["consecutive_failures"] == 5


def test_update_preserves_other_platforms(cfg):
    locked_store.update("blogger", lambda e: {"consecutive_failures": 2, "paused": False}, cfg)
    locked_store.update("medium", lambda e: {"consecutive_failures": 7, "paused": True}, cfg)
    assert locked_store.get("blogger", cfg)["consecutive_failures"] == 2
    assert locked_store.get("medium", cfg)["paused"] is True


def test_update_paused_flag(cfg):
    locked_store.update("devto", lambda e: {"consecutive_failures": 0, "paused": True}, cfg)
    assert locked_store.get("devto", cfg)["paused"] is True
    locked_store.update("devto", lambda e: {**e, "paused": False}, cfg)
    assert locked_store.get("devto", cfg)["paused"] is False


# ── set_paused (Phase 2 U5) ────────────────────────────────────────────────────

def test_set_paused_true_then_false(cfg):
    locked_store.set_paused("medium", True, cfg)
    assert locked_store.get("medium", cfg)["paused"] is True
    locked_store.set_paused("medium", False, cfg)
    assert locked_store.get("medium", cfg)["paused"] is False


def test_set_paused_preserves_consecutive_failures(cfg):
    locked_store.update("velog", lambda e: {"consecutive_failures": 3, "paused": False}, cfg)
    locked_store.set_paused("velog", True, cfg)
    rec = locked_store.get("velog", cfg)
    assert rec["paused"] is True
    assert rec["consecutive_failures"] == 3


def test_set_paused_returns_new_state(cfg):
    assert locked_store.set_paused("blogger", True, cfg) is True
    assert locked_store.set_paused("blogger", False, cfg) is False


def test_is_paused_helper(cfg):
    assert locked_store.is_paused("devto", cfg) is False
    locked_store.set_paused("devto", True, cfg)
    assert locked_store.is_paused("devto", cfg) is True


# ── concurrent writes ─────────────────────────────────────────────────────────

def _worker(config_dir: str, platform: str, value: int, result_queue):
    """Subprocess worker: set consecutive_failures to value and report back."""
    os.environ["BACKLINK_PUBLISHER_CONFIG_DIR"] = config_dir
    from backlink_publisher.config import load_config
    from backlink_publisher.health.persistence import locked_store as ls
    cfg = load_config()
    ls.update(platform, lambda e: {"consecutive_failures": value, "paused": False}, cfg)
    result_queue.put(value)


def test_concurrent_writes_no_lost_update(tmp_path):
    """Two processes writing different platforms do not corrupt each other."""
    result_queue = multiprocessing.Queue()
    p1 = multiprocessing.Process(
        target=_worker, args=(str(tmp_path), "medium", 10, result_queue)
    )
    p2 = multiprocessing.Process(
        target=_worker, args=(str(tmp_path), "blogger", 20, result_queue)
    )
    p1.start()
    p2.start()
    p1.join(timeout=10)
    p2.join(timeout=10)

    # Both must complete without error.
    assert p1.exitcode == 0
    assert p2.exitcode == 0

    # Read back both values — neither should be lost.
    os.environ["BACKLINK_PUBLISHER_CONFIG_DIR"] = str(tmp_path)
    from backlink_publisher.config import load_config
    cfg = load_config()
    assert locked_store.get("medium", cfg)["consecutive_failures"] == 10
    assert locked_store.get("blogger", cfg)["consecutive_failures"] == 20
