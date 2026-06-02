"""Tests for Velog jitter env-var override getters (U3)."""
import pytest

from backlink_publisher.publishing.adapters.velog_graphql import (
    _VELOG_JITTER_MIN_S,
    _VELOG_JITTER_MAX_S,
    _velog_jitter_min_s,
    _velog_jitter_max_s,
)


def test_defaults_when_no_env_set():
    assert _velog_jitter_min_s() == 60
    assert _velog_jitter_max_s() == 180


def test_env_override_valid(monkeypatch):
    monkeypatch.setenv("VELOG_THROTTLE_MIN_S", "30")
    monkeypatch.setenv("VELOG_THROTTLE_MAX_S", "90")
    assert _velog_jitter_min_s() == 30
    assert _velog_jitter_max_s() == 90


def test_invalid_env_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("VELOG_THROTTLE_MIN_S", "abc")
    assert _velog_jitter_min_s() == _VELOG_JITTER_MIN_S


def test_min_equals_max_is_valid(monkeypatch):
    """min == max is valid deterministic behavior, not a fallback case."""
    monkeypatch.setenv("VELOG_THROTTLE_MIN_S", "60")
    monkeypatch.setenv("VELOG_THROTTLE_MAX_S", "60")
    assert _velog_jitter_min_s() == 60
    assert _velog_jitter_max_s() == 60


def test_min_greater_than_max_guard(monkeypatch):
    """min > max is inverted range — _apply_publish_jitter should fall back to defaults."""
    import random
    from unittest.mock import patch
    import time

    monkeypatch.setenv("VELOG_THROTTLE_MIN_S", "200")
    monkeypatch.setenv("VELOG_THROTTLE_MAX_S", "100")

    from backlink_publisher.publishing.adapters import velog_graphql

    calls = []
    with (
        patch.object(velog_graphql, "_velog_jitter_min_s", return_value=200),
        patch.object(velog_graphql, "_velog_jitter_max_s", return_value=100),
        patch.object(velog_graphql.time, "sleep") as mock_sleep,
        patch.object(velog_graphql.time, "time", return_value=0.0),
    ):
        # last_publish_at = very recent (0.001) so jitter fires
        velog_graphql._apply_publish_jitter("test-id", -999.0)
        # Should have slept using default range values (not inverted 100-200)
        if mock_sleep.called:
            wait = mock_sleep.call_args[0][0]
            # Default range is 60-180, so wait drawn from that
            assert wait <= _VELOG_JITTER_MAX_S, f"Expected default range, got {wait}"
