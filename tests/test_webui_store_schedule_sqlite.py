"""Tests for ScheduleSqliteStore (Unit 2) — schedule_store → webui.db.

Verifies load/save/update roundtrip, startup migration from JSON, sentinel
idempotency, crash-recovery, and Store protocol compliance.

Plan: docs/plans/2026-06-03-008-refactor-webui-store-sqlite-unification-plan.md
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from webui_store.schedule import ScheduleSqliteStore, _JSON_FILENAME, _SENTINEL_NAME
from webui_store.sqlite_base import WebUIDatabase
from webui_store.base import Store


def _store(tmp_path: Path) -> ScheduleSqliteStore:
    return ScheduleSqliteStore(WebUIDatabase(tmp_path / "webui.db"))


# ── Core Store protocol ───────────────────────────────────────────────────────

class TestScheduleSqliteStoreProtocol:
    def test_isinstance_store(self, tmp_path):
        assert isinstance(_store(tmp_path), Store)

    def test_load_returns_empty_dict_when_absent(self, tmp_path):
        assert _store(tmp_path).load() == {}

    def test_save_and_load_roundtrip(self, tmp_path):
        store = _store(tmp_path)
        store.save({"min_interval_hours": 8, "jitter_minutes": 15})
        assert store.load() == {"min_interval_hours": 8, "jitter_minutes": 15}

    def test_save_overwrites_previous(self, tmp_path):
        store = _store(tmp_path)
        store.save({"a": 1})
        store.save({"b": 2})
        assert store.load() == {"b": 2}

    def test_update_merges_key(self, tmp_path):
        store = _store(tmp_path)
        store.save({"min_interval_hours": 4})
        result = store.update(lambda d: {**d, "jitter_minutes": 30})
        assert result == {"min_interval_hours": 4, "jitter_minutes": 30}
        assert store.load() == {"min_interval_hours": 4, "jitter_minutes": 30}

    def test_load_returns_dict_not_none(self, tmp_path):
        store = _store(tmp_path)
        result = store.load()
        assert isinstance(result, dict)

    def test_save_empty_dict(self, tmp_path):
        store = _store(tmp_path)
        store.save({})
        assert store.load() == {}


# ── Startup migration ─────────────────────────────────────────────────────────

class TestStartupMigration:
    def test_migrates_from_json_when_present(self, tmp_path):
        data = {"min_interval_hours": 6, "jitter_minutes": 20}
        (tmp_path / _JSON_FILENAME).write_text(
            json.dumps(data), encoding="utf-8"
        )
        store = _store(tmp_path)
        store.migrate_from_json(tmp_path)

        assert store.load() == data
        assert (tmp_path / (_JSON_FILENAME + ".migrated")).exists()
        assert (tmp_path / _SENTINEL_NAME).exists()
        assert not (tmp_path / _JSON_FILENAME).exists()

    def test_migrated_file_chmod_600(self, tmp_path):
        (tmp_path / _JSON_FILENAME).write_text("{}", encoding="utf-8")
        store = _store(tmp_path)
        store.migrate_from_json(tmp_path)
        migrated = tmp_path / (_JSON_FILENAME + ".migrated")
        assert migrated.exists()
        assert (migrated.stat().st_mode & 0o777) == 0o600

    def test_idempotent_when_sentinel_exists(self, tmp_path):
        data = {"a": 1}
        (tmp_path / _JSON_FILENAME).write_text(json.dumps(data), encoding="utf-8")
        (tmp_path / _SENTINEL_NAME).write_text("migrated", encoding="utf-8")

        store = _store(tmp_path)
        store.migrate_from_json(tmp_path)

        # JSON file should remain untouched (sentinel stopped migration)
        assert (tmp_path / _JSON_FILENAME).exists()
        assert store.load() == {}  # nothing imported

    def test_no_op_when_json_absent(self, tmp_path):
        store = _store(tmp_path)
        store.migrate_from_json(tmp_path)
        assert not (tmp_path / _SENTINEL_NAME).exists()
        assert store.load() == {}

    def test_corrupt_json_skipped_no_sentinel(self, tmp_path):
        (tmp_path / _JSON_FILENAME).write_text("not valid json {", encoding="utf-8")
        store = _store(tmp_path)
        store.migrate_from_json(tmp_path)

        # Corrupt file: sentinel NOT written (allows retry if file is repaired)
        assert not (tmp_path / _SENTINEL_NAME).exists()
        # JSON file still present (not renamed)
        assert (tmp_path / _JSON_FILENAME).exists()

    def test_crash_recovery_migrated_exists_no_sentinel(self, tmp_path):
        """Process died after rename but before sentinel — next boot writes sentinel."""
        (tmp_path / (_JSON_FILENAME + ".migrated")).write_text("{}", encoding="utf-8")
        store = _store(tmp_path)
        store.migrate_from_json(tmp_path)
        assert (tmp_path / _SENTINEL_NAME).exists()

    def test_second_migration_call_is_no_op(self, tmp_path):
        (tmp_path / _JSON_FILENAME).write_text('{"x": 1}', encoding="utf-8")
        store = _store(tmp_path)
        store.migrate_from_json(tmp_path)

        # Inject different data, call again — should not overwrite
        store.save({"x": 999})
        store.migrate_from_json(tmp_path)
        assert store.load() == {"x": 999}


# ── Integration: import from webui_store ─────────────────────────────────────

class TestWebuiStoreIntegration:
    def test_schedule_store_import_satisfies_protocol(self, monkeypatch, tmp_path):
        monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
        from webui_store import _refresh_paths, schedule_store
        _refresh_paths()

        assert isinstance(schedule_store._real(), ScheduleSqliteStore)
        schedule_store.save({"hello": "world"})
        assert schedule_store.load() == {"hello": "world"}

    def test_schedule_store_path_is_webui_db(self, monkeypatch, tmp_path):
        monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
        from webui_store import _refresh_paths, schedule_store
        _refresh_paths()

        assert schedule_store.path == tmp_path / "webui.db"
