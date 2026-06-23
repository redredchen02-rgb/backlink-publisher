"""Security regression + contract for ``POST /api/v1/settings/channels/<ch>/credential``.

Plan 2026-06-18-002 U7 (Settings). The general registry-dispatched credential
write was ported HTML→JSON by extracting a single-source facade
(``ChannelBindAPI``); the legacy ``/settings/save-channel-credential`` route is
covered by ``test_channel_bind_save.py``. This suite guards the JSON path:

THREAT-3 transport gate (CSRF-enabled app so the inline guards fire):
  * forged (non-loopback) Origin → 403, no secret file written
  * ``BACKLINK_PUBLISHER_ALLOW_NETWORK=1`` → 403
  * a successful save writes a ``0600`` file

plus the dispatch contract for every auth type (token / token_fields /
paste_blob / userpass / anon), unknown/skip channel → 422, SSRF + domain
validations still reject, clear removes the file, and a save failure never
echoes the secret.
"""

from __future__ import annotations

__tier__ = "integration"

import hashlib
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
    # Isolated config dir (writes land in tmp) + CSRF-ENABLED so the inline
    # transport guards are exercised, exactly like the credential-core suite.
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


def _post(client, channel, body, *, origin=LOOPBACK_ORIGIN):
    return client.post(
        f"/api/v1/settings/channels/{channel}/credential",
        json=body,
        headers={"X-CSRFToken": CSRF, "Origin": origin},
    )


# ── THREAT-3 transport guards ────────────────────────────────────────────────


def test_credential_save_writes_file_0600(client, tmp_path):
    # Direct literal client.post(...) so the route-coverage meta-test sees it.
    resp = client.post(
        "/api/v1/settings/channels/hackmd/credential",
        json={"auth_type": "token", "token": "MY_SECRET"},
        headers={"X-CSRFToken": CSRF, "Origin": LOOPBACK_ORIGIN},
    )
    assert resp.status_code == 200, resp.data[:300]
    assert resp.get_json()["ok"] is True
    token_file = tmp_path / "hackmd-token.json"
    assert token_file.exists()
    if os.name != "nt":
        assert stat.S_IMODE(token_file.stat().st_mode) == 0o600
    assert json.loads(token_file.read_text())["token"] == "MY_SECRET"


def test_credential_save_forged_origin_is_403(client, tmp_path):
    resp = _post(client, "hackmd", {"auth_type": "token", "token": "MY_SECRET"},
                 origin=EVIL_ORIGIN)
    assert resp.status_code == 403
    # Guard fired BEFORE any write.
    assert not (tmp_path / "hackmd-token.json").exists()


def test_credential_save_refused_under_allow_network(client, tmp_path, monkeypatch):
    monkeypatch.setenv("BACKLINK_PUBLISHER_ALLOW_NETWORK", "1")
    resp = _post(client, "hackmd", {"auth_type": "token", "token": "MY_SECRET"})
    assert resp.status_code == 403
    assert not (tmp_path / "hackmd-token.json").exists()


# ── dispatch contract: each auth type ────────────────────────────────────────


def test_token_fields_round_trip(client, tmp_path):
    resp = _post(client, "tumblr", {
        "auth_type": "token_fields",
        "consumer_key": "CK123", "consumer_secret": "CS!@#",
        "oauth_token": "OT456", "oauth_token_secret": "OTS&*(",
        "blog_identifier": "myblog.tumblr.com",
    })
    assert resp.status_code == 200, resp.data[:300]
    assert resp.get_json()["ok"] is True
    cred = tmp_path / "tumblr-credentials.json"
    assert cred.exists()
    if os.name != "nt":
        assert stat.S_IMODE(cred.stat().st_mode) == 0o600
    assert json.loads(cred.read_text())["consumer_key"] == "CK123"


def test_token_fields_ssrf_private_ip_rejected(client, tmp_path):
    resp = _post(client, "wordpresscom", {
        "auth_type": "token_fields", "token": "tok",
        "site": "https://192.168.1.1/",
    })
    assert resp.status_code == 422
    assert resp.headers["Content-Type"].startswith("application/problem+json")
    assert not (tmp_path / "wordpresscom-token.json").exists()


def test_token_fields_http_site_rejected(client):
    resp = _post(client, "wordpresscom", {
        "auth_type": "token_fields", "token": "tok",
        "site": "http://example.wordpress.com",
    })
    assert resp.status_code == 422


def test_paste_blob_round_trip(client, tmp_path):
    blob = json.dumps({"cookies": [
        {"name": "UserName", "value": "u", "domain": ".substack.com", "path": "/"},
    ]})
    resp = _post(client, "substack", {"auth_type": "paste_blob", "blob": blob})
    assert resp.status_code == 200, resp.data[:300]
    cred = tmp_path / "substack-credentials.json"
    assert cred.exists()
    if os.name != "nt":
        assert stat.S_IMODE(cred.stat().st_mode) == 0o600


def test_paste_blob_accepts_object_blob(client, tmp_path):
    # JSON clients may send the cookie blob as a nested object, not a string.
    resp = _post(client, "substack", {"auth_type": "paste_blob", "blob": {
        "cookies": [{"name": "sid", "value": "v", "domain": ".substack.com"}],
    }})
    assert resp.status_code == 200, resp.data[:300]
    assert (tmp_path / "substack-credentials.json").exists()


def test_paste_blob_wrong_domain_rejected(client):
    blob = json.dumps({"cookies": [
        {"name": "sid", "value": "abc", "domain": ".github.com"},
    ]})
    resp = _post(client, "substack", {"auth_type": "paste_blob", "blob": blob})
    assert resp.status_code == 422


def test_userpass_stores_md5(client, tmp_path):
    resp = _post(client, "livejournal", {
        "auth_type": "userpass", "username": "ljuser", "password": "secret123",
    })
    assert resp.status_code == 200, resp.data[:300]
    cred = tmp_path / "livejournal-credentials.json"
    assert cred.exists()
    data = json.loads(cred.read_text())
    assert data["hpassword"] == hashlib.md5(b"secret123").hexdigest()
    assert "secret123" not in json.dumps(data)


def test_userpass_missing_password_rejected(client):
    resp = _post(client, "livejournal", {
        "auth_type": "userpass", "username": "u", "password": "",
    })
    assert resp.status_code == 422


def test_anon_is_noop_ok_false(client):
    resp = _post(client, "telegraph", {"auth_type": "anon"})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is False  # nothing written


# ── functional contract: channel / clear / leave-as-is ───────────────────────


def test_unknown_channel_is_422(client):
    resp = _post(client, "nosuchplanet", {"auth_type": "token", "token": "x"})
    assert resp.status_code == 422
    assert resp.headers["Content-Type"].startswith("application/problem+json")


def test_skip_channel_is_422(client):
    # devto/ghpages/notion keep dedicated routes — the general endpoint refuses.
    resp = _post(client, "devto", {"auth_type": "token", "token": "x"})
    assert resp.status_code == 422


def test_auth_type_mismatch_is_422(client):
    resp = _post(client, "hackmd", {"auth_type": "userpass", "username": "u", "password": "p"})
    assert resp.status_code == 422


def test_empty_token_is_leave_as_is_200(client, tmp_path):
    resp = _post(client, "hackmd", {"auth_type": "token", "token": ""})
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is False
    assert not (tmp_path / "hackmd-token.json").exists()


def test_clear_removes_file(client, tmp_path):
    _post(client, "hackmd", {"auth_type": "token", "token": "MY_SECRET"})
    assert (tmp_path / "hackmd-token.json").exists()
    resp = _post(client, "hackmd", {"clear": True})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert body["cleared"] is True
    assert not (tmp_path / "hackmd-token.json").exists()


def test_save_failure_does_not_leak_secret(client):
    secret = "SUPER_SECRET_TOKEN_12345"
    from unittest.mock import patch
    with patch("backlink_publisher.config.tokens._save_token",
               side_effect=Exception("disk full")):
        resp = _post(client, "hackmd", {"auth_type": "token", "token": secret})
    assert resp.status_code == 502
    assert secret not in resp.get_data(as_text=True)
