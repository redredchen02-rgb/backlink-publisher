"""Plan 2026-05-26-002 Unit 3 + 4 — channel credential save route tests.

Covers:
  U3: per-auth-type form partials render in settings.html for cardless channels.
  U4: /settings/save-channel-credential security perimeter and behaviour:
    - CSRF tripwire (follows test_webui_url_verify_routes pattern)
    - Off-loopback rejection
    - Secret-safe error responses (tokens never leak)
    - TOKEN round-trip: save → 0600 file
    - TOKEN+FIELDS: SSRF validation, leave-as-is semantics
    - PASTE-BLOB: schema validation, domain check, round-trip
    - USERPASS: module-dispatch credential hashing (livejournal md5)
    - Clear path: unlinks credential file
"""
from __future__ import annotations

__tier__ = "unit"
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def app(tmp_path):
    from webui_app import create_app
    a = create_app(start_scheduler=False)
    a.config["TESTING"] = True
    a.config["SESSION_COOKIE_SECURE"] = False
    return a


@pytest.fixture
def client(app):
    return app.test_client()


def _seed_csrf(client) -> str:
    """Seed a test CSRF token into the session (same pattern as url_verify)."""
    with client.session_transaction() as sess:
        sess["csrf_token"] = "test-csrf-token"
    return "test-csrf-token"


def _origin_headers() -> dict[str, str]:
    from webui_app.helpers.security import _FLASK_PORT
    return {"Origin": f"http://127.0.0.1:{_FLASK_PORT}"}


def _post(client, data: dict, *, csrf: str | None = None):
    """POST to save-channel-credential with loopback Origin + CSRF token."""
    headers = _origin_headers()
    form_data = dict(data)
    if csrf is not None:
        form_data["csrf_token"] = csrf
    return client.post(
        "/settings/save-channel-credential",
        data=form_data,
        headers=headers,
    )


# ---------------------------------------------------------------------------
# U3 rendering: inline form partials appear in settings.html
# ---------------------------------------------------------------------------


@pytest.fixture
def settings_body(client):
    return client.get("/settings").get_data(as_text=True)


@pytest.mark.parametrize("channel,auth_type", [
    ("livejournal", "userpass"),
    ("tumblr", "token_fields"),
    ("wordpresscom", "token_fields"),
    ("hatena", "token_fields"),
    ("substack", "paste_blob"),
    ("txtfyi", "anon"),
    # writeas removed: retired in plan 008, no longer rendered in settings UI
])
def test_cardless_channel_inline_form_rendered(settings_body, channel, auth_type):
    """Each auth-type partial renders a form block for cardless channels."""
    assert f'id="channel-{channel}"' in settings_body
    if auth_type != "anon":
        assert "/settings/save-channel-credential" in settings_body


def test_anon_channel_no_save_form(settings_body):
    """Anon channels show the ready badge but no credential save form."""
    assert "免绑定 · 就绪" in settings_body
    # anon bind section should not contain a form POST to save-channel-credential
    # (other auth types do, but anon section itself has no <form> element)
    assert 'id="bind-section-txtfyi"' in settings_body


# ---------------------------------------------------------------------------
# U4 security perimeter
# ---------------------------------------------------------------------------


def test_csrf_tripwire_missing_token(client):
    """POST without CSRF token must be rejected with 403."""
    headers = _origin_headers()
    resp = client.post(
        "/settings/save-channel-credential",
        data={"channel": "writeas", "auth_type": "token", "token": "x"},
        headers=headers,
    )
    assert resp.status_code == 403


def test_csrf_tripwire_wrong_token(client):
    """POST with wrong CSRF token is rejected."""
    _seed_csrf(client)
    resp = _post(client, {"channel": "writeas", "auth_type": "token", "token": "x"},
                 csrf="wrong-token")
    assert resp.status_code == 403


def test_off_loopback_rejected(client):
    """POST with non-loopback Origin is rejected with 403."""
    csrf = _seed_csrf(client)
    resp = client.post(
        "/settings/save-channel-credential",
        data={"channel": "writeas", "auth_type": "token", "token": "x",
              "csrf_token": csrf},
        headers={"Origin": "http://evil.com"},
    )
    assert resp.status_code == 403


def test_allow_network_rejected(client, monkeypatch):
    """When BACKLINK_PUBLISHER_ALLOW_NETWORK=1, the route refuses with 403."""
    csrf = _seed_csrf(client)
    monkeypatch.setenv("BACKLINK_PUBLISHER_ALLOW_NETWORK", "1")
    resp = _post(client,
                 {"channel": "writeas", "auth_type": "token", "token": "x"},
                 csrf=csrf)
    assert resp.status_code == 403


def test_unknown_channel_rejected(client):
    """Unregistered channel name returns 302 with danger flash."""
    csrf = _seed_csrf(client)
    resp = _post(client, {"channel": "nosuchplanet", "auth_type": "token",
                          "token": "x"}, csrf=csrf)
    assert resp.status_code == 302
    assert "danger" in resp.headers["Location"]


def test_skip_channel_rejected(client):
    """Channels with dedicated routes (devto/ghpages/notion) are refused."""
    csrf = _seed_csrf(client)
    for channel in ("devto", "ghpages", "notion"):
        resp = _post(client, {"channel": channel, "auth_type": "token",
                               "token": "x"}, csrf=csrf)
        assert resp.status_code == 302
        assert "danger" in resp.headers["Location"]


# ---------------------------------------------------------------------------
# U4 TOKEN — hackmd round-trip (writeas retired in plan 008, tests replaced)
# ---------------------------------------------------------------------------


def test_token_save_creates_0600_file(client, tmp_path, monkeypatch):
    """Saving a hackmd token creates hackmd-token.json with mode 0600."""
    config_dir = tmp_path / "cfg"
    config_dir.mkdir()
    csrf = _seed_csrf(client)
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(config_dir))
    resp = _post(client, {"channel": "hackmd", "auth_type": "token",
                           "token": "MY_SECRET"}, csrf=csrf)
    assert resp.status_code == 302
    assert "success" in resp.headers["Location"]
    token_path = config_dir / "hackmd-token.json"
    assert token_path.exists()
    mode = os.stat(token_path).st_mode & 0o777
    assert mode == 0o600
    data = json.loads(token_path.read_text())
    assert data["token"] == "MY_SECRET"


def test_token_secret_not_leaked_on_error(client):
    """A save failure must not expose the actual token value in the response."""
    csrf = _seed_csrf(client)
    secret = "SUPER_SECRET_TOKEN_12345"
    from unittest.mock import patch
    with patch("backlink_publisher.config.tokens._save_token",
               side_effect=Exception("disk full")):
        resp = _post(client, {"channel": "hackmd", "auth_type": "token",
                               "token": secret}, csrf=csrf)
    assert resp.status_code == 302
    assert secret not in resp.headers.get("Location", "")
    assert secret not in resp.get_data(as_text=True)


def test_token_leave_as_is_empty(client):
    """Empty token field → leave-as-is → info flash, no file written."""
    csrf = _seed_csrf(client)
    resp = _post(client, {"channel": "hackmd", "auth_type": "token",
                           "token": ""}, csrf=csrf)
    assert resp.status_code == 302
    assert "info" in resp.headers["Location"]


def test_token_clear_unlinks_file(client, tmp_path, monkeypatch):
    """Clear removes the token file."""
    config_dir = tmp_path / "cfg"
    config_dir.mkdir()
    token_path = config_dir / "hackmd-token.json"
    token_path.write_text('{"token": "old"}', encoding="utf-8")
    token_path.chmod(0o600)

    csrf = _seed_csrf(client)
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(config_dir))
    resp = _post(client, {"channel": "hackmd", "clear": "1"}, csrf=csrf)
    assert resp.status_code == 302
    assert "success" in resp.headers["Location"]
    assert not token_path.exists()


def test_retired_writeas_token_save_returns_danger(client):
    """writeas retired — save-channel-credential returns danger flash."""
    csrf = _seed_csrf(client)
    resp = _post(client, {"channel": "writeas", "auth_type": "token",
                           "token": "x"}, csrf=csrf)
    assert resp.status_code == 302
    assert "danger" in resp.headers["Location"]


# ---------------------------------------------------------------------------
# U4 TOKEN+FIELDS — wordpresscom SSRF + leave-as-is
# ---------------------------------------------------------------------------


def test_token_fields_ssrf_private_ip_rejected(client):
    """Site URL pointing to private IP must be rejected."""
    csrf = _seed_csrf(client)
    resp = _post(client, {"channel": "wordpresscom", "auth_type": "token_fields",
                           "token": "tok", "site": "https://192.168.1.1/"},
                 csrf=csrf)
    assert resp.status_code == 302
    assert "danger" in resp.headers["Location"]


def test_token_fields_http_site_rejected(client):
    """Site URL with http:// (not https) must be rejected."""
    csrf = _seed_csrf(client)
    resp = _post(client, {"channel": "wordpresscom", "auth_type": "token_fields",
                           "token": "tok", "site": "http://example.wordpress.com"},
                 csrf=csrf)
    assert resp.status_code == 302
    assert "danger" in resp.headers["Location"]


def test_token_fields_leave_as_is_empty_fields(client):
    """Submitting no fields → info flash, no file written."""
    csrf = _seed_csrf(client)
    resp = _post(client, {"channel": "wordpresscom", "auth_type": "token_fields"},
                 csrf=csrf)
    assert resp.status_code == 302
    assert "info" in resp.headers["Location"]


def test_token_fields_round_trip(client, tmp_path, monkeypatch):
    """Save wordpresscom token+site → file exists with both fields."""
    config_dir = tmp_path / "cfg"
    config_dir.mkdir()
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(config_dir))

    csrf = _seed_csrf(client)
    with pytest.MonkeyPatch().context() as mp:
        # Bypass SSRF DNS resolution for test domain. The SSRF gate moved into
        # the facade (Plan 2026-06-18-002 U7), so patch it there — behaviour
        # assertion below (both fields round-trip) is unchanged.
        mp.setattr(
            "webui_app.api.channel_bind_api._check_url_for_ssrf",
            lambda url: None,
        )
        resp = _post(client, {
            "channel": "wordpresscom", "auth_type": "token_fields",
            "token": "MY_WP_TOKEN",
            "site": "https://myblog.wordpress.com",
        }, csrf=csrf)

    assert resp.status_code == 302
    assert "success" in resp.headers["Location"]
    token_path = config_dir / "wordpresscom-token.json"
    assert token_path.exists()
    data = json.loads(token_path.read_text())
    assert data["token"] == "MY_WP_TOKEN"
    assert data["site"] == "https://myblog.wordpress.com"


def test_tumblr_token_fields_round_trip(client, tmp_path, monkeypatch):
    """Save tumblr 5-field credentials → file written with correct content (0600)."""
    config_dir = tmp_path / "cfg"
    config_dir.mkdir()
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(config_dir))

    csrf = _seed_csrf(client)
    resp = _post(client, {
        "channel": "tumblr", "auth_type": "token_fields",
        "consumer_key": "CK123",
        "consumer_secret": "CS!@#$%",
        "oauth_token": "OT456",
        "oauth_token_secret": "OTS&*()",
        "blog_identifier": "myblog.tumblr.com",
    }, csrf=csrf)

    assert resp.status_code == 302
    assert "success" in resp.headers["Location"]
    cred_path = config_dir / "tumblr-credentials.json"
    assert cred_path.exists()
    import os, stat
    if os.name != "nt":
        assert stat.S_IMODE(cred_path.stat().st_mode) == 0o600
    data = json.loads(cred_path.read_text())
    assert data["consumer_key"] == "CK123"
    assert data["consumer_secret"] == "CS!@#$%"
    assert data["oauth_token"] == "OT456"
    assert data["oauth_token_secret"] == "OTS&*()"
    assert data["blog_identifier"] == "myblog.tumblr.com"


def test_tumblr_token_fields_leave_as_is_empty(client):
    """Submitting no tumblr fields → info flash, no file written."""
    csrf = _seed_csrf(client)
    resp = _post(client, {"channel": "tumblr", "auth_type": "token_fields"}, csrf=csrf)
    assert resp.status_code == 302
    assert "info" in resp.headers["Location"]


# ---------------------------------------------------------------------------
# U4 TOKEN+FIELDS — hatena (plan 012)
# ---------------------------------------------------------------------------


def test_hatena_token_fields_round_trip(client, tmp_path, monkeypatch):
    """Save hatena credentials → hatena-credentials.json written with all fields."""
    config_dir = tmp_path / "cfg"
    config_dir.mkdir()
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(config_dir))

    csrf = _seed_csrf(client)
    resp = _post(client, {
        "channel": "hatena", "auth_type": "token_fields",
        "hatena_id": "myid",
        "blog_id": "myid.hatenablog.com",
        "api_key": "supersecret",
    }, csrf=csrf)

    assert resp.status_code == 302
    assert "success" in resp.headers["Location"]
    cred_path = config_dir / "hatena-credentials.json"
    assert cred_path.exists()
    data = json.loads(cred_path.read_text())
    assert data["hatena_id"] == "myid"
    assert data["blog_id"] == "myid.hatenablog.com"
    assert data["api_key"] == "supersecret"


def test_hatena_leave_as_is_partial_fields(client, tmp_path, monkeypatch):
    """Submitting only hatena_id preserves existing blog_id and api_key."""
    config_dir = tmp_path / "cfg"
    config_dir.mkdir()
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(config_dir))

    # Pre-seed the file
    cred_path = config_dir / "hatena-credentials.json"
    cred_path.write_text('{"hatena_id": "old", "blog_id": "old.hatenablog.com", "api_key": "oldkey"}')
    cred_path.chmod(0o600)

    csrf = _seed_csrf(client)
    resp = _post(client, {
        "channel": "hatena", "auth_type": "token_fields",
        "hatena_id": "newid",
        # blog_id and api_key intentionally omitted
    }, csrf=csrf)

    assert resp.status_code == 302
    data = json.loads(cred_path.read_text())
    assert data["hatena_id"] == "newid"
    assert data["blog_id"] == "old.hatenablog.com"
    assert data["api_key"] == "oldkey"


def test_hatena_csrf_required(client):
    """Missing CSRF token → 403."""
    resp = client.post(
        "/settings/save-channel-credential",
        data={"channel": "hatena", "auth_type": "token_fields", "hatena_id": "x"},
        headers=_origin_headers(),
    )
    assert resp.status_code == 403


def test_hatena_non_loopback_origin_rejected(client):
    """Off-loopback Origin → 403."""
    csrf = _seed_csrf(client)
    resp = client.post(
        "/settings/save-channel-credential",
        data={"channel": "hatena", "auth_type": "token_fields",
              "hatena_id": "x", "csrf_token": csrf},
        headers={"Origin": "http://evil.example.com"},
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# U4 TEMPLATE — hatena field rendering (plan 012 Unit 3)
# ---------------------------------------------------------------------------


def test_hatena_template_renders_three_inputs(settings_body):
    """Settings page renders hatena_id, blog_id, api_key inputs for hatena."""
    assert 'name="hatena_id"' in settings_body
    assert 'name="blog_id"' in settings_body
    assert 'name="api_key"' in settings_body


def test_hatena_template_no_warning_box(settings_body):
    """Hatena accordion must not show '字段配置尚未定义' warning."""
    # Locate the hatena section (between channel-hatena open and next channel div)
    # Simplest: just assert the warning key phrase absent (it would only appear
    # if _FIELD_DEFS["hatena"] were missing)
    assert "hatena 的字段配置尚未定义" not in settings_body


def test_hatena_cred_filename_correct(settings_body):
    """Credential file hint shows hatena-credentials.json, not hatena-token.json."""
    assert "hatena-credentials.json" in settings_body
    assert "hatena-token.json" not in settings_body


# ---------------------------------------------------------------------------
# U4 PASTE-BLOB — schema validation + domain check + round-trip
# ---------------------------------------------------------------------------


def test_paste_blob_invalid_json_rejected(client):
    csrf = _seed_csrf(client)
    resp = _post(client, {"channel": "substack", "auth_type": "paste_blob",
                           "blob": "not-json"}, csrf=csrf)
    assert resp.status_code == 302
    assert "danger" in resp.headers["Location"]


def test_paste_blob_missing_cookies_key_rejected(client):
    csrf = _seed_csrf(client)
    resp = _post(client, {"channel": "substack", "auth_type": "paste_blob",
                           "blob": '{"data": []}'}, csrf=csrf)
    assert resp.status_code == 302
    assert "danger" in resp.headers["Location"]


def test_paste_blob_wrong_domain_rejected(client):
    """Cookies from a different domain trigger a domain-mismatch error."""
    csrf = _seed_csrf(client)
    blob = json.dumps({
        "cookies": [
            {"name": "sid", "value": "abc", "domain": ".github.com"},
        ]
    })
    resp = _post(client, {"channel": "substack", "auth_type": "paste_blob",
                           "blob": blob}, csrf=csrf)
    assert resp.status_code == 302
    assert "danger" in resp.headers["Location"]


def test_paste_blob_missing_name_field_rejected(client):
    csrf = _seed_csrf(client)
    blob = json.dumps({
        "cookies": [{"value": "abc", "domain": ".substack.com"}]
    })
    resp = _post(client, {"channel": "substack", "auth_type": "paste_blob",
                           "blob": blob}, csrf=csrf)
    assert resp.status_code == 302
    assert "danger" in resp.headers["Location"]


def test_paste_blob_round_trip(client, tmp_path, monkeypatch):
    """Valid Substack cookie blob saves as 0600 credentials.json."""
    config_dir = tmp_path / "cfg"
    config_dir.mkdir()
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(config_dir))

    csrf = _seed_csrf(client)
    blob = json.dumps({
        "cookies": [
            {"name": "UserName", "value": "testuser", "domain": ".substack.com",
             "path": "/"},
            {"name": "uuid_tt_dd", "value": "token123", "domain": ".substack.com",
             "path": "/"},
        ]
    })
    resp = _post(client, {"channel": "substack", "auth_type": "paste_blob",
                           "blob": blob}, csrf=csrf)
    assert resp.status_code == 302
    assert "success" in resp.headers["Location"]

    import os as _os
    cred_path = config_dir / "substack-credentials.json"
    assert cred_path.exists()
    mode = _os.stat(cred_path).st_mode & 0o777
    assert mode == 0o600
    data = json.loads(cred_path.read_text())
    assert len(data["cookies"]) == 2


def test_paste_blob_size_limit_rejected(client):
    """Cookie blob larger than 100KB is rejected."""
    csrf = _seed_csrf(client)
    big_value = "x" * 110_000
    blob = json.dumps({
        "cookies": [{"name": "k", "value": big_value, "domain": ".substack.com"}]
    })
    resp = _post(client, {"channel": "substack", "auth_type": "paste_blob",
                           "blob": blob}, csrf=csrf)
    assert resp.status_code == 302
    assert "danger" in resp.headers["Location"]


def test_paste_blob_leave_as_is_empty(client):
    """Empty blob → info flash."""
    csrf = _seed_csrf(client)
    resp = _post(client, {"channel": "substack", "auth_type": "paste_blob",
                           "blob": ""}, csrf=csrf)
    assert resp.status_code == 302
    assert "info" in resp.headers["Location"]


# ---------------------------------------------------------------------------
# U4 USERPASS — module dispatch divergence
# ---------------------------------------------------------------------------


def test_userpass_livejournal_stores_md5(client, tmp_path, monkeypatch):
    """livejournal store_credentials hashes the password (md5, not plaintext)."""
    config_dir = tmp_path / "cfg"
    config_dir.mkdir()
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(config_dir))

    csrf = _seed_csrf(client)
    resp = _post(client, {"channel": "livejournal", "auth_type": "userpass",
                           "username": "ljuser", "password": "secret123"},
                 csrf=csrf)
    assert resp.status_code == 302
    assert "success" in resp.headers["Location"]

    cred_path = config_dir / "livejournal-credentials.json"
    assert cred_path.exists()
    import os as _os
    assert _os.stat(cred_path).st_mode & 0o777 == 0o600
    data = json.loads(cred_path.read_text())
    assert data["username"] == "ljuser"
    # hpassword must be md5 — NOT the plaintext password
    import hashlib
    expected_md5 = hashlib.md5(b"secret123").hexdigest()
    assert data["hpassword"] == expected_md5
    assert "secret123" not in json.dumps(data)


def test_userpass_secret_not_leaked_on_error(client):
    """A store_credentials failure must not expose the password in flash."""
    csrf = _seed_csrf(client)
    password = "MY_SECRET_PASSWORD_XYZ"
    from unittest.mock import patch
    with patch(
        "backlink_publisher.publishing.adapters.livejournal_api.store_credentials",
        side_effect=Exception("auth error"),
    ):
        resp = _post(client, {"channel": "livejournal", "auth_type": "userpass",
                               "username": "u", "password": password}, csrf=csrf)
    assert resp.status_code == 302
    assert password not in resp.headers.get("Location", "")


def test_userpass_missing_password_rejected(client):
    """Username without password → danger flash."""
    csrf = _seed_csrf(client)
    resp = _post(client, {"channel": "livejournal", "auth_type": "userpass",
                           "username": "u", "password": ""}, csrf=csrf)
    assert resp.status_code == 302
    assert "danger" in resp.headers["Location"]


def test_userpass_leave_as_is_both_empty(client):
    """Both fields empty → info flash, no write."""
    csrf = _seed_csrf(client)
    resp = _post(client, {"channel": "livejournal", "auth_type": "userpass",
                           "username": "", "password": ""}, csrf=csrf)
    assert resp.status_code == 302
    assert "info" in resp.headers["Location"]


def test_userpass_clear_unlinks_file(client, tmp_path, monkeypatch):
    """Clear unlinks livejournal-credentials.json."""
    config_dir = tmp_path / "cfg"
    config_dir.mkdir()
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(config_dir))
    cred_path = config_dir / "livejournal-credentials.json"
    cred_path.write_text('{"username":"x","hpassword":"y"}', encoding="utf-8")
    cred_path.chmod(0o600)

    csrf = _seed_csrf(client)
    resp = _post(client, {"channel": "livejournal", "clear": "1"}, csrf=csrf)
    assert resp.status_code == 302
    assert "success" in resp.headers["Location"]
    assert not cred_path.exists()


# ---------------------------------------------------------------------------
# U4 ANON — no-op
# ---------------------------------------------------------------------------


def test_dispatch_maps_have_no_dead_rows():
    """Every channel in the credential-service dispatch maps must be registered.

    Guards against re-introducing rows for removed channels
    (jianshu/zhihu/cnblogs/habr/pikabu/segmentfault were swept 2026-05-27).
    Maps live in credential_service after U3b migration.
    """
    import backlink_publisher.publishing.adapters  # noqa: F401 — trigger registration
    from backlink_publisher.publishing.registry import registered_platforms
    from webui_app.services.credential_service import (
        _PASTE_BLOB_CHANNELS,
        _USERPASS_CRED_BASENAMES,
    )

    reg = set(registered_platforms())
    dead = (set(_PASTE_BLOB_CHANNELS) | set(_USERPASS_CRED_BASENAMES)) - reg
    assert dead == set(), f"dead dispatch rows for unregistered channels: {dead}"


def test_anon_save_returns_info(client):
    """Saving an anon channel (telegraph) returns info, no file written."""
    csrf = _seed_csrf(client)
    resp = _post(client, {"channel": "telegraph", "auth_type": "anon"}, csrf=csrf)
    assert resp.status_code == 302
    assert "info" in resp.headers["Location"]


# ---------------------------------------------------------------------------
# blog_id domain-format validation (plan 014)
# ---------------------------------------------------------------------------


def test_hatena_blog_id_valid_hostname_accepted(client, tmp_path, monkeypatch):
    """Valid Hatena blog_id hostname is accepted and credential file is written."""
    config_dir = tmp_path / "cfg"
    config_dir.mkdir()
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(config_dir))
    csrf = _seed_csrf(client)
    resp = _post(client, {
        "channel": "hatena", "auth_type": "token_fields",
        "hatena_id": "testuser",
        "blog_id": "testuser.hatenablog.com",
        "api_key": "abc123",
    }, csrf=csrf)
    assert resp.status_code == 302
    assert "danger" not in resp.headers["Location"]
    assert (config_dir / "hatena-credentials.json").exists()


@pytest.mark.parametrize("bad_blog_id", [
    "../../evil.example.com",
    "192.168.1.1",
    "127.0.0.1",
    "https://blog.example.com",
    "hatena.ne.jp/attack",
    "nodots",
    "user@host.com",
    "../relative",
])
def test_hatena_blog_id_invalid_format_rejected(client, bad_blog_id):
    """Malformed blog_id values must be rejected with a danger flash; no credential written."""
    csrf = _seed_csrf(client)
    resp = _post(client, {
        "channel": "hatena", "auth_type": "token_fields",
        "hatena_id": "u",
        "blog_id": bad_blog_id,
        "api_key": "k",
    }, csrf=csrf)
    assert resp.status_code == 302
    assert "danger" in resp.headers["Location"]


def test_hatena_blog_id_empty_is_leave_as_is(client, tmp_path, monkeypatch):
    """Empty blog_id is skipped (leave-as-is); validation gate is not triggered."""
    config_dir = tmp_path / "cfg"
    config_dir.mkdir()
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(config_dir))
    csrf = _seed_csrf(client)
    resp = _post(client, {
        "channel": "hatena", "auth_type": "token_fields",
        "hatena_id": "u",
        "blog_id": "",
        "api_key": "k",
    }, csrf=csrf)
    assert resp.status_code == 302
    assert "danger" not in resp.headers["Location"]


def test_hatena_blog_id_custom_domain_accepted(client, tmp_path, monkeypatch):
    """Custom-domain blog_id (non-hatenablog.com) must also pass validation."""
    config_dir = tmp_path / "cfg"
    config_dir.mkdir()
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(config_dir))
    csrf = _seed_csrf(client)
    resp = _post(client, {
        "channel": "hatena", "auth_type": "token_fields",
        "hatena_id": "u",
        "blog_id": "myblog.custom-domain.jp",
        "api_key": "k",
    }, csrf=csrf)
    assert resp.status_code == 302
    assert "danger" not in resp.headers["Location"]


def test_blog_id_validation_does_not_affect_other_channels(client, tmp_path, monkeypatch):
    """tumblr's blog_identifier field is not subject to hatena blog_id validation."""
    config_dir = tmp_path / "cfg"
    config_dir.mkdir()
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(config_dir))
    csrf = _seed_csrf(client)
    resp = _post(client, {
        "channel": "tumblr", "auth_type": "token_fields",
        "consumer_key": "ck",
        "consumer_secret": "cs",
        "oauth_token": "ot",
        "oauth_token_secret": "ots",
        "blog_identifier": "yourblog.tumblr.com",
    }, csrf=csrf)
    assert resp.status_code == 302
    assert "danger" not in resp.headers["Location"]
