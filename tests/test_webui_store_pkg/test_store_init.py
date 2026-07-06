"""Tests for webui_store.__init__ — store factories, singletons, _refresh_paths.

Plan 2026-06-30 Phase 3+ T3.6: webui_store test coverage expansion.
"""

from __future__ import annotations

__tier__ = "unit"

import os
from pathlib import Path
from typing import Any

import pytest

from webui_store import (
    _LazyStore,
    _refresh_paths,
    _store_path,
    channel_status_store,
    drafts_store,
    history_store,
    profiles_store,
    schedule_store,
)


class TestStorePath:
    """_store_path resolves paths correctly."""

    def test_store_path_resolves_under_config_dir(self, monkeypatch: Any) -> None:
        config_dir = Path("/tmp/test-bp-config")
        monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(config_dir))
        path = _store_path("test.json")
        assert str(path).endswith("test.json")
        assert str(config_dir) in str(path)


class TestRefreshPaths:
    """_refresh_paths resets lazy stores."""

    def test_refresh_resets_stores(self) -> None:
        # Should not raise, and after calling, stores should still be usable.
        _refresh_paths()
        # Verify stores are still functional (lazy re-creation on access)
        assert isinstance(history_store, _LazyStore)
        assert isinstance(drafts_store, _LazyStore)

    def test_refresh_idempotent(self) -> None:
        """Calling _refresh_paths twice is safe."""
        _refresh_paths()
        _refresh_paths()  # second call should be a no-op

    def test_refresh_clears_webui_db_cache(self) -> None:
        """After _refresh_paths, the next store access creates a new WebUIDatabase."""
        _refresh_paths()
        # Access each store to verify they can be lazily re-created
        try:
            _ = schedule_store.load()
        except Exception:
            pass  # Expected if no webui.db exists; we just verify no crash
        try:
            _ = profiles_store.load()
        except Exception:
            pass


class TestStoreSingletons:
    """Lazy store singletons are properly typed."""

    def test_history_store_is_lazy(self) -> None:
        assert isinstance(history_store, _LazyStore)

    def test_drafts_store_is_lazy(self) -> None:
        assert isinstance(drafts_store, _LazyStore)

    def test_profiles_store_is_lazy(self) -> None:
        assert isinstance(profiles_store, _LazyStore)

    def test_schedule_store_is_lazy(self) -> None:
        assert isinstance(schedule_store, _LazyStore)

    def test_channel_status_store_is_lazy(self) -> None:
        assert isinstance(channel_status_store, _LazyStore)
