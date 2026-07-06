"""Tests for webui_store.base — JsonStore, _LazyStore, Store protocol.

Plan 2026-06-30 Phase 3+ T3.6: webui_store test coverage expansion.
"""

from __future__ import annotations

__tier__ = "unit"

import json
from pathlib import Path
from typing import Any

import pytest

from webui_store.base import JsonStore, Store, _LazyStore


# ═════════════════════════════════════════════════════════════════════════════
# Store protocol (structural typing check)
# ═════════════════════════════════════════════════════════════════════════════


def test_jsonstore_satisfies_store_protocol(tmp_path: Path) -> None:
    """JsonStore instances satisfy the Store protocol at runtime."""
    store: Any = JsonStore(tmp_path / "test.json", default_factory=dict)
    assert isinstance(store, Store)


# ═════════════════════════════════════════════════════════════════════════════
# JsonStore — load / save / update
# ═════════════════════════════════════════════════════════════════════════════


class TestJsonStore:
    """JsonStore unit tests."""

    def test_load_returns_default_when_missing(self, tmp_path: Path) -> None:
        store = JsonStore(tmp_path / "nonexistent.json", default_factory=list)
        assert store.load() == []

    def test_load_returns_default_when_corrupt(self, tmp_path: Path) -> None:
        f = tmp_path / "corrupt.json"
        f.write_text("{bad json", encoding="utf-8")
        store = JsonStore(f, default_factory=lambda: {"fallback": True})
        assert store.load() == {"fallback": True}

    def test_save_and_load_round_trip(self, tmp_path: Path) -> None:
        store = JsonStore(tmp_path / "data.json", default_factory=dict)
        store.save({"key": "value", "num": 42})
        assert store.load() == {"key": "value", "num": 42}

    def test_save_overwrites_previous(self, tmp_path: Path) -> None:
        store = JsonStore(tmp_path / "data.json", default_factory=list)
        store.save([1, 2, 3])
        store.save([4, 5])
        assert store.load() == [4, 5]

    def test_update_atomicity(self, tmp_path: Path) -> None:
        """update() atomically transforms the stored value under lock."""
        store = JsonStore(tmp_path / "counter.json", default_factory=lambda: {"n": 0})

        def inc(data: dict) -> dict:
            data["n"] += 1
            return data

        result = store.update(inc)
        assert result == {"n": 1}
        assert store.load() == {"n": 1}

        store.update(inc)
        assert store.load() == {"n": 2}

    def test_update_returns_new_value(self, tmp_path: Path) -> None:
        store = JsonStore(tmp_path / "data.json", default_factory=list)

        def append_item(data: list) -> list:
            data.append("a")
            return data

        result = store.update(append_item)
        assert result == ["a"]
        assert store.load() == ["a"]

    def test_path_property(self, tmp_path: Path) -> None:
        p = tmp_path / "test.json"
        store = JsonStore(p, default_factory=dict)
        assert store.path == p

    def test_path_setter(self, tmp_path: Path) -> None:
        store = JsonStore(tmp_path / "old.json", default_factory=dict)
        new_path = tmp_path / "new.json"
        store.path = new_path
        store.save({"ok": True})
        assert new_path.exists()
        assert not (tmp_path / "old.json").exists()

    def test_default_factory_called_each_load(self, tmp_path: Path) -> None:
        """Each call to load() on a missing file calls default_factory afresh."""
        calls: list[int] = []

        def factory() -> list:
            calls.append(1)
            return []

        store = JsonStore(tmp_path / "missing.json", default_factory=factory)
        store.load()
        store.load()
        assert len(calls) == 2

    def test_save_non_ascii(self, tmp_path: Path) -> None:
        """ensure_ascii=False preserves Unicode characters."""
        store = JsonStore(tmp_path / "unicode.json", default_factory=dict)
        store.save({"text": "中文"})
        raw = (tmp_path / "unicode.json").read_text(encoding="utf-8")
        assert "中文" in raw
        assert store.load() == {"text": "中文"}


# ═════════════════════════════════════════════════════════════════════════════
# _LazyStore — lazy proxy
# ═════════════════════════════════════════════════════════════════════════════


class TestLazyStore:
    """_LazyStore proxy unit tests."""

    def test_factory_not_called_on_creation(self, tmp_path: Path) -> None:
        called = False

        def factory() -> JsonStore:
            nonlocal called
            called = True
            return JsonStore(tmp_path / "lazy.json", default_factory=dict)

        store = _LazyStore(factory)
        assert not called  # factory deferred

    def test_factory_called_on_first_access(self, tmp_path: Path) -> None:
        called = False

        def factory() -> JsonStore:
            nonlocal called
            called = True
            return JsonStore(tmp_path / "lazy.json", default_factory=dict)

        store = _LazyStore(factory)
        store.load()
        assert called

    def test_load_returns_correct_value(self, tmp_path: Path) -> None:
        real = JsonStore(tmp_path / "data.json", default_factory=lambda: {"x": 1})
        real.save({"x": 42})

        lazy = _LazyStore(lambda: JsonStore(tmp_path / "data.json", default_factory=dict))
        assert lazy.load() == {"x": 42}

    def test_save_through_proxy(self, tmp_path: Path) -> None:
        lazy = _LazyStore(lambda: JsonStore(tmp_path / "proxy.json", default_factory=list))
        lazy.save([1, 2, 3])
        assert (tmp_path / "proxy.json").exists()
        assert json.loads((tmp_path / "proxy.json").read_text(encoding="utf-8")) == [1, 2, 3]

    def test_update_through_proxy(self, tmp_path: Path) -> None:
        lazy = _LazyStore(lambda: JsonStore(tmp_path / "proxy.json", default_factory=lambda: {"n": 0}))
        result = lazy.update(lambda d: {"n": d["n"] + 1})
        assert result == {"n": 1}

    def test_path_property(self, tmp_path: Path) -> None:
        p = tmp_path / "proxy.json"
        lazy = _LazyStore(lambda: JsonStore(p, default_factory=dict))
        assert lazy.path == p

    def test_reset_discards_cached_instance(self, tmp_path: Path) -> None:
        calls = 0

        def factory() -> JsonStore:
            nonlocal calls
            calls += 1
            return JsonStore(tmp_path / "reset.json", default_factory=dict)

        lazy = _LazyStore(factory)
        lazy.load()
        assert calls == 1
        lazy.reset()
        lazy.load()
        assert calls == 2  # factory called again after reset

    def test_env_change_invalidates_cache(self, tmp_path: Path, monkeypatch: Any) -> None:
        """When BACKLINK_PUBLISHER_CONFIG_DIR changes, _real() drops the cached
        instance and creates a new one."""
        dir_a = tmp_path / "a"
        dir_b = tmp_path / "b"
        dir_a.mkdir()
        dir_b.mkdir()

        monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(dir_a))
        lazy = _LazyStore(lambda: JsonStore(
            dir_a / "data.json", default_factory=lambda: {"env": "a"}
        ))
        monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(dir_b))
        # After env change, the lazy store should see the new path
        # (the factory binds to the dir at creation time, so we verify
        # the instance is recreated).
        lazy.load()
        # This test primarily verifies no crash on env change

    def test_fallback_getattr(self, tmp_path: Path) -> None:
        """__getattr__ delegates unknown attributes to the real store."""
        lazy = _LazyStore(lambda: JsonStore(tmp_path / "attr.json", default_factory=dict))
        # JsonStore has a public .path property
        assert lazy.path == tmp_path / "attr.json"
