"""Tests for the verify_health store — Plan 2026-06-05-008 Unit 1.

Per-platform credential-expiry verdict cache: only token_expired/ok mutate
state; transient verdicts are no-ops.
"""


from __future__ import annotations
__tier__ = "integration"

from pathlib import Path

import pytest

from webui_store.base import Store
from webui_store.sqlite_base import WebUIDatabase
from webui_store.verify_health import (
    expired_channels,
    list_all,
    record,
    VerifyHealthSqliteStore,
)


def _store(tmp_path: Path) -> VerifyHealthSqliteStore:
    return VerifyHealthSqliteStore(WebUIDatabase(tmp_path / "webui.db"))


class TestStoreProtocol:
    def test_isinstance_store(self, tmp_path):
        assert isinstance(_store(tmp_path), Store)

    def test_load_empty_when_absent(self, tmp_path):
        assert _store(tmp_path).load() == {}

    def test_save_load_roundtrip(self, tmp_path):
        store = _store(tmp_path)
        store.save({"devto": {"result": "token_expired", "at": "2026-06-05T00:00:00+00:00"}})
        assert store.load() == {
            "devto": {"result": "token_expired", "at": "2026-06-05T00:00:00+00:00"}
        }

    def test_save_drops_resultless_rows(self, tmp_path):
        store = _store(tmp_path)
        store.save({"x": {"at": "t"}, "y": {}})  # no result → dropped
        assert store.load() == {}


class TestRecordSemantics:
    @pytest.fixture(autouse=True)
    def _isolated_store(self, tmp_path, monkeypatch):
        """Each test gets its own config dir → fresh webui.db, so the
        module-level singleton functions don't share state across tests.
        """
        monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
        from webui_store import _refresh_paths
        _refresh_paths()

    def test_token_expired_sets(self):
        record("devto", "token_expired")
        assert "devto" in expired_channels()

    def test_ok_clears(self):
        record("devto", "token_expired")
        assert "devto" in expired_channels()
        record("devto", "ok")
        assert "devto" not in expired_channels()
        assert expired_channels() == frozenset()

    def test_timeout_is_noop_on_clean(self):
        record("devto", "timeout")
        assert expired_channels() == frozenset()

    def test_timeout_does_not_clear_existing_expiry(self):
        record("devto", "token_expired")
        record("devto", "timeout")  # transient must not clear
        assert "devto" in expired_channels()

    def test_never_and_unverifiable_are_noops(self):
        record("devto", "token_expired")
        record("devto", "never")
        record("devto", "unverifiable_live")
        assert "devto" in expired_channels()  # unchanged

    def test_idempotent_expired(self):
        record("devto", "token_expired")
        record("devto", "token_expired")
        assert expired_channels() == frozenset({"devto"})
        assert len(list_all()) == 1

    def test_independent_channels(self):
        record("devto", "token_expired")
        record("notion", "token_expired")
        record("notion", "ok")
        assert expired_channels() == frozenset({"devto"})

    def test_unknown_channel_not_expired(self):
        assert "mystery" not in expired_channels()


class TestRefreshPathsResetsVerifyHealthCache:
    """A1: verify_health_store used to be silently excluded from
    _refresh_paths()'s reset tuple. These assertions observe the real effect
    of the fix (cache actually cleared / config-dir change actually takes
    effect) rather than merely "calling _refresh_paths() doesn't raise".
    """

    def test_refresh_paths_clears_cached_instance(self, tmp_path, monkeypatch):
        # White-box: directly observe the _LazyStore's cached instance being
        # discarded by _refresh_paths() itself, without relying on
        # BACKLINK_PUBLISHER_CONFIG_DIR changing (which _LazyStore._real()
        # would separately guard against on its own) — isolates the effect
        # of verify_health_store's membership in the reset tuple specifically.
        from webui_store import _refresh_paths
        from webui_store.verify_health import verify_health_store

        monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
        verify_health_store.load()  # force instantiation
        assert verify_health_store._instance is not None  # sanity precondition

        _refresh_paths()

        assert verify_health_store._instance is None, (
            "_refresh_paths() did not clear verify_health_store's cached "
            "instance — verify_health_store is missing from the "
            "_refresh_paths() reset tuple in webui_store/__init__.py"
        )

    def test_refresh_paths_repoints_store_to_new_config_dir(self, tmp_path, monkeypatch):
        # Black-box: after a config-dir change + _refresh_paths(), the store
        # actually resolves under the *new* directory on next access.
        from webui_store import _refresh_paths
        from webui_store.verify_health import verify_health_store

        dir_a = tmp_path / "a"
        dir_b = tmp_path / "b"
        dir_a.mkdir()
        dir_b.mkdir()

        monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(dir_a))
        _refresh_paths()
        verify_health_store.load()
        assert Path(verify_health_store.path).parent == dir_a

        monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(dir_b))
        _refresh_paths()
        verify_health_store.load()
        assert Path(verify_health_store.path).parent == dir_b
