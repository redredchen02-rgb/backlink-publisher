"""F3 (plan 2026-07-13-004): _lazy_init wires the operator catalog dir.

Before F3, ``register_catalog_entries`` was called with no ``user_config_dir``,
so operator-authored ``<config_dir>/catalog/*.yaml`` never registered in
production (only tests passed the arg). These tests pin the wiring at the
``_lazy_init`` seam — captured, not via a full registry re-init (which would
collide with the process-global registry) — and the sandbox fail-closed guard.
"""

from __future__ import annotations

from pathlib import Path

from backlink_publisher._util import paths as _paths
import backlink_publisher.publishing.adapters as A


def test_lazy_init_passes_resolved_user_catalog_dir(tmp_path, monkeypatch):
    cfg = tmp_path / "cfg"
    (cfg / "catalog").mkdir(parents=True)
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(cfg))

    captured: dict[str, str] = {}

    def _fake_register_catalog(built_in_dir: str = "", user_config_dir: str = "") -> None:
        captured["built_in"] = built_in_dir
        captured["user"] = user_config_dir

    monkeypatch.setattr(A, "register_all_adapters", lambda: None)
    monkeypatch.setattr(A, "register_catalog_entries", _fake_register_catalog)
    monkeypatch.setattr(A, "_INITIALIZED", False)

    A._lazy_init()

    assert captured["user"] == str(cfg / "catalog")
    assert captured["built_in"] == A._builtin_catalog


def test_lazy_init_falls_back_when_config_dir_unresolvable(monkeypatch):
    def _boom() -> Path:
        raise RuntimeError("test-sandbox fail-closed: no config override")

    monkeypatch.setattr(_paths, "_config_dir", _boom)

    captured: dict[str, str] = {}

    def _fake_register_catalog(built_in_dir: str = "", user_config_dir: str = "") -> None:
        captured["user"] = user_config_dir

    monkeypatch.setattr(A, "register_all_adapters", lambda: None)
    monkeypatch.setattr(A, "register_catalog_entries", _fake_register_catalog)
    monkeypatch.setattr(A, "_INITIALIZED", False)

    A._lazy_init()

    assert captured["user"] == ""  # guard swallowed the RuntimeError
