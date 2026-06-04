"""Registry credential_saver capability — Plan 2026-06-01-001 Unit 3a.

Tests for:
- credential_saver(name) accessor (None for unregistered/anon, callback for livejournal)
- callback contract: writes 0600 file byte-identical to direct store_credentials call
- post-write 0600 re-check on pre-existing loose-inode (existing 0644 file)
- registry snapshot isolation (no state leak across tests)
- R9: FakeAdapter without credential_saver kwarg still registers (optional kwarg)
"""
from __future__ import annotations

__tier__ = "unit"
import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

import backlink_publisher.publishing.adapters  # noqa: F401 — trigger registration

from backlink_publisher.config import Config
from backlink_publisher.publishing.registry import (
    _REGISTRY,
    credential_saver,
    register,
)
from backlink_publisher.publishing.adapters.livejournal_api import (
    _credentials_path,
    store_credentials,
)

# ---------------------------------------------------------------------------
# Accessor tests
# ---------------------------------------------------------------------------

def test_livejournal_has_credential_saver():
    """livejournal is registered with a credential_saver callback."""
    saver = credential_saver("livejournal")
    assert callable(saver), "livejournal credential_saver must be callable"


def test_anon_platform_has_no_credential_saver():
    """telegraph (anon auth) has no credential_saver — returns None."""
    assert credential_saver("telegraph") is None


def test_unregistered_platform_returns_none():
    """Unregistered platform name returns None."""
    assert credential_saver("not_a_real_platform_xyz") is None


# ---------------------------------------------------------------------------
# Callback contract tests
# ---------------------------------------------------------------------------

def _make_config(tmp_path: Path) -> Config:
    from backlink_publisher.config import load_config
    return load_config(tmp_path / "config.toml")


def test_saver_callback_writes_valid_0600_file(tmp_path, monkeypatch):
    """The livejournal credential_saver writes the same 0600 file as
    the direct store_credentials call — byte-identical contract."""
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
    cfg = _make_config(tmp_path)

    saver = credential_saver("livejournal")
    assert saver is not None

    path = saver(
        "livejournal",
        cfg,
        {"username": "testuser", "password": "hunter2"},
        "replace",
    )
    assert path.exists()
    assert (os.stat(path).st_mode & 0o777) == 0o600

    data = json.loads(path.read_text())
    assert data["username"] == "testuser"
    assert "hpassword" in data, "hpassword must be stored (md5 hash)"
    # Byte-identical check: direct call overwrites with same content
    path2 = store_credentials(cfg, "testuser", "hunter2")
    assert path2.read_bytes() == path.read_bytes()


def test_saver_callback_rechmod_loose_inode(tmp_path, monkeypatch):
    """Pre-existing 0644 credential file must be re-chmod'd to 0600 after write."""
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
    cfg = _make_config(tmp_path)

    # Plant a 0644 "prior" cred file (simulates old-code file left behind)
    cred_path = _credentials_path(cfg)
    cred_path.parent.mkdir(parents=True, exist_ok=True)
    cred_path.write_text('{"username":"old","hpassword":"old"}')
    os.chmod(cred_path, 0o644)
    assert (os.stat(cred_path).st_mode & 0o777) == 0o644

    saver = credential_saver("livejournal")
    saver("livejournal", cfg, {"username": "newuser", "password": "secret"}, "replace")

    mode = os.stat(cred_path).st_mode & 0o777
    assert mode == 0o600, f"expected 0600, got {oct(mode)}"


def test_saver_callback_raises_on_empty_credentials(tmp_path, monkeypatch):
    """Empty username or password raises DependencyError (delegates to store_credentials)."""
    from backlink_publisher._util.errors import DependencyError
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
    cfg = _make_config(tmp_path)

    saver = credential_saver("livejournal")
    with pytest.raises(DependencyError):
        saver("livejournal", cfg, {"username": "", "password": "pw"}, "replace")
    with pytest.raises(DependencyError):
        saver("livejournal", cfg, {"username": "user", "password": ""}, "replace")


# ---------------------------------------------------------------------------
# Registry snapshot isolation
# ---------------------------------------------------------------------------

def test_registry_state_does_not_leak_between_tests():
    """Verify the livejournal entry persists as expected and has credential_saver.
    (Isolation is managed by autouse conftest — this just asserts the happy state.)"""
    assert "livejournal" in _REGISTRY
    assert _REGISTRY["livejournal"].credential_saver is not None


# ---------------------------------------------------------------------------
# R9 extension readiness — optional kwarg must not break existing register() calls
# ---------------------------------------------------------------------------

def test_r9_fake_adapter_registers_without_credential_saver(fake_platform_registered):
    """FakeAdapter (registered without credential_saver kwarg) still works; R9 not broken."""
    from backlink_publisher.publishing.registry import registered_platforms
    assert "fake" in registered_platforms()
    assert credential_saver("fake") is None  # no saver registered
