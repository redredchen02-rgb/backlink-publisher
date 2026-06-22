"""Read-side contract for ``GET /api/v1/settings/notion/status`` — Plan 2026-06-18-002 U8.

The Notion credential WRITE (``POST /api/v1/settings/notion-token``) was migrated in
the U7 security core; this status GET is the hydration the SPA NotionCard reads. It
must surface only ``configured`` (bool) + the non-secret ``database_id`` — the
integration_token must NEVER appear in the response (the redaction invariant the
other status GETs hold).
"""

from __future__ import annotations

__tier__ = "integration"

import pytest

from webui_app import create_app
from webui_app.helpers.security import _FLASK_PORT

LOOPBACK_ORIGIN = f"http://127.0.0.1:{_FLASK_PORT}"
CSRF = "test-csrf-token"


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("BACKLINK_PUBLISHER_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.delenv("BACKLINK_PUBLISHER_ALLOW_NETWORK", raising=False)
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


def _save(client, body):
    return client.post(
        "/api/v1/settings/notion-token", json=body,
        headers={"X-CSRFToken": CSRF, "Origin": LOOPBACK_ORIGIN},
    )


def test_notion_status_unconfigured_when_no_token(client):
    # Direct literal client.get(...) so the route-coverage meta-test sees it.
    resp = client.get("/api/v1/settings/notion/status")
    assert resp.status_code == 200, resp.data[:300]
    body = resp.get_json()
    assert body == {"configured": False, "database_id": ""}


def test_notion_status_configured_after_save(client):
    assert _save(client, {"integration_token": "secret_abc", "database_id": "db_123"}).status_code == 200
    body = client.get("/api/v1/settings/notion/status").get_json()
    assert body["configured"] is True
    assert body["database_id"] == "db_123"  # non-secret, echoed for display


def test_notion_status_never_leaks_integration_token(client):
    _save(client, {"integration_token": "super-secret-xyz", "database_id": "db_123"})
    resp = client.get("/api/v1/settings/notion/status")
    assert "super-secret-xyz" not in resp.get_data(as_text=True)
    assert "integration_token" not in resp.get_json()


def test_notion_status_is_get_no_guard(client):
    # Read-only, no secret leaves the box → no Origin/CSRF needed (no inline guard).
    resp = client.get("/api/v1/settings/notion/status")
    assert resp.status_code == 200
