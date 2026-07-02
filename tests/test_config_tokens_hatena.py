"""Unit tests for Hatena AtomPub credential token save (plan 012 Unit 1)."""
from __future__ import annotations

__tier__ = "unit"
import json
import os
import stat

import pytest

from backlink_publisher.config.tokens import (
    _TOKEN_FILES,
    load_hatena_token,
    save_hatena_token,
)

_CRED = {"hatena_id": "testuser", "blog_id": "testuser.hatenablog.com", "api_key": "abc123"}


@pytest.fixture
def config_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
    return tmp_path


class TestHatenaToken:
    def test_save_writes_correct_fields(self, config_dir):
        save_hatena_token(_CRED)
        cred_file = config_dir / "hatena-credentials.json"
        assert cred_file.exists()
        data = json.loads(cred_file.read_text())
        assert data["hatena_id"] == "testuser"
        assert data["blog_id"] == "testuser.hatenablog.com"
        assert data["api_key"] == "abc123"

    def test_save_sets_0600_permissions(self, config_dir):
        save_hatena_token(_CRED)
        cred_file = config_dir / "hatena-credentials.json"
        if os.name != "nt":
            assert stat.S_IMODE(cred_file.stat().st_mode) == 0o600

    def test_special_chars_roundtrip(self, config_dir):
        key = 'abc!@#$%^&*()_+=-[]{}|;\':",./<>?'
        save_hatena_token({"hatena_id": "u", "blog_id": "b", "api_key": key})
        data = json.loads((config_dir / "hatena-credentials.json").read_text())
        assert data["api_key"] == key

    def test_load_roundtrip(self, config_dir):
        save_hatena_token(_CRED)
        loaded = load_hatena_token()
        assert loaded is not None
        assert loaded["hatena_id"] == "testuser"
        assert loaded["blog_id"] == "testuser.hatenablog.com"
        assert loaded["api_key"] == "abc123"

    def test_load_returns_none_when_missing(self, config_dir):
        assert load_hatena_token() is None

    def test_load_returns_none_on_invalid_utf8_instead_of_raising(self, config_dir):
        """Code-review finding, 2026-07-02: a token file with invalid UTF-8
        bytes must degrade to None like any other corrupt file, not raise
        UnicodeDecodeError past the caller.
        """
        cred_file = config_dir / "hatena-credentials.json"
        cred_file.write_bytes(b"\xff\xfe\x00not valid utf-8")
        assert load_hatena_token() is None

    def test_token_files_includes_hatena(self):
        platforms = {p for p, _ in _TOKEN_FILES}
        assert "hatena" in platforms
        filenames = {f for _, f in _TOKEN_FILES}
        assert "hatena-credentials.json" in filenames


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
    from backlink_publisher.config import load_config
    return load_config()


class TestHatenaDispatch:
    def test_dispatch_entry_exists(self):
        from webui_app.services.credential_service import _TOKEN_FIELDS_DISPATCH
        assert "hatena" in _TOKEN_FIELDS_DISPATCH
        _, basename, fields = _TOKEN_FIELDS_DISPATCH["hatena"]
        assert basename == "hatena-credentials.json"
        assert set(fields) == {"hatena_id", "blog_id", "api_key"}

    def test_save_token_fields_roundtrip(self, cfg, tmp_path, monkeypatch):
        from webui_app.services.credential_service import save_token_fields
        path = save_token_fields(
            "hatena", cfg,
            {"hatena_id": "u1", "blog_id": "u1.hatenablog.com", "api_key": "k1"},
        )
        assert path == cfg.config_dir / "hatena-credentials.json"
        data = json.loads(path.read_text())
        assert data["hatena_id"] == "u1"
        assert data["api_key"] == "k1"

    def test_save_token_fields_leave_as_is_semantics(self, cfg, tmp_path, monkeypatch):
        from webui_app.services.credential_service import save_token_fields
        save_token_fields("hatena", cfg, {"hatena_id": "orig", "blog_id": "orig.blog.com", "api_key": "origkey"})
        save_token_fields("hatena", cfg, {"hatena_id": "updated", "blog_id": "orig.blog.com", "api_key": "origkey"})
        data = json.loads((cfg.config_dir / "hatena-credentials.json").read_text())
        assert data["hatena_id"] == "updated"
        assert data["blog_id"] == "orig.blog.com"
        assert data["api_key"] == "origkey"
