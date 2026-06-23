"""Contract for ``GET /api/v1/settings/channels/forms`` — the per-channel binding
form schemas the SPA settings page renders credential forms from.

Plan 2026-06-18-002 U7 (Settings, section 3 slice 2 — binding forms). Static
metadata via ``ChannelFormsAPI``; the credential WRITE it pairs with
(``…/<channel>/credential``) is covered in test_webui_api_v1_channel_bind.py. This
guards: the read shape, that field NAMES stay single-sourced against the save path,
that no secret VALUE is ever emitted, and that only fixed-credential channels appear
(oauth / browser-login / skip channels excluded).
"""

from __future__ import annotations

__tier__ = "integration"

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("BACKLINK_PUBLISHER_CACHE_DIR", str(tmp_path / "cache"))
    from webui_app import create_app
    a = create_app(start_scheduler=False)
    a.config["TESTING"] = True
    a.config["PROPAGATE_EXCEPTIONS"] = False
    a.config["SESSION_COOKIE_SECURE"] = False
    return a


@pytest.fixture
def client(app):
    return app.test_client()


def _forms(client) -> list[dict]:
    resp = client.get("/api/v1/settings/channels/forms")
    assert resp.status_code == 200, resp.data[:300]
    body = resp.get_json()
    assert isinstance(body.get("forms"), list)
    return body["forms"]


def test_forms_returns_fixed_credential_channels(client):
    forms = _forms(client)
    by_slug = {f["slug"]: f for f in forms}
    # one of each fixed-credential auth type is present
    assert "wordpresscom" in by_slug and by_slug["wordpresscom"]["auth_type"] == "token_fields"
    assert "hackmd" in by_slug and by_slug["hackmd"]["auth_type"] == "token"
    assert "substack" in by_slug and by_slug["substack"]["auth_type"] == "paste_blob"
    assert "livejournal" in by_slug and by_slug["livejournal"]["auth_type"] == "userpass"
    for f in forms:
        assert f["fields"], f"{f['slug']} has no fields"
        assert f["supports_clear"] is True
        assert f["display_name"]


def test_field_names_match_credential_service_single_source(client):
    """The SPA must render exactly the fields the save path persists: field NAMES
    come from credential_service (the dispatch maps), never duplicated here."""
    from webui_app.services import credential_service

    for f in _forms(client):
        names = [fld["name"] for fld in f["fields"]]
        if f["auth_type"] == "token_fields":
            assert names == credential_service.token_field_names(f["slug"]), f["slug"]
        elif f["auth_type"] == "token":
            assert names == ["token"]
        elif f["auth_type"] == "userpass":
            assert names == ["username", "password"]
        elif f["auth_type"] == "paste_blob":
            assert names == ["blob"]


def test_token_form_is_a_single_secret_field(client):
    by_slug = {f["slug"]: f for f in _forms(client)}
    fld = by_slug["hackmd"]["fields"]
    assert len(fld) == 1
    assert fld[0]["name"] == "token"
    assert fld[0]["secret"] is True and fld[0]["type"] == "password"


def test_userpass_form_has_text_user_and_secret_password(client):
    by_slug = {f["slug"]: f for f in _forms(client)}
    fld = {x["name"]: x for x in by_slug["livejournal"]["fields"]}
    assert fld["username"]["secret"] is False and fld["username"]["type"] == "text"
    assert fld["password"]["secret"] is True and fld["password"]["type"] == "password"


def test_paste_blob_form_is_a_textarea(client):
    by_slug = {f["slug"]: f for f in _forms(client)}
    fld = by_slug["substack"]["fields"]
    assert len(fld) == 1 and fld[0]["name"] == "blob"
    assert fld[0]["type"] == "textarea" and fld[0]["secret"] is False


def test_oauth_browser_and_dedicated_card_channels_are_absent(client):
    """blogger(oauth), medium/velog/mastodon(live_browser) get card actions, not a
    generic form; notion has its own two-field NotionCard; anon channels need no
    credentials. (devto/ghpages ARE present now — folded in via save_via="token".)"""
    slugs = {f["slug"] for f in _forms(client)}
    for absent in ("blogger", "medium", "velog", "mastodon", "notion",
                   "telegraph", "txtfyi", "rentry", "notesio"):
        assert absent not in slugs, f"{absent} must not have a generic binding form"


def test_token_paste_channels_folded_in_with_save_via_token(client):
    """devto / ghpages — single-token paste channels ChannelBindAPI skips — are folded
    into the workbench (U8), persisting via the dedicated /channels/<ch>/token route."""
    by_slug = {f["slug"]: f for f in _forms(client)}
    for slug in ("devto", "ghpages"):
        assert slug in by_slug, f"{slug} should be folded into the binding workbench"
        assert by_slug[slug]["save_via"] == "token"
        assert [x["name"] for x in by_slug[slug]["fields"]] == ["token"]


def test_generic_channels_save_via_credential(client):
    """Channels ChannelBindAPI dispatches keep save_via='credential' (unchanged)."""
    by_slug = {f["slug"]: f for f in _forms(client)}
    assert by_slug["hackmd"]["save_via"] == "credential"
    assert by_slug["wordpresscom"]["save_via"] == "credential"


def test_forms_carry_no_secret_values(client):
    """A field is pure presentation metadata — it must never carry a stored value."""
    allowed = {"name", "label", "type", "placeholder", "help", "secret"}
    for f in _forms(client):
        # top-level row keys are status-free / secret-free
        assert "value" not in f and "identity" not in f and "bound" not in f
        for fld in f["fields"]:
            assert set(fld) <= allowed, f"{f['slug']} field has unexpected keys: {set(fld) - allowed}"
            assert "value" not in fld
