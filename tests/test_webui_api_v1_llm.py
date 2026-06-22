"""Security regression + contract for ``POST /api/v1/settings/llm-config``.

Plan 2026-06-18-002 U7 (Settings). The LLM settings save was ported HTML→JSON via
the single-source ``LlmSettingsAPI`` facade; the legacy ``/settings/save-llm-config``
route is covered by ``test_webui_llm_settings_save.py``. This suite guards the JSON
path. ``llm-settings.json`` holds the long-term ``api_key`` secret (0600), so it is
on the THREAT-3 surface — the inline transport guards must fire (CSRF-enabled app):

  * forged (non-loopback) Origin → 403, no secret file written
  * ``BACKLINK_PUBLISHER_ALLOW_NETWORK=1`` → 403
  * a successful save writes a 0600 file

plus the contract: non-https endpoint → 422, image-gen validation → 422,
``action:clear`` resets, and a blank api_key preserves the stored secret.
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


def _post(client, body, *, origin=LOOPBACK_ORIGIN):
    return client.post(
        "/api/v1/settings/llm-config",
        json=body,
        headers={"X-CSRFToken": CSRF, "Origin": origin},
    )


def _settings_file(tmp_path):
    return tmp_path / "llm-settings.json"


# ── THREAT-3 transport guards ────────────────────────────────────────────────


def test_llm_save_writes_file_0600(client, tmp_path):
    # Direct literal client.post(...) so the route-coverage meta-test sees it.
    resp = client.post(
        "/api/v1/settings/llm-config",
        json={"endpoint": "https://api.example.com/v1", "api_key": "sk-secret-123", "model": "gpt-4o"},
        headers={"X-CSRFToken": CSRF, "Origin": LOOPBACK_ORIGIN},
    )
    assert resp.status_code == 200, resp.data[:300]
    assert resp.get_json()["ok"] is True
    f = _settings_file(tmp_path)
    assert f.exists()
    if os.name != "nt":
        assert stat.S_IMODE(f.stat().st_mode) == 0o600
    data = json.loads(f.read_text())
    assert data["api_key"] == "sk-secret-123"
    assert data["endpoint"] == "https://api.example.com/v1"


def test_llm_save_forged_origin_is_403(client, tmp_path):
    resp = _post(client, {"endpoint": "https://api.example.com/v1", "api_key": "sk-x"},
                 origin=EVIL_ORIGIN)
    assert resp.status_code == 403
    assert not _settings_file(tmp_path).exists()


def test_llm_save_refused_under_allow_network(client, tmp_path, monkeypatch):
    monkeypatch.setenv("BACKLINK_PUBLISHER_ALLOW_NETWORK", "1")
    resp = _post(client, {"endpoint": "https://api.example.com/v1", "api_key": "sk-x"})
    assert resp.status_code == 403
    assert not _settings_file(tmp_path).exists()


# ── GET hydration (redaction-safe) ───────────────────────────────────────────


def test_llm_config_get_redacts_secrets(client, tmp_path):
    """A saved api_key surfaces as has_api_key=True, never the key itself."""
    client.post(
        "/api/v1/settings/llm-config",
        json={"endpoint": "https://api.example.com/v1", "api_key": "sk-secret-xyz", "model": "gpt-4o"},
        headers={"X-CSRFToken": CSRF, "Origin": LOOPBACK_ORIGIN},
    )
    resp = client.get("/api/v1/settings/llm-config")
    assert resp.status_code == 200, resp.data[:300]
    body = resp.get_json()
    assert body["endpoint"] == "https://api.example.com/v1"
    assert body["model"] == "gpt-4o"
    assert body["has_api_key"] is True
    # the secret is NEVER serialized — not under any key, not anywhere in the body
    assert "api_key" not in body
    assert "sk-secret-xyz" not in resp.get_data(as_text=True)


def test_llm_config_get_empty_when_unset(client):
    resp = client.get("/api/v1/settings/llm-config")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["has_api_key"] is False
    assert body["endpoint"] == ""


# ── contract ─────────────────────────────────────────────────────────────────


def test_llm_save_non_https_endpoint_is_422(client, tmp_path):
    resp = _post(client, {"endpoint": "http://api.example.com/v1", "api_key": "sk-x"})
    assert resp.status_code == 422
    assert resp.headers["Content-Type"].startswith("application/problem+json")
    assert not _settings_file(tmp_path).exists()


def test_llm_save_image_gen_without_fields_is_422(client, tmp_path):
    resp = _post(client, {"use_image_gen": True})
    assert resp.status_code == 422
    assert not _settings_file(tmp_path).exists()


def test_llm_save_clear_resets_to_defaults(client, tmp_path):
    _post(client, {"endpoint": "https://api.example.com/v1", "api_key": "sk-secret-123"})
    assert _settings_file(tmp_path).exists()
    resp = _post(client, {"action": "clear"})
    assert resp.status_code == 200
    data = json.loads(_settings_file(tmp_path).read_text())
    assert data["api_key"] == ""
    assert data["endpoint"] == ""


def test_llm_save_blank_api_key_preserves_stored(client, tmp_path):
    _post(client, {"endpoint": "https://api.example.com/v1", "api_key": "sk-secret-123", "model": "m1"})
    # Second save with a blank api_key but a new model — the secret must survive.
    resp = _post(client, {"endpoint": "https://api.example.com/v1", "api_key": "", "model": "m2"})
    assert resp.status_code == 200
    data = json.loads(_settings_file(tmp_path).read_text())
    assert data["api_key"] == "sk-secret-123"
    assert data["model"] == "m2"
