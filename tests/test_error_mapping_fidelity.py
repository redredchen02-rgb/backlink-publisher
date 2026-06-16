"""Error-mapping fidelity guard for the circuit breaker (Plan 2026-06-15-001 B4).

The circuit breaker trips ONLY on the *typed* exceptions ``ExternalServiceError``
and ``AuthExpiredError`` (policy.py). A non-typed/generic ``Exception`` is routed
to ``Outcome.TRANSIENT`` and re-raised WITHOUT any trip accounting (policy.py
``except Exception`` arm). That is the exact failure mode the reliability review
flagged: if a real 429 / 503 / ban / session-expiry response surfaces from an
adapter as a *generic* exception instead of the typed one, it is INVISIBLE to the
breaker — the channel never trips no matter how many times it fails.

These tests pin that contract so it cannot regress silently:
  * a generic exception, repeated well past the trip threshold, never trips;
  * the typed exception DOES trip at threshold (the mapping that must hold).

The corollary for adapters: real 429/503/ban MUST be raised as
``ExternalServiceError``/``AuthExpiredError``, never a bare ``Exception``.
Capturing the *real* per-platform response shapes needs live credentials and is
deferred to execution (plan §Deferred to Implementation); this guards the
contract the policy layer depends on regardless.

The CLI-seam wiring (``if policy_enabled()`` branch selection through the real
publish loop) is already covered by ``test_reliability_policy_live.py``.
"""
from __future__ import annotations

__tier__ = "unit"

from unittest.mock import patch

import pytest

from backlink_publisher._util.errors import ExternalServiceError
from backlink_publisher.publishing.reliability.events import Outcome
from backlink_publisher.publishing.reliability.policy import publish_with_policy

_GET_STATUS = "webui_store.channel_status.get_status"
_ADAPTER_PUB = "backlink_publisher.publishing.reliability.policy.adapter_publish"
_EMIT = "backlink_publisher.publishing.reliability.policy.emit_attempt"


@pytest.fixture()
def cfg(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("BACKLINK_PUBLISHER_CIRCUIT_COOLDOWN_S", "300")
    monkeypatch.setenv("BACKLINK_PUBLISHER_RELIABILITY_POLICY_ENABLED", "1")

    class _Cfg:
        config_dir = tmp_path

    return _Cfg()


def test_generic_exception_never_trips_circuit(cfg):
    """A non-typed exception is invisible to the breaker — the failure mode to catch.

    Even raised 2x the default error threshold (5), a generic exception must not
    trip: only ExternalServiceError/AuthExpiredError count.
    """
    from backlink_publisher.publishing.reliability.circuit import is_tripped

    # A misleadingly 5xx-looking message must NOT be enough — type is what counts.
    exc = RuntimeError("gateway returned 503 (but as a generic exception)")
    for _ in range(10):  # 2x the default error threshold of 5
        with patch(_GET_STATUS, return_value={"status": "bound"}), \
             patch(_ADAPTER_PUB, side_effect=exc), \
             patch(_EMIT):
            with pytest.raises(RuntimeError):
                publish_with_policy("medium", payload={"id": "1"}, config=cfg)

    assert is_tripped("medium", cfg) is False


def test_generic_exception_routes_to_transient_outcome(cfg):
    """The generic arm emits Outcome.TRANSIENT carrying the real class name."""
    exc = RuntimeError("boom")
    with patch(_GET_STATUS, return_value={"status": "bound"}), \
         patch(_ADAPTER_PUB, side_effect=exc), \
         patch(_EMIT) as mock_emit:
        with pytest.raises(RuntimeError):
            publish_with_policy("medium", payload={"id": "1"}, config=cfg)

    mock_emit.assert_called_once()
    assert mock_emit.call_args[0][1] == Outcome.TRANSIENT
    assert mock_emit.call_args.kwargs.get("error_class") == "RuntimeError"


def test_typed_external_error_does_trip_at_threshold(cfg):
    """Contrast: the typed mapping that MUST hold — 5 consecutive trips the circuit."""
    from backlink_publisher.publishing.reliability.circuit import is_tripped

    exc = ExternalServiceError("rate limited: 429")
    for _ in range(5):  # default error threshold
        with patch(_GET_STATUS, return_value={"status": "bound"}), \
             patch(_ADAPTER_PUB, side_effect=exc), \
             patch(_EMIT):
            with pytest.raises(ExternalServiceError):
                publish_with_policy("medium", payload={"id": "1"}, config=cfg)

    assert is_tripped("medium", cfg) is True


def test_generic_and_typed_are_not_conflated(cfg):
    """A generic exception does not increment the same counter typed errors use."""
    from backlink_publisher.health.persistence import locked_store

    with patch(_GET_STATUS, return_value={"status": "bound"}), \
         patch(_ADAPTER_PUB, side_effect=RuntimeError("x")), \
         patch(_EMIT):
        with pytest.raises(RuntimeError):
            publish_with_policy("medium", payload={"id": "1"}, config=cfg)

    # consecutive_failures stays 0 — the generic arm does no trip accounting.
    entry = locked_store.get("medium", cfg)
    assert int(entry.get("consecutive_failures", 0)) == 0
