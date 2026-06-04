"""Tests for ProfilesSqliteStore (Unit 3) — profiles_store → webui.db.

Verifies load/save/update roundtrip for a list of profile dicts, startup
migration from JSON, sentinel idempotency, crash-recovery, and Store
protocol compliance.

Plan: docs/plans/2026-06-03-008-refactor-webui-store-sqlite-unification-plan.md
"""

from __future__ import annotations

import json
from pathlib import Path

from webui_store.base import Store
from webui_store.profiles import ProfilesSqliteStore, _JSON_FILENAME, _SENTINEL_NAME
from webui_store.sqlite_base import WebUIDatabase


def _store(tmp_path: Path) -> ProfilesSqliteStore:
    return ProfilesSqliteStore(WebUIDatabase(tmp_path / "webui.db"))


_SAMPLE = [
    {"name": "alpha", "platforms": ["medium", "devto"]},
    {"name": "beta", "platforms": ["notion"]},
]


# ── Core Store protocol ───────────────────────────────────────────────────────

class TestProfilesSqliteStoreProtocol:
    def test_isinstance_store(self, tmp_path):
        assert isinstance(_store(tmp_path), Store)

    def test_load_returns_empty_list_when_absent(self, tmp_path):
        assert _store(tmp_path).load() == []

    def test_load_returns_list_not_none(self, tmp_path):
        assert isinstance(_store(tmp_path).load(), list)

    def test_save_and_load_roundtrip(self, tmp_path):
        store = _store(tmp_path)
        store.save(_SAMPLE)
        assert store.load() == _SAMPLE

    def test_save_overwrites_previous(self, tmp_path):
        store = _store(tmp_path)
        store.save([{"name": "x"}])
        store.save([{"name": "y"}])
        assert store.load() == [{"name": "y"}]

    def test_save_empty_list(self, tmp_path):
        store = _store(tmp_path)
        store.save([])
        assert store.load() == []

    def test_update_appends_profile(self, tmp_path):
        store = _store(tmp_path)
        store.save([{"name": "a"}])
        result = store.update(lambda items: [*items, {"name": "b"}])
        assert result == [{"name": "a"}, {"name": "b"}]
        assert store.load() == [{"name": "a"}, {"name": "b"}]


# ── Startup migration ─────────────────────────────────────────────────────────

class TestStartupMigration:
    def test_migrates_from_json_when_present(self, tmp_path):
        (tmp_path / _JSON_FILENAME).write_text(json.dumps(_SAMPLE), encoding="utf-8")
        store = _store(tmp_path)
        store.migrate_from_json(tmp_path)

        assert store.load() == _SAMPLE
        assert (tmp_path / (_JSON_FILENAME + ".migrated")).exists()
        assert (tmp_path / _SENTINEL_NAME).exists()
        assert not (tmp_path / _JSON_FILENAME).exists()

    def test_migration_preserves_all_records(self, tmp_path):
        many = [{"name": f"p{i}"} for i in range(25)]
        (tmp_path / _JSON_FILENAME).write_text(json.dumps(many), encoding="utf-8")
        store = _store(tmp_path)
        store.migrate_from_json(tmp_path)
        assert store.load() == many

    def test_migrated_file_chmod_600(self, tmp_path):
        (tmp_path / _JSON_FILENAME).write_text("[]", encoding="utf-8")
        store = _store(tmp_path)
        store.migrate_from_json(tmp_path)
        migrated = tmp_path / (_JSON_FILENAME + ".migrated")
        assert migrated.exists()
        assert (migrated.stat().st_mode & 0o777) == 0o600

    def test_idempotent_when_sentinel_exists(self, tmp_path):
        (tmp_path / _JSON_FILENAME).write_text(json.dumps(_SAMPLE), encoding="utf-8")
        (tmp_path / _SENTINEL_NAME).write_text("migrated", encoding="utf-8")
        store = _store(tmp_path)
        store.migrate_from_json(tmp_path)
        assert (tmp_path / _JSON_FILENAME).exists()
        assert store.load() == []

    def test_no_op_when_json_absent(self, tmp_path):
        store = _store(tmp_path)
        store.migrate_from_json(tmp_path)
        assert not (tmp_path / _SENTINEL_NAME).exists()
        assert store.load() == []

    def test_corrupt_json_skipped_no_sentinel(self, tmp_path):
        (tmp_path / _JSON_FILENAME).write_text("not valid [", encoding="utf-8")
        store = _store(tmp_path)
        store.migrate_from_json(tmp_path)
        assert not (tmp_path / _SENTINEL_NAME).exists()
        assert (tmp_path / _JSON_FILENAME).exists()

    def test_crash_recovery_migrated_exists_no_sentinel(self, tmp_path):
        (tmp_path / (_JSON_FILENAME + ".migrated")).write_text("[]", encoding="utf-8")
        store = _store(tmp_path)
        store.migrate_from_json(tmp_path)
        assert (tmp_path / _SENTINEL_NAME).exists()


# ── Integration: import from webui_store ─────────────────────────────────────

class TestWebuiStoreIntegration:
    def test_profiles_store_import_satisfies_protocol(self, monkeypatch, tmp_path):
        monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
        from webui_store import _refresh_paths, profiles_store
        _refresh_paths()

        assert isinstance(profiles_store._real(), ProfilesSqliteStore)
        profiles_store.save([{"name": "z"}])
        assert profiles_store.load() == [{"name": "z"}]

    def test_profiles_store_path_is_webui_db(self, monkeypatch, tmp_path):
        monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
        from webui_store import _refresh_paths, profiles_store
        _refresh_paths()
        assert profiles_store.path == tmp_path / "webui.db"
