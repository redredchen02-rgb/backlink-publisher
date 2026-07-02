"""Tests for BlobSqliteStore subclasses — Schedule, PublishDefaults, etc.

Plan 2026-06-30 Phase 3+ T3.6: webui_store test coverage expansion.
"""

from __future__ import annotations

__tier__ = "unit"

from pathlib import Path

import pytest

from webui_store.publish_defaults import PublishDefaultsSqliteStore
from webui_store.schedule import ScheduleSqliteStore
from webui_store.sqlite_base import WebUIDatabase


@pytest.fixture
def schedule_store(tmp_path: Path) -> ScheduleSqliteStore:
    return ScheduleSqliteStore(WebUIDatabase(tmp_path / "webui.db"))


@pytest.fixture
def defaults_store(tmp_path: Path) -> PublishDefaultsSqliteStore:
    return PublishDefaultsSqliteStore(WebUIDatabase(tmp_path / "webui.db"))


class TestScheduleStore:
    """ScheduleSqliteStore — BlobSqliteStore with dict value type."""

    def test_default_is_empty_dict(self, schedule_store: ScheduleSqliteStore) -> None:
        assert schedule_store.load() == {}

    def test_save_and_load(self, schedule_store: ScheduleSqliteStore) -> None:
        data = {"interval_hours": 6, "enabled": True, "platforms": ["medium"]}
        schedule_store.save(data)
        assert schedule_store.load() == data

    def test_update(self, schedule_store: ScheduleSqliteStore) -> None:
        schedule_store.save({"interval_hours": 4})
        result = schedule_store.update(lambda d: {**d, "enabled": True})
        assert result == {"interval_hours": 4, "enabled": True}

    def test_overwrite(self, schedule_store: ScheduleSqliteStore) -> None:
        schedule_store.save({"version": 1})
        schedule_store.save({"version": 2})
        assert schedule_store.load() == {"version": 2}


class TestPublishDefaultsStore:
    """PublishDefaultsSqliteStore — BlobSqliteStore with dict value type."""

    def test_default_is_empty_dict(self, defaults_store: PublishDefaultsSqliteStore) -> None:
        assert defaults_store.load() == {}

    def test_save_and_load(self, defaults_store: PublishDefaultsSqliteStore) -> None:
        data = {"publish_mode": "draft", "dofollow": True}
        defaults_store.save(data)
        loaded = defaults_store.load()
        assert loaded["publish_mode"] == "draft"
        assert loaded["dofollow"] is True

    def test_update_merges(self, defaults_store: PublishDefaultsSqliteStore) -> None:
        defaults_store.save({"platform": "medium"})
        result = defaults_store.update(lambda d: {**d, "language": "en"})
        assert result["platform"] == "medium"
        assert result["language"] == "en"
