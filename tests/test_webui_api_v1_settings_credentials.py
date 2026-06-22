"""Security regression for ``/api/v1/settings/*`` credential writes — Plan 2026-06-18-002 U7.

THREAT-3 gate: when the token-paste credential writes were ported HTML→JSON, the
per-route transport guards must NOT be silently dropped. This suite runs a
CSRF-ENABLED app (so the inline guards fire — they are gated on CSRF config, like
``bind.py``) and asserts, at the transport layer:

  * a forged (non-loopback) Origin → 403  (DNS-rebinding guard intact)
  * ``BACKLINK_PUBLISHER_ALLOW_NETWORK=1`` → 403  (loopback-only refusal intact)
  * the written secret file is still ``0600``  (atomic-write mode intact)

plus the functional contract (unknown channel → 422, clear removes the file).
A loopback Origin + valid CSRF is the happy path.
"""

from __future__ import annotations

__tier__ = "integration"

import json
import os
import stat

import pytest

from webui_app import create_app
from webui_app.helpers.security import _FLASK_PORT

LOOPBACK_ORIGIN = f"http://127.0.0.1:{_FLASK_PORT}"
EVIL_ORIGIN = "http://evil.example.com"
CSRF = "test-csrf-token"


@pytest.fixture
def app(tmp_path, monkeypatch):
    # Isolated config/cache dirs so credential writes land in tmp, and a
    # CSRF-ENABLED app so the inline transport guards are exercised.
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


def _post(client, path, body, *, origin=LOOPBACK_ORIGIN):
    return client.post(
        path, json=body,
        headers={"X-CSRFToken": CSRF, "Origin": origin},
    )


# ── transport guards (the THREAT-3 assertions) ──────────────────────────────


def test_webui_save_channel_token_writes_file_0600(client, tmp_path):
    # Direct literal client.post(...) so the route-coverage meta-test sees it.
    resp = client.post(
        "/api/v1/settings/channels/ghpages/token",
        json={"token": "ghp_abc123def456"},
        headers={"X-CSRFToken": CSRF, "Origin": LOOPBACK_ORIGIN},
    )
    assert resp.status_code == 200, resp.data[:300]
    assert resp.get_json()["ok"] is True
    token_file = tmp_path / "ghpages-token.json"
    assert token_file.exists()
    if os.name != "nt":
        assert stat.S_IMODE(token_file.stat().st_mode) == 0o600
    assert json.loads(token_file.read_text())["token"] == "ghp_abc123def456"


def test_webui_save_channel_token_forged_origin_is_403(client, tmp_path):
    resp = _post(
        client, "/api/v1/settings/channels/ghpages/token",
        {"token": "ghp_abc123def456"}, origin=EVIL_ORIGIN,
    )
    assert resp.status_code == 403
    # Guard fired BEFORE any write — no secret file created.
    assert not (tmp_path / "ghpages-token.json").exists()


def test_webui_save_channel_token_refused_under_allow_network(client, tmp_path, monkeypatch):
    monkeypatch.setenv("BACKLINK_PUBLISHER_ALLOW_NETWORK", "1")
    resp = _post(client, "/api/v1/settings/channels/ghpages/token", {"token": "ghp_abc123def456"})
    assert resp.status_code == 403
    assert not (tmp_path / "ghpages-token.json").exists()


def test_webui_notion_token_writes_file_0600(client, tmp_path):
    # Direct literal client.post(...) so the route-coverage meta-test sees it.
    resp = client.post(
        "/api/v1/settings/notion-token",
        json={"integration_token": "secret_abc", "database_id": "db_123"},
        headers={"X-CSRFToken": CSRF, "Origin": LOOPBACK_ORIGIN},
    )
    assert resp.status_code == 200, resp.data[:300]
    notion_file = tmp_path / "notion-token.json"
    assert notion_file.exists()
    if os.name != "nt":
        assert stat.S_IMODE(notion_file.stat().st_mode) == 0o600


def test_webui_notion_token_forged_origin_is_403(client, tmp_path):
    resp = _post(
        client, "/api/v1/settings/notion-token",
        {"integration_token": "secret_abc", "database_id": "db_123"}, origin=EVIL_ORIGIN,
    )
    assert resp.status_code == 403
    assert not (tmp_path / "notion-token.json").exists()


# ── functional contract ─────────────────────────────────────────────────────


def test_webui_save_channel_token_unknown_channel_is_422(client):
    resp = _post(client, "/api/v1/settings/channels/wpcom/token", {"token": "x"})
    assert resp.status_code == 422
    assert resp.headers["Content-Type"].startswith("application/problem+json")


def test_webui_save_channel_token_empty_is_noop_200(client, tmp_path):
    resp = _post(client, "/api/v1/settings/channels/ghpages/token", {"token": ""})
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is False
    assert not (tmp_path / "ghpages-token.json").exists()


def test_webui_save_channel_token_clear_removes_file(client, tmp_path):
    _post(client, "/api/v1/settings/channels/ghpages/token", {"token": "ghp_abc123def456"})
    assert (tmp_path / "ghpages-token.json").exists()
    resp = _post(client, "/api/v1/settings/channels/ghpages/token", {"clear": True})
    assert resp.status_code == 200
    assert resp.get_json()["cleared"] is True
    assert not (tmp_path / "ghpages-token.json").exists()


def test_webui_notion_token_missing_database_id_is_422(client):
    resp = _post(client, "/api/v1/settings/notion-token", {"integration_token": "secret_abc"})
    assert resp.status_code == 422
