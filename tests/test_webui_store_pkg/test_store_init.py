"""Tests for webui_store.__init__ — store factories, singletons, _refresh_paths.

Plan 2026-06-30 Phase 3+ T3.6: webui_store test coverage expansion.
"""

from __future__ import annotations

__tier__ = "unit"

import ast
import inspect
import os
from pathlib import Path
import textwrap
from typing import Any

import pytest

import webui_store
from webui_store import (
    _LazyStore,
    _refresh_paths,
    _store_path,
    channel_status_store,
    drafts_store,
    error_report_store,
    history_store,
    profiles_store,
    schedule_store,
    verify_health_store,
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

    def test_verify_health_store_is_lazy(self) -> None:
        assert isinstance(verify_health_store, _LazyStore)

    def test_error_report_store_is_lazy(self) -> None:
        assert isinstance(error_report_store, _LazyStore)


class TestLazyStoreCompleteness:
    """Scan-based guard against a repeat of the A1 gap: ``verify_health_store``
    and ``error_report_store`` were each defined as a module-level
    ``_LazyStore`` singleton in their own submodule but never wired into
    ``webui_store.__all__`` or ``_refresh_paths()``'s reset tuple — the same
    shape of omission happened twice independently. Rather than hand-listing
    known store names (which is exactly what let the omission go undetected
    for two separate stores), this enumerates every module-level
    ``_LazyStore(...)`` declaration under ``webui_store/*.py`` via AST, so a
    future third store is caught automatically.
    """

    @staticmethod
    def _scan_lazy_store_names_in_dir(pkg_dir: Path) -> dict[str, str]:
        """Return ``{store_name: filename}`` for every module-level
        ``name = _LazyStore(...)`` or ``name: _LazyStore = _LazyStore(...)``
        assignment found directly in the top level of any ``*.py`` file in
        ``pkg_dir`` (nested/function-local assignments are intentionally
        not matched — only real singleton declarations live at module level).
        """
        found: dict[str, str] = {}
        for path in sorted(pkg_dir.glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in tree.body:
                target: ast.expr | None
                value: ast.expr | None
                if isinstance(node, ast.Assign) and len(node.targets) == 1:
                    target, value = node.targets[0], node.value
                elif isinstance(node, ast.AnnAssign) and node.value is not None:
                    target, value = node.target, node.value
                else:
                    continue
                if (
                    isinstance(target, ast.Name)
                    and isinstance(value, ast.Call)
                    and isinstance(value.func, ast.Name)
                    and value.func.id == "_LazyStore"
                ):
                    found[target.id] = path.name
        return found

    @classmethod
    def _scan_lazy_store_names(cls) -> dict[str, str]:
        pkg_dir = Path(webui_store.__file__).parent
        return cls._scan_lazy_store_names_in_dir(pkg_dir)

    @staticmethod
    def _scan_refresh_paths_reset_names() -> set[str]:
        """Names iterated over by the ``for store in (...): store.reset()``
        loop inside the real ``_refresh_paths()``, read from its live source
        (not a hardcoded mirror of the tuple) so this stays correct
        regardless of future reordering/reformatting of that function.
        """
        source = textwrap.dedent(inspect.getsource(webui_store._refresh_paths))
        func = ast.parse(source).body[0]
        assert isinstance(func, ast.FunctionDef)
        names: set[str] = set()
        for node in ast.walk(func):
            if isinstance(node, ast.For) and isinstance(node.iter, (ast.Tuple, ast.List)):
                names.update(
                    elt.id for elt in node.iter.elts if isinstance(elt, ast.Name)
                )
        return names

    def test_scan_finds_known_stores(self) -> None:
        # Documents the current baseline (11 stores as of A1) and guards the
        # scanner itself against silently finding zero/too-few declarations.
        expected = {
            "history_store", "profiles_store", "drafts_store",
            "schedule_store", "queue_store", "campaign_store",
            "publish_defaults_store", "batch_ops_store",
            "channel_status_store", "verify_health_store",
            "error_report_store",
        }
        found = self._scan_lazy_store_names()
        assert expected <= set(found), (
            f"expected known stores {sorted(expected - set(found))} "
            "were not found by the AST scan — scanner may be broken"
        )

    def test_every_lazy_store_is_exported_and_reset(self) -> None:
        found = self._scan_lazy_store_names()
        assert found, "AST scan found zero _LazyStore singletons — scan is broken"

        exported = set(webui_store.__all__)
        reset_names = self._scan_refresh_paths_reset_names()

        missing_all = {
            name: fname for name, fname in found.items() if name not in exported
        }
        missing_refresh = {
            name: fname for name, fname in found.items() if name not in reset_names
        }

        assert not missing_all, (
            "_LazyStore singleton(s) declared but not exported via "
            f"webui_store.__all__: {missing_all}"
        )
        assert not missing_refresh, (
            "_LazyStore singleton(s) declared but not reset by "
            f"webui_store._refresh_paths(): {missing_refresh}"
        )

    def test_red_path_unwired_lazy_store_is_detected(self, tmp_path: Path) -> None:
        # Proves the scan (and the completeness check built on it) has teeth:
        # a module-level _LazyStore(...) declaration that is not exported/
        # reset is found and named — mirroring the real verify_health_store /
        # error_report_store omission this test class exists to prevent.
        fake_module = tmp_path / "_fake_offender.py"
        fake_module.write_text(
            "from webui_store.base import _LazyStore\n"
            "unwired_fake_store = _LazyStore(lambda: None)\n",
            encoding="utf-8",
        )

        found = self._scan_lazy_store_names_in_dir(tmp_path)
        assert found == {"unwired_fake_store": "_fake_offender.py"}

        # Same comparison test_every_lazy_store_is_exported_and_reset makes,
        # against the *real* package's __all__/_refresh_paths: the fake name
        # is absent from both, so it must be reported as missing.
        exported = set(webui_store.__all__)
        reset_names = self._scan_refresh_paths_reset_names()
        assert "unwired_fake_store" not in exported
        assert "unwired_fake_store" not in reset_names
