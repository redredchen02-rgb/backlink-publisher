"""Tests for env-var override getters in content/fetch.py (Unit 4)."""
from __future__ import annotations

__tier__ = "unit"
import pytest

import backlink_publisher.content.fetch as _fetch


@pytest.mark.parametrize("getter,expected", [
    ("_fetch_timeout", 10),
    ("_max_retries", 2),
    ("_head_scan_bytes", 256_000),
    ("_max_body_bytes", 1_000_000),
    ("_body_too_small_bytes", 2048),
])
def test_defaults_when_env_unset(getter, expected, monkeypatch):
    monkeypatch.delenv("BACKLINK_FETCH_TIMEOUT", raising=False)
    monkeypatch.delenv("BACKLINK_FETCH_MAX_RETRIES", raising=False)
    monkeypatch.delenv("BACKLINK_FETCH_HEAD_SCAN_BYTES", raising=False)
    monkeypatch.delenv("BACKLINK_FETCH_MAX_BODY_BYTES", raising=False)
    monkeypatch.delenv("BACKLINK_FETCH_BODY_TOO_SMALL", raising=False)
    fn = getattr(_fetch, getter)
    assert fn() == expected


def test_fetch_timeout_override(monkeypatch):
    monkeypatch.setenv("BACKLINK_FETCH_TIMEOUT", "15")
    assert _fetch._fetch_timeout() == 15


def test_max_retries_override(monkeypatch):
    monkeypatch.setenv("BACKLINK_FETCH_MAX_RETRIES", "5")
    assert _fetch._max_retries() == 5


def test_max_retries_zero_is_valid(monkeypatch):
    monkeypatch.setenv("BACKLINK_FETCH_MAX_RETRIES", "0")
    assert _fetch._max_retries() == 0


def test_head_scan_bytes_override(monkeypatch):
    monkeypatch.setenv("BACKLINK_FETCH_HEAD_SCAN_BYTES", "512000")
    assert _fetch._head_scan_bytes() == 512_000


def test_max_body_bytes_override(monkeypatch):
    monkeypatch.setenv("BACKLINK_FETCH_MAX_BODY_BYTES", "2000000")
    assert _fetch._max_body_bytes() == 2_000_000


def test_body_too_small_bytes_override(monkeypatch):
    monkeypatch.setenv("BACKLINK_FETCH_BODY_TOO_SMALL", "4096")
    assert _fetch._body_too_small_bytes() == 4096


def test_max_retries_bad_value_falls_back(monkeypatch):
    monkeypatch.setenv("BACKLINK_FETCH_MAX_RETRIES", "abc")
    assert _fetch._max_retries() == 2


def test_fetch_timeout_bad_value_falls_back(monkeypatch):
    monkeypatch.setenv("BACKLINK_FETCH_TIMEOUT", "not_a_number")
    assert _fetch._fetch_timeout() == 10


def test_head_scan_bytes_bad_value_falls_back(monkeypatch):
    monkeypatch.setenv("BACKLINK_FETCH_HEAD_SCAN_BYTES", "big")
    assert _fetch._head_scan_bytes() == 256_000


def test_body_too_small_bad_value_falls_back(monkeypatch):
    monkeypatch.setenv("BACKLINK_FETCH_BODY_TOO_SMALL", "xyz")
    assert _fetch._body_too_small_bytes() == 2048
