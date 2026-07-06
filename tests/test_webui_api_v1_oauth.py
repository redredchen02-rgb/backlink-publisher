"""Contract for the ``/api/v1`` OAuth credential-management routes.

Plan 2026-06-18-002 U7 (Settings). The two API-appropriate OAuth credential
mutations were ported HTML→JSON via the single-source ``OAuthAPI`` facade; the
legacy ``/settings/{save-blogger-oauth,clear-medium-oauth}`` routes are covered by
``test_webui_routes_oauth.py``. The Blogger oauth-start→callback redirect handshake
is intentionally NOT on ``/api/v1`` (the callback is a browser-navigation landing).

Mock-path note: ``load_config`` / ``save_config`` / ``os`` are module-top imports on
the facade, so they are patched at ``webui_app.api.oauth_api.*`` (the logic moved
there). The config dir for clear-medium is isolated at the source
``backlink_publisher.config._config_dir``.
"""

from __future__ import annotations

__tier__ = "integration"

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

CSRF = "test-csrf-token-fixture"
_STORED_SECRET = "preserved-on-blank-input"


@pytest.fixture(autouse=True)
def _isolated_config_dir(tmp_path):
    fake = tmp_path / "config"
    with patch("backlink_publisher.config._config_dir", return_value=fake):
        yield fake


@pytest.fixture
def app():
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


def _headers():
    return {"X-CSRFToken": CSRF}


# ── save-blogger ─────────────────────────────────────────────────────────────


def test_save_blogger_happy_path(client):
    cfg = MagicMock()
    cfg.blogger_oauth = None
    with patch("webui_app.api.oauth_api.load_config", return_value=cfg), \
            patch("webui_app.api.oauth_api.save_config") as save:
        resp = client.post("/api/v1/settings/blogger-oauth",
                           json={"client_id": "cid-123", "client_secret": "secret-xyz"},
                           headers=_headers())
    assert resp.status_code == 200, resp.data[:300]
    assert resp.get_json()["ok"] is True
    _, kwargs = save.call_args
    assert kwargs["blogger_client_id"] == "cid-123"
    assert kwargs["blogger_client_secret"] == "secret-xyz"


def test_save_blogger_blank_secret_preserves_stored(client):
    cfg = MagicMock()
    cfg.blogger_oauth.client_secret = _STORED_SECRET
    with patch("webui_app.api.oauth_api.load_config", return_value=cfg), \
            patch("webui_app.api.oauth_api.save_config") as save:
        resp = client.post("/api/v1/settings/blogger-oauth",
                           json={"client_id": "cid-123", "client_secret": ""},
                           headers=_headers())
    assert resp.status_code == 200
    _, kwargs = save.call_args
    assert kwargs["blogger_client_secret"] == _STORED_SECRET


def test_save_blogger_missing_creds_is_422(client):
    cfg = MagicMock()
    cfg.blogger_oauth = None
    with patch("webui_app.api.oauth_api.load_config", return_value=cfg), \
            patch("webui_app.api.oauth_api.save_config") as save:
        resp = client.post("/api/v1/settings/blogger-oauth",
                           json={"client_id": "", "client_secret": "secret-xyz"},
                           headers=_headers())
    assert resp.status_code == 422
    assert resp.headers["Content-Type"].startswith("application/problem+json")
    save.assert_not_called()


def test_save_blogger_persistence_failure_is_502(client):
    cfg = MagicMock()
    cfg.blogger_oauth = None
    with patch("webui_app.api.oauth_api.load_config", return_value=cfg), \
            patch("webui_app.api.oauth_api.save_config",
                  side_effect=RuntimeError("disk full")):
        resp = client.post("/api/v1/settings/blogger-oauth",
                           json={"client_id": "cid", "client_secret": "sec"},
                           headers=_headers())
    assert resp.status_code == 502


# ── clear-medium ─────────────────────────────────────────────────────────────


def test_clear_medium_removes_existing_token(client, _isolated_config_dir):
    _isolated_config_dir.mkdir(parents=True, exist_ok=True)
    token_file = _isolated_config_dir / "medium-token.json"
    token_file.write_text("{}")
    resp = client.post("/api/v1/settings/medium-oauth/clear", headers=_headers())
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True
    assert not token_file.exists()


def test_clear_medium_absent_token_still_ok(client, _isolated_config_dir):
    _isolated_config_dir.mkdir(parents=True, exist_ok=True)
    resp = client.post("/api/v1/settings/medium-oauth/clear", headers=_headers())
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True


def test_clear_medium_remove_failure_is_502(client, _isolated_config_dir):
    _isolated_config_dir.mkdir(parents=True, exist_ok=True)
    (_isolated_config_dir / "medium-token.json").write_text("{}")
    with patch("webui_app.api.oauth_api.os.remove", side_effect=OSError("locked")):
        resp = client.post("/api/v1/settings/medium-oauth/clear", headers=_headers())
    assert resp.status_code == 502


# ── blogger status (read-only, no guard) ─────────────────────────────────────


def test_blogger_status_unconfigured(client):
    resp = client.get("/api/v1/settings/blogger/status")
    assert resp.status_code == 200, resp.data[:300]
    body = resp.get_json()
    assert body["authorized"] is False
    assert body["client_secret_set"] is False
    assert body["client_id"] == ""
    assert body["callback_uri"].endswith("/settings/blogger/oauth-callback")


def test_blogger_status_reports_client_without_leaking_secret(client):
    cfg = MagicMock()
    cfg.blogger_oauth.client_id = "cid-public.apps.googleusercontent.com"
    cfg.blogger_oauth.client_secret = "GOCSPX-super-secret-value"
    with patch("webui_app.api.oauth_api.load_config", return_value=cfg), \
            patch("backlink_publisher.config.tokens.load_blogger_token", return_value={"token": "t"}):
        resp = client.get("/api/v1/settings/blogger/status")
    body = resp.get_json()
    assert body["authorized"] is True
    assert body["client_id"] == "cid-public.apps.googleusercontent.com"
    assert body["client_secret_set"] is True
    # the secret VALUE is never returned — only the boolean
    assert "GOCSPX-super-secret-value" not in resp.get_data(as_text=True)


# ── blogger revoke (delete token file) ───────────────────────────────────────


def test_revoke_blogger_deletes_token_file(client, _isolated_config_dir):
    from backlink_publisher.config import load_config
    p = load_config().token_path("blogger")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{}")
    resp = client.post("/api/v1/settings/blogger/revoke", headers=_headers())
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True
    assert not p.exists()


def test_revoke_blogger_absent_token_still_ok(client, _isolated_config_dir):
    resp = client.post("/api/v1/settings/blogger/revoke", headers=_headers())
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True


def test_revoke_blogger_delete_failure_is_502(client):
    cfg = MagicMock()
    cfg.blogger_token_path.unlink.side_effect = OSError("locked")
    with patch("webui_app.api.oauth_api.load_config", return_value=cfg):
        resp = client.post("/api/v1/settings/blogger/revoke", headers=_headers())
    assert resp.status_code == 502
