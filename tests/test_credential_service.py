"""Unit tests for webui_app.services.credential_service — Plan 2026-06-01-001 U3b.

Flask-free: all tests bypass the app and call the service directly.
Covers: save/clear for each auth_type, field-merge semantics, 0600 mode,
ChannelNotConfigured on unknown channel.
"""
from __future__ import annotations

__tier__ = "unit"
import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

import backlink_publisher.publishing.adapters  # noqa: F401 — trigger registration
from webui_app.services import credential_service
from webui_app.services.credential_service import (
    ChannelNotConfigured,
    CorruptCredentialFile,
)


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    """Return a minimal Config-like object pointing at a tmp config dir."""
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
    from backlink_publisher.config import load_config
    return load_config()


# ── dispatch map shape ────────────────────────────────────────────────────────


def test_token_dispatch_contains_expected_channels():
    # writeas retired in plan 008; hackmd/mataroa/qiita added as token channels
    assert "writeas" not in credential_service._TOKEN_DISPATCH
    assert "devto" in credential_service._TOKEN_DISPATCH
    assert "hackmd" in credential_service._TOKEN_DISPATCH
    assert "mataroa" in credential_service._TOKEN_DISPATCH
    assert "qiita" in credential_service._TOKEN_DISPATCH


def test_token_fields_dispatch_contains_expected_channels():
    assert "wordpresscom" in credential_service._TOKEN_FIELDS_DISPATCH
    assert "ghpages" in credential_service._TOKEN_FIELDS_DISPATCH


def test_paste_blob_dispatch_contains_expected_channels():
    assert "substack" in credential_service._PASTE_BLOB_CHANNELS


def test_userpass_cred_basenames_contains_livejournal():
    assert "livejournal" in credential_service._USERPASS_CRED_BASENAMES


# ── save_token ────────────────────────────────────────────────────────────────


def test_save_token_writes_0600_file(cfg, tmp_path):
    # writeas retired in plan 008; hackmd is representative token channel
    path = credential_service.save_token("hackmd", cfg, "MY_HACKMD_TOKEN")
    assert path.exists()
    assert os.stat(path).st_mode & 0o777 == 0o600
    data = json.loads(path.read_text())
    assert data["token"] == "MY_HACKMD_TOKEN"


def test_save_token_devto_uses_api_key_field(cfg, tmp_path):
    path = credential_service.save_token("devto", cfg, "DEVTO_KEY")
    data = json.loads(path.read_text())
    assert "api_key" in data
    assert data["api_key"] == "DEVTO_KEY"


def test_save_token_unknown_channel_raises(cfg):
    with pytest.raises(ChannelNotConfigured):
        credential_service.save_token("nosuchclient", cfg, "tok")


# ── save_token_fields ─────────────────────────────────────────────────────────


def test_save_token_fields_writes_file(cfg, tmp_path):
    path = credential_service.save_token_fields(
        "wordpresscom", cfg, {"token": "TOK", "site": "https://x.wordpress.com"}
    )
    assert path.exists()
    data = json.loads(path.read_text())
    assert data["token"] == "TOK"
    assert data["site"] == "https://x.wordpress.com"


def test_save_token_fields_partial_submit_preserves_existing(cfg, tmp_path):
    """Critical U3b semantic: partial submit must NOT clear unsubmitted fields."""
    # First write both fields
    credential_service.save_token_fields(
        "wordpresscom", cfg, {"token": "INITIAL_TOK", "site": "https://wp.example.com"}
    )
    # Second write: only token; site must survive
    credential_service.save_token_fields("wordpresscom", cfg, {"token": "NEW_TOK"})
    path = cfg.config_dir / "wordpresscom-token.json"
    data = json.loads(path.read_text())
    assert data["token"] == "NEW_TOK"
    assert data["site"] == "https://wp.example.com", "partial submit must not erase site"


def test_save_token_fields_corrupt_existing_raises(cfg, tmp_path):
    """BF2: corrupt existing file raises CorruptCredentialFile (fail-loud)."""
    p = cfg.config_dir / "wordpresscom-token.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("NOT JSON!!!", encoding="utf-8")
    with pytest.raises(CorruptCredentialFile, match="无法解析为 JSON"):
        credential_service.save_token_fields("wordpresscom", cfg, {"token": "T"})


def test_save_token_fields_corrupt_does_not_overwrite(cfg, tmp_path):
    """BF2: corrupt file is never silently overwritten with new fields."""
    p = cfg.config_dir / "wordpresscom-token.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    original_bad = "CORRUPT"
    p.write_text(original_bad, encoding="utf-8")
    try:
        credential_service.save_token_fields("wordpresscom", cfg, {"token": "T"})
    except CorruptCredentialFile:
        pass
    assert p.read_text(encoding="utf-8") == original_bad


def test_save_token_fields_unknown_channel_raises(cfg):
    with pytest.raises(ChannelNotConfigured):
        credential_service.save_token_fields("ghostcms", cfg, {"token": "x"})


def test_token_field_names_returns_field_list():
    assert credential_service.token_field_names("wordpresscom") == ["token", "site"]


def test_token_field_names_ghpages_single_field():
    assert credential_service.token_field_names("ghpages") == ["token"]


def test_token_field_names_gitlabpages_single_field():
    assert credential_service.token_field_names("gitlabpages") == ["token"]


def test_save_token_fields_gitlabpages_writes_file(cfg, tmp_path):
    """GitLab Pages binding (active, dofollow='uncertain', canary-pending) is
    now WebUI-bindable: save writes the single-token gitlabpages-token.json."""
    path = credential_service.save_token_fields(
        "gitlabpages", cfg, {"token": "glpat-XXXX"}
    )
    assert path.name == "gitlabpages-token.json"
    assert path.exists()
    data = json.loads(path.read_text())
    assert data["token"] == "glpat-XXXX"


def test_token_field_names_unknown_returns_none():
    assert credential_service.token_field_names("ghostcms") is None


# ── save_paste_blob ───────────────────────────────────────────────────────────


def test_save_paste_blob_writes_0600_file(cfg, tmp_path):
    blob = {"cookies": [{"name": "a", "value": "b", "domain": ".substack.com"}]}
    path = credential_service.save_paste_blob("substack", cfg, blob)
    assert path.exists()
    assert os.stat(path).st_mode & 0o777 == 0o600
    data = json.loads(path.read_text())
    assert data["cookies"][0]["name"] == "a"


def test_save_paste_blob_unknown_channel_raises(cfg):
    with pytest.raises(ChannelNotConfigured):
        credential_service.save_paste_blob("fakechan", cfg, {})


# ── save_userpass ─────────────────────────────────────────────────────────────


def test_save_userpass_livejournal_writes_hpassword(cfg, tmp_path):
    path = credential_service.save_userpass("livejournal", cfg, "user1", "pass1")
    assert path.exists()
    assert os.stat(path).st_mode & 0o777 == 0o600
    data = json.loads(path.read_text())
    assert data["username"] == "user1"
    assert "hpassword" in data
    assert data["hpassword"] != "pass1"  # md5-hashed, not plaintext


def test_save_userpass_unknown_channel_raises(cfg):
    with pytest.raises(ChannelNotConfigured):
        credential_service.save_userpass("notregistered_up", cfg, "u", "p")


# ── clear_credential ──────────────────────────────────────────────────────────


def test_clear_token_returns_true_when_file_exists(cfg, tmp_path):
    credential_service.save_token("hackmd", cfg, "tok")
    assert credential_service.clear_credential("hackmd", "token", cfg) is True
    assert not (cfg.config_dir / "hackmd-token.json").exists()


def test_clear_token_returns_false_when_file_missing(cfg):
    assert credential_service.clear_credential("hackmd", "token", cfg) is False


def test_clear_token_fields_returns_true(cfg, tmp_path):
    credential_service.save_token_fields("wordpresscom", cfg, {"token": "t"})
    assert credential_service.clear_credential("wordpresscom", "token_fields", cfg) is True


def test_clear_paste_blob_returns_true(cfg, tmp_path):
    blob = {"cookies": [{"name": "a", "value": "b", "domain": ".substack.com"}]}
    credential_service.save_paste_blob("substack", cfg, blob)
    assert credential_service.clear_credential("substack", "paste_blob", cfg) is True


def test_clear_userpass_returns_true(cfg, tmp_path):
    credential_service.save_userpass("livejournal", cfg, "u", "p")
    assert credential_service.clear_credential("livejournal", "userpass", cfg) is True


def test_clear_unknown_channel_raises(cfg):
    with pytest.raises(ChannelNotConfigured):
        credential_service.clear_credential("ghostcms", "token", cfg)


def test_clear_unknown_auth_type_raises(cfg):
    with pytest.raises(ChannelNotConfigured):
        credential_service.clear_credential("hackmd", "weirdtype", cfg)


# ── paste_blob_expected_domain ────────────────────────────────────────────────


def test_paste_blob_expected_domain_substack():
    assert credential_service.paste_blob_expected_domain("substack") == "substack.com"


def test_paste_blob_expected_domain_unknown_returns_none():
    assert credential_service.paste_blob_expected_domain("fakechan") is None
