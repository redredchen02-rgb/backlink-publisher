"""Tests for env-var override getters in linkcheck/http.py (Unit 4)."""
from __future__ import annotations

__tier__ = "unit"
import pytest

import backlink_publisher.linkcheck.http as _http


@pytest.mark.parametrize("getter,expected", [
    ("_request_timeout", 10),
    ("_max_concurrent", 10),
    ("_max_retries", 2),
    ("_retry_delay_base_s", 1),
])
def test_defaults_when_env_unset(getter, expected, monkeypatch):
    monkeypatch.delenv("BACKLINK_LINKCHECK_REQUEST_TIMEOUT", raising=False)
    monkeypatch.delenv("BACKLINK_LINKCHECK_MAX_CONCURRENT", raising=False)
    monkeypatch.delenv("BACKLINK_LINKCHECK_MAX_RETRIES", raising=False)
    monkeypatch.delenv("BACKLINK_LINKCHECK_RETRY_DELAY_BASE_S", raising=False)
    fn = getattr(_http, getter)
    assert fn() == expected


def test_request_timeout_override(monkeypatch):
    monkeypatch.setenv("BACKLINK_LINKCHECK_REQUEST_TIMEOUT", "20")
    assert _http._request_timeout() == 20


def test_max_concurrent_override(monkeypatch):
    monkeypatch.setenv("BACKLINK_LINKCHECK_MAX_CONCURRENT", "4")
    assert _http._max_concurrent() == 4


def test_max_retries_override(monkeypatch):
    monkeypatch.setenv("BACKLINK_LINKCHECK_MAX_RETRIES", "5")
    assert _http._max_retries() == 5


def test_retry_delay_base_s_override(monkeypatch):
    monkeypatch.setenv("BACKLINK_LINKCHECK_RETRY_DELAY_BASE_S", "5")
    assert _http._retry_delay_base_s() == 5


def test_max_concurrent_bad_value_falls_back(monkeypatch):
    monkeypatch.setenv("BACKLINK_LINKCHECK_MAX_CONCURRENT", "abc")
    assert _http._max_concurrent() == 10


def test_request_timeout_bad_value_falls_back(monkeypatch):
    monkeypatch.setenv("BACKLINK_LINKCHECK_REQUEST_TIMEOUT", "not_a_number")
    assert _http._request_timeout() == 10


def test_max_retries_bad_value_falls_back(monkeypatch):
    monkeypatch.setenv("BACKLINK_LINKCHECK_MAX_RETRIES", "xyz")
    assert _http._max_retries() == 2


def test_retry_delay_bad_value_falls_back(monkeypatch):
    monkeypatch.setenv("BACKLINK_LINKCHECK_RETRY_DELAY_BASE_S", "1.5")
    assert _http._retry_delay_base_s() == 1
