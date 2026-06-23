"""Unit 3 — LITE edition host enforcement matrix (plan 2026-06-04-004).

_resolve_bind_host(): 127.0.0.1/::1/localhost pass; LAN/fe80:: raise RuntimeError.
Route-level: bind blueprint enforces loopback via @bp.before_request so
::1 and localhost pass, 192.168.x.x and fe80:: return 403.
"""
from __future__ import annotations

__tier__ = "unit"

import pytest

from webui_app.helpers.security import _resolve_bind_host


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("BIND_HOST", raising=False)
    monkeypatch.delenv("BACKLINK_PUBLISHER_ALLOW_NETWORK", raising=False)


# ── _resolve_bind_host unit tests ─────────────────────────────────────────────

@pytest.mark.parametrize("host", ["127.0.0.1", "::1", "localhost"])
def test_loopback_hosts_resolve(host, monkeypatch):
    monkeypatch.setenv("BIND_HOST", host)
    assert _resolve_bind_host() == host


@pytest.mark.parametrize("host", ["192.168.1.100", "10.0.0.5", "fe80::1", "fe80::1%eth0"])
def test_non_loopback_raises(host, monkeypatch):
    monkeypatch.setenv("BIND_HOST", host)
    with pytest.raises(RuntimeError, match="loopback"):
        _resolve_bind_host()


@pytest.mark.parametrize("allow", ["0", "1", "true", "yes"])
def test_allow_network_does_not_bypass_non_loopback(monkeypatch, allow):
    """ALLOW_NETWORK=1 does not override the non-loopback refusal."""
    monkeypatch.setenv("BIND_HOST", "192.168.1.100")
    monkeypatch.setenv("BACKLINK_PUBLISHER_ALLOW_NETWORK", allow)
    with pytest.raises(RuntimeError):
        _resolve_bind_host()


def test_fe80_link_local_not_loopback(monkeypatch):
    """fe80:: is link-local, NOT loopback — regression guard."""
    monkeypatch.setenv("BIND_HOST", "fe80::1")
    with pytest.raises(RuntimeError):
        _resolve_bind_host()


# ── route-level enforcement (bind blueprint @bp.before_request) ───────────────

@pytest.fixture
def client(disable_csrf):
    import webui
    return webui.app.test_client()


def test_bind_status_with_loopback_passes_gate(client):
    """Loopback REMOTE_ADDR: bind GET status route passes loopback gate (404 = job not found, not 403)."""
    resp = client.get(
        "/api/v1/settings/channels/medium/bind/nonexistent-job-id",
        environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
    )
    # Loopback passes gate; 404 because job_id unknown (not 403 loopback block)
    assert resp.status_code != 403, "Loopback should not be blocked"


def test_bind_status_with_ipv6_loopback_passes_gate(client):
    """::1 is in _LOOPBACK_HOSTS — route passes gate (404 = job not found, not 403)."""
    resp = client.get(
        "/api/v1/settings/channels/medium/bind/nonexistent-job-id",
        environ_overrides={"REMOTE_ADDR": "::1"},
    )
    assert resp.status_code != 403, "::1 loopback should not be blocked"


def test_bind_status_with_localhost_passes_gate(client):
    """'localhost' is in _LOOPBACK_HOSTS — confirms intentional inclusion."""
    resp = client.get(
        "/api/v1/settings/channels/medium/bind/nonexistent-job-id",
        environ_overrides={"REMOTE_ADDR": "localhost"},
    )
    assert resp.status_code != 403, "'localhost' should not be blocked"


def test_bind_route_with_lan_ip_returns_403(client):
    """LAN IP REMOTE_ADDR blocked by bind blueprint before_request hook."""
    resp = client.get(
        "/api/v1/settings/channels/medium/bind/nonexistent-job-id",
        environ_overrides={"REMOTE_ADDR": "192.168.1.100"},
    )
    assert resp.status_code == 403


def test_bind_route_with_fe80_returns_403(client):
    """fe80:: link-local blocked by bind blueprint before_request — regression guard."""
    resp = client.get(
        "/api/v1/settings/channels/medium/bind/nonexistent-job-id",
        environ_overrides={"REMOTE_ADDR": "fe80::1"},
    )
    assert resp.status_code == 403
