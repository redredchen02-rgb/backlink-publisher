"""Unit tests for save_tumblr_token / _TOKEN_FILES integration."""
from __future__ import annotations

__tier__ = "unit"
import json
import os
import stat

import pytest

from backlink_publisher.config.tokens import (
    _TOKEN_FILES,
    save_tumblr_token,
)

_TUMBLR_FIELDS = {
    "consumer_key": "ck_abc",
    "consumer_secret": "cs_xyz!@#",
    "oauth_token": "ot_111",
    "oauth_token_secret": "ots_&*()",
    "blog_identifier": "myblog.tumblr.com",
}


@pytest.fixture
def config_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
    return tmp_path


class TestSaveTumblrToken:
    def test_writes_all_fields(self, config_dir):
        save_tumblr_token(_TUMBLR_FIELDS.copy())
        cred_file = config_dir / "tumblr-credentials.json"
        assert cred_file.exists()
        data = json.loads(cred_file.read_text())
        for key, value in _TUMBLR_FIELDS.items():
            assert data[key] == value

    def test_sets_0600_permissions(self, config_dir):
        save_tumblr_token(_TUMBLR_FIELDS.copy())
        cred_file = config_dir / "tumblr-credentials.json"
        if os.name != "nt":
            assert stat.S_IMODE(cred_file.stat().st_mode) == 0o600

    def test_special_chars_round_trip(self, config_dir):
        """Password fields with special characters survive JSON round-trip."""
        special = {
            "consumer_key": "ck",
            "consumer_secret": 'cs"quoted\nnewline',
            "oauth_token": "ot\ttab",
            "oauth_token_secret": "ots\\backslash",
            "blog_identifier": "blog.tumblr.com",
        }
        save_tumblr_token(special)
        data = json.loads((config_dir / "tumblr-credentials.json").read_text())
        assert data["consumer_secret"] == 'cs"quoted\nnewline'
        assert data["oauth_token"] == "ot\ttab"
        assert data["oauth_token_secret"] == "ots\\backslash"

    def test_token_files_has_tumblr_entry(self):
        """_TOKEN_FILES must include a tumblr entry (drift-check integration)."""
        basenames = {channel: fname for channel, fname in _TOKEN_FILES}
        assert "tumblr" in basenames
        assert basenames["tumblr"] == "tumblr-credentials.json"
