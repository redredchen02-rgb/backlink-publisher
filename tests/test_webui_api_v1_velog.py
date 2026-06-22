"""Contract + security for the ``/api/v1`` velog channel routes.

Plan 2026-06-18-002 U7 (Settings section 3 slice 4). The velog-login spawn and its
error_code→message mapping were ported via the single-source ``VelogLoginAPI``
facade; the legacy ``/api/velog/{login,status}`` JSON routes (200/500 status
contract) are covered by ``test_webui_service_routes.py``. This suite guards the
JSON-v1 path: the status read shape, the login envelope (``{ok, message,
error_code, log_path}``, always HTTP 200), and — because login spawns a detached
browser process — the inline transport guards (forged Origin → 403,
ALLOW_NETWORK=1 → 403), like the medium / bind routes.

Mock note: the spawn helper is patched on the SERVICE module
(``webui_app.services.browser_login.spawn_browser_login``) — the facade imports it
lazily, so the patch is honoured (parity with the legacy route's mock surface).
"""

from __future__ import annotations

__tier__ = "integration"

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

CSRF = "test-csrf-token"


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("BACKLINK_PUBLISHER_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.delenv("BACKLINK_PUBLISHER_ALLOW_NETWORK", raising=False)
    from webui_app import create_app
    a = create_app(start_scheduler=False)
    a.config["TESTING"] = True
    a.config["PROPAGATE_EXCEPTIONS"] = False
    a.config["SESSION_COOKIE_SECURE"] = False
    return a


@pytest.fixture
def client(app):
    c = app.test_client()
    with c.session_transaction() as sess:
        sess["csrf_token"] = CSRF
    return c


def _loopback_origin() -> str:
    from webui_app.helpers.security import _FLASK_PORT
    return f"http://127.0.0.1:{_FLASK_PORT}"


def _headers(origin=None):
    return {"X-CSRFToken": CSRF, "Origin": origin or _loopback_origin()}


def _patch_spawn(monkeypatch, *, ok, error=None, log="/tmp/velog.log"):
    from webui_app.services import browser_login as bl
    monkeypatch.setattr(
        bl, "spawn_browser_login",
        lambda module, **kw: bl.SpawnResult(ok=ok, error=error, log_path=log),
    )


# ── status (read-only, no guard) ─────────────────────────────────────────────


def test_status_returns_state_and_quota(client):
    resp = client.get("/api/v1/settings/velog/status")
    assert resp.status_code == 200, resp.data[:300]
    body = resp.get_json()
    assert body["state"] in ("err", "warn", "ok", "fresh", "cap_reached", "permission_denied")
    for key in ("label", "guide", "cookies_path", "count", "cap"):
        assert key in body, f"missing {key}"
    # fresh config → not bound
    assert body["state"] == "err"


def test_status_is_a_read_no_guard_needed(client, monkeypatch):
    monkeypatch.setenv("BACKLINK_PUBLISHER_ALLOW_NETWORK", "1")
    resp = client.get("/api/v1/settings/velog/status",
                      headers={"Origin": "http://evil.example.com"})
    assert resp.status_code == 200


# ── login (spawn envelope, always 200; inline guards) ────────────────────────


def test_login_ok_envelope(client, monkeypatch):
    _patch_spawn(monkeypatch, ok=True, log="/tmp/velog.log")
    resp = client.post("/api/v1/settings/velog/login", headers=_headers())
    assert resp.status_code == 200, resp.data[:300]
    body = resp.get_json()
    assert body["ok"] is True
    assert body["error_code"] is None
    assert body["log_path"] == "/tmp/velog.log"
    assert body["message"]


def test_login_failure_is_200_with_error_code(client, monkeypatch):
    """An early-died subprocess is a successful call reporting a result — the v1
    envelope stays HTTP 200 (unlike the legacy 500), error rides in ``ok``."""
    _patch_spawn(monkeypatch, ok=False,
                 error='{"error_code": "playwright_not_installed"}', log="/tmp/velog.log")
    resp = client.post("/api/v1/settings/velog/login", headers=_headers())
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is False
    assert body["error_code"] == "playwright_not_installed"
    assert "Playwright" in body["message"]


def test_login_forged_origin_is_403(client, monkeypatch):
    """Spawns a browser process — a forged Origin must 403 before the view runs."""
    _patch_spawn(monkeypatch, ok=True)
    resp = client.post(
        "/api/v1/settings/velog/login",
        headers={"X-CSRFToken": CSRF, "Origin": "http://evil.example.com"},
    )
    assert resp.status_code == 403


def test_login_refused_under_allow_network(client, monkeypatch):
    _patch_spawn(monkeypatch, ok=True)
    monkeypatch.setenv("BACKLINK_PUBLISHER_ALLOW_NETWORK", "1")
    resp = client.post("/api/v1/settings/velog/login", headers=_headers())
    assert resp.status_code == 403
