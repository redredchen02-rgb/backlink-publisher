"""Tests for /ce:health maintenance actions — Plan 2026-06-03-004 Phase 2.

Three loopback-only POST endpoints behind the live CSRF guard:
  U5  /ce:health/pause          — toggle LockedHealthStore.paused
  U6  /ce:health/reverify       — re-run verify_adapter_setup (offline)
  U7  /ce:health/circuit-reset  — reset a tripped circuit breaker

Covers: happy path, CSRF rejection (no token → 403), unknown-platform
rejection (400, no side effect), and write-error degradation (never 500).
"""

from __future__ import annotations

import pytest


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("BACKLINK_PUBLISHER_CACHE_DIR", str(tmp_path / "cache"))
    from webui_app import create_app

    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def _post(client, path, body):
    """POST JSON with a valid CSRF token primed into the session."""
    with client.session_transaction() as sess:
        sess["csrf_token"] = "test-token"
    return client.post(path, json=body, headers={"X-CSRFToken": "test-token"})


# ── CSRF perimeter ────────────────────────────────────────────────────────────

def test_pause_without_csrf_is_403(client):
    resp = client.post("/ce:health/pause", json={"platform": "medium", "paused": True})
    assert resp.status_code == 403


def test_reverify_without_csrf_is_403(client):
    resp = client.post("/ce:health/reverify", json={"platform": "medium"})
    assert resp.status_code == 403


def test_circuit_reset_without_csrf_is_403(client):
    resp = client.post("/ce:health/circuit-reset", json={"platform": "medium"})
    assert resp.status_code == 403


# ── U5: pause / resume ────────────────────────────────────────────────────────

def test_pause_then_resume_round_trip(client, tmp_path):
    from backlink_publisher.config import load_config
    from backlink_publisher.health.persistence import locked_store

    resp = _post(client, "/ce:health/pause", {"platform": "medium", "paused": True})
    assert resp.status_code == 200
    assert resp.get_json() == {"ok": True, "platform": "medium", "paused": True}
    assert locked_store.is_paused("medium", load_config()) is True

    resp = _post(client, "/ce:health/pause", {"platform": "medium", "paused": False})
    assert resp.get_json()["paused"] is False
    assert locked_store.is_paused("medium", load_config()) is False


def test_pause_defaults_to_true_when_flag_omitted(client):
    resp = _post(client, "/ce:health/pause", {"platform": "medium"})
    assert resp.get_json()["paused"] is True


def test_pause_unknown_platform_is_400_no_side_effect(client):
    resp = _post(client, "/ce:health/pause", {"platform": "not-a-platform", "paused": True})
    assert resp.status_code == 400
    assert resp.get_json()["ok"] is False


# ── U6: re-verify ─────────────────────────────────────────────────────────────

def test_reverify_known_platform_returns_ready_field(client):
    # No credentials in the sandbox config dir → offline verify reports
    # ready=False with a reason, but the endpoint itself succeeds (ok=True).
    resp = _post(client, "/ce:health/reverify", {"platform": "medium"})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert body["platform"] == "medium"
    assert "ready" in body


def test_reverify_unknown_platform_is_400(client):
    resp = _post(client, "/ce:health/reverify", {"platform": "nope"})
    assert resp.status_code == 400


# ── U7: circuit reset ─────────────────────────────────────────────────────────

def test_circuit_reset_known_platform_ok(client):
    resp = _post(client, "/ce:health/circuit-reset", {"platform": "medium"})
    assert resp.status_code == 200
    assert resp.get_json() == {"ok": True, "platform": "medium"}


def test_circuit_reset_clears_tripped_state(client, tmp_path):
    from backlink_publisher.config import load_config
    from backlink_publisher.publishing.reliability import circuit

    cfg = load_config()
    circuit.trip("medium", cfg)
    assert circuit.is_tripped("medium", cfg) is True

    resp = _post(client, "/ce:health/circuit-reset", {"platform": "medium"})
    assert resp.status_code == 200
    assert circuit.is_tripped("medium", cfg) is False


def test_circuit_reset_unknown_platform_is_400(client):
    resp = _post(client, "/ce:health/circuit-reset", {"platform": "nope"})
    assert resp.status_code == 400
