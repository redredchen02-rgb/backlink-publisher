"""Per-channel enforce allowlist (Plan 2026-06-15-006, Unit 7).

Enforce mode skips ONLY allowlisted channels; everything else falls back to
observe behavior. Ships empty (no channel enforced) → flipping POLICY to enforce
is a no-op until the operator allowlists a channel. Re-read per call (rollback
takes effect next run).
"""
from __future__ import annotations

__tier__ = "unit"

from unittest.mock import patch

import pytest

from backlink_publisher.publishing.adapters.base import AdapterResult
from backlink_publisher.publishing.reliability.circuit import trip
from backlink_publisher.publishing.reliability.policy import (
    enforce_allowlist,
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
    monkeypatch.delenv(ENFORCE_ALLOWLIST_ENV, raising=False)  # default: empty

    class _Cfg:
        config_dir = tmp_path

    return _Cfg()


def _ok():
    return AdapterResult(status="published", adapter="medium-api", platform="medium")


# ── allowlist parsing ────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "raw,expected",
    [
        (None, set()),
        ("", set()),
        ("medium", {"medium"}),
        ("medium,velog", {"medium", "velog"}),
        (" medium , velog ,", {"medium", "velog"}),  # trims + drops empties
    ],
)
def test_enforce_allowlist_parsing(monkeypatch, raw, expected):
    if raw is None:
        monkeypatch.delenv(ENFORCE_ALLOWLIST_ENV, raising=False)
    else:
        monkeypatch.setenv(ENFORCE_ALLOWLIST_ENV, raw)
    assert enforce_allowlist() == frozenset(expected)


# ── enforce gated by allowlist ───────────────────────────────────────────────

def test_enforce_empty_allowlist_does_not_skip(cfg):
    """POLICY=enforce + empty allowlist + tripped circuit → dispatch (no skip)."""
    trip("medium", cfg)
    with patch(_GET_STATUS, return_value={"status": "bound"}), \
         patch(_ADAPTER_PUB, return_value=_ok()) as pub:
        out = publish_with_policy("medium", payload={"id": "1"}, config=cfg)
    pub.assert_called_once()
    assert out.status == "published"  # fell back to observe, dispatched anyway


def test_enforce_allowlisted_channel_skips(cfg, monkeypatch):
    monkeypatch.setenv(ENFORCE_ALLOWLIST_ENV, "medium")
    trip("medium", cfg)
    with patch(_GET_STATUS, return_value={"status": "bound"}), \
         patch(_ADAPTER_PUB) as pub:
        out = publish_with_policy("medium", payload={"id": "1"}, config=cfg)
    pub.assert_not_called()
    assert out.status == "skipped_circuit_open"


def test_enforce_non_allowlisted_falls_back_to_observe(cfg, monkeypatch):
    """A channel NOT in the allowlist behaves as observe even under enforce."""
    monkeypatch.setenv(ENFORCE_ALLOWLIST_ENV, "velog")  # medium not listed
    trip("medium", cfg)
    with patch(_GET_STATUS, return_value={"status": "bound"}), \
         patch(_ADAPTER_PUB, return_value=_ok()) as pub:
        out = publish_with_policy("medium", payload={"id": "1"}, config=cfg)
    pub.assert_called_once()
    assert out.status == "published"


def test_allowlist_rollback_takes_effect_next_call(cfg, monkeypatch):
    """Removing a channel from the allowlist stops enforcing it on the next call."""
    trip("medium", cfg)
    monkeypatch.setenv(ENFORCE_ALLOWLIST_ENV, "medium")
    with patch(_GET_STATUS, return_value={"status": "bound"}), \
         patch(_ADAPTER_PUB, return_value=_ok()):
        out1 = publish_with_policy("medium", payload={"id": "1"}, config=cfg)
    assert out1.status == "skipped_circuit_open"

    monkeypatch.delenv(ENFORCE_ALLOWLIST_ENV, raising=False)  # rollback
    trip("medium", cfg)  # still tripped
    with patch(_GET_STATUS, return_value={"status": "bound"}), \
         patch(_ADAPTER_PUB, return_value=_ok()) as pub:
        out2 = publish_with_policy("medium", payload={"id": "1"}, config=cfg)
    pub.assert_called_once()
    assert out2.status == "published"  # no longer enforced
