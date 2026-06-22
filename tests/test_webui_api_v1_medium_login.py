"""Contract + security for the ``/api/v1`` Medium browser-login routes.

Plan 2026-06-18-002 U7 (Settings). The launch/probe/clear dispatch was ported
HTML→JSON via the single-source ``MediumLoginAPI`` facade; the legacy
``/settings/medium/*-browser-login`` routes (flash-redirect + session flag +
redirect sanitization) are covered by ``test_medium_login_routes.py``. This suite
guards the JSON path: the action envelope (``{level, message, logged_in}``) is
returned as-is (NOT problem+json, always HTTP 200), and — because these spawn
browser processes / delete the login profile — the inline transport guards fire
(forged Origin → 403, ALLOW_NETWORK=1 → 403), like the bind routes.

Mock note: the Playwright helpers are patched on the facade module
(``webui_app.api.medium_login_api.*``) — the dispatch moved there.
"""

from __future__ import annotations

__tier__ = "integration"

import sys
import os
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backlink_publisher._util.errors import DependencyError  # noqa: E402

CSRF = "test-csrf-token"
_FACADE = "webui_app.api.medium_login_api"


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


# ── contract (loopback Origin passes the guard) ──────────────────────────────


def test_launch_success_sets_logged_in(client):
    with patch(f"{_FACADE}.launch_login_window", return_value={"logged_in": True}):
        resp = client.post("/api/v1/settings/medium/launch-browser-login", headers=_headers())
    assert resp.status_code == 200, resp.data[:300]
    body = resp.get_json()
    assert body["level"] == "success"
    assert body["logged_in"] is True


def test_probe_logged_in_reports_username(client):
    with patch(f"{_FACADE}.probe_login_status",
               return_value={"logged_in": True, "username": "alice"}):
        resp = client.post("/api/v1/settings/medium/probe-browser-login", headers=_headers())
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["level"] == "info"
    assert body["logged_in"] is True
    assert "@alice" in body["message"]


def test_probe_not_logged_in_clears_flag(client):
    with patch(f"{_FACADE}.probe_login_status", return_value={"logged_in": False}):
        resp = client.post("/api/v1/settings/medium/probe-browser-login", headers=_headers())
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["level"] == "info"
    assert body["logged_in"] is False


def test_clear_success_clears_flag(client):
    with patch(f"{_FACADE}.clear_browser_profile", return_value=None):
        resp = client.post("/api/v1/settings/medium/clear-browser-login", headers=_headers())
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["level"] == "success"
    assert body["logged_in"] is False


def test_launch_dependency_error_is_warning_logged_in_null(client):
    """A missing-Playwright DependencyError is an operational outcome (warning),
    not a transport error — envelope, 200, logged_in unchanged (null)."""
    with patch(f"{_FACADE}.launch_login_window", side_effect=DependencyError("no playwright")):
        resp = client.post("/api/v1/settings/medium/launch-browser-login", headers=_headers())
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["level"] == "warning"
    assert body["logged_in"] is None


# ── security regression (inline guards, like bind) ───────────────────────────


def test_launch_forged_origin_is_403(client):
    """Spawns a browser process — a forged Origin must 403 before the view runs."""
    resp = client.post(
        "/api/v1/settings/medium/launch-browser-login",
        headers={"X-CSRFToken": CSRF, "Origin": "http://evil.example.com"},
    )
    assert resp.status_code == 403


def test_clear_refused_under_allow_network(client, monkeypatch):
    monkeypatch.setenv("BACKLINK_PUBLISHER_ALLOW_NETWORK", "1")
    resp = client.post("/api/v1/settings/medium/clear-browser-login", headers=_headers())
    assert resp.status_code == 403
