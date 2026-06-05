"""Unit tests for Hatena AtomPub credential token save (plan 012 Unit 1)."""
from __future__ import annotations

__tier__ = "unit"
import json
import os
import stat

import pytest

from backlink_publisher.config.tokens import _TOKEN_FILES, save_hatena_token


@pytest.fixture
def config_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
    return tmp_path


class TestSaveHatenaToken:
    def test_save_writes_correct_json(self, config_dir):
        save_hatena_token({"hatena_id": "myid", "blog_id": "myid.hatenablog.com", "api_key": "secret"})
        cred_file = config_dir / "hatena-credentials.json"
        assert cred_file.exists()
        data = json.loads(cred_file.read_text())
        assert data["hatena_id"] == "myid"
        assert data["blog_id"] == "myid.hatenablog.com"
        assert data["api_key"] == "secret"

    def test_save_sets_0600_permissions(self, config_dir):
        save_hatena_token({"hatena_id": "u", "blog_id": "u.hatenablog.com", "api_key": "k"})
        cred_file = config_dir / "hatena-credentials.json"
        if os.name != "nt":
            assert stat.S_IMODE(cred_file.stat().st_mode) == 0o600

    def test_special_chars_roundtrip(self, config_dir):
        key = 'abc!@#$%^&*()_+=-[]{}|;\':",./<>?'
        save_hatena_token({"hatena_id": "u", "blog_id": "b", "api_key": key})
        data = json.loads((config_dir / "hatena-credentials.json").read_text())
        assert data["api_key"] == key

    def test_token_files_contains_hatena(self):
        names = {plat for plat, _ in _TOKEN_FILES}
        assert "hatena" in names
        filenames = {fname for _, fname in _TOKEN_FILES}
        assert "hatena-credentials.json" in filenames
