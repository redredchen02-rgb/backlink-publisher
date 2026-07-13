"""_save_token writes credential files atomically at 0o600 (audit finding [23]).

The old _save_token did open(path,'w') -> json.dump -> os.chmod(0o600): on POSIX
the file was created at umask perms (0o644) and stayed group/world-readable until
the post-write chmod (a TOCTOU window exposing OAuth tokens / API keys), and the
truncate-in-place write left a corrupt file on a crash mid-write. The fix routes
through persistence.safe_write.atomic_write (mkstemp 0o600 -> replace) and tightens
the parent dir to 0o700, mirroring _util.secrets.write_frw_token.
"""
from __future__ import annotations

__tier__ = "unit"

import os
import sys

import pytest

import backlink_publisher.config.tokens as tokens_mod
from backlink_publisher.config.tokens import _load_token, _save_token


def test_save_token_routes_through_atomic_write_at_0600(tmp_path, monkeypatch):
    seen: dict = {}
    real = tokens_mod.atomic_write

    def _spy(path, text, mode=0o600):
        seen["mode"] = mode
        return real(path, text, mode)

    monkeypatch.setattr(tokens_mod, "atomic_write", _spy)

    token_path = tmp_path / "blogger-token.json"
    _save_token({"api_key": "sk-secret"}, token_path, "blogger-token.json")

    assert seen.get("mode") == 0o600, "token must be written 0o600 via atomic_write"
    loaded = _load_token(token_path, "blogger-token.json")
    assert loaded is not None
    assert loaded["api_key"] == "sk-secret"
    assert loaded["token_rev"] == 1


@pytest.mark.skipif(sys.platform == "win32", reason="Windows doesn't enforce Unix 0600 semantics")
def test_save_token_file_is_0600_and_parent_tightened_to_0700(tmp_path):
    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir(mode=0o755)  # start world-readable, as a fresh config dir would
    token_path = cfg_dir / "medium-token.json"

    _save_token({"integration_token": "x"}, token_path, "medium-token.json")

    assert (os.stat(token_path).st_mode & 0o777) == 0o600
    assert (os.stat(cfg_dir).st_mode & 0o777) == 0o700
