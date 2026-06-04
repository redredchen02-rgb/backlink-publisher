"""Unit 1 — SQLite store migration edge cases (plan 2026-06-04-004).

Corrupt/binary/non-UTF-8 JSON → migration skipped, sentinel NOT written.
Empty startup → documented empty default. Crash-recovery: .migrated exists
but no sentinel → sentinel written. Queue pending-task recovery.
"""
from __future__ import annotations

__tier__ = "unit"

import json
from pathlib import Path

import pytest

from webui_store.sqlite_base import WebUIDatabase


# ── helpers ──────────────────────────────────────────────────────────────────

def _db(tmp_path: Path) -> WebUIDatabase:
    return WebUIDatabase(tmp_path / "webui.db")


STORE_PARAMS = [
    pytest.param("schedule", id="schedule"),
    pytest.param("profiles", id="profiles"),
    pytest.param("queue",    id="queue"),
    pytest.param("drafts",   id="drafts"),
    pytest.param("campaign", id="campaign"),
]

_SENTINEL = {
    "schedule": ".webui-schedule-migrated-v1",
    "profiles": ".webui-profiles-migrated-v1",
    "queue":    ".webui-queue-migrated-v1",
    "drafts":   ".webui-drafts-migrated-v1",
    "campaign": ".webui-campaign-migrated-v1",
}

_JSON = {
    "schedule": "schedule-settings.json",
    "profiles": "campaign-profiles.json",
    "queue":    "publish-queue.json",
    "drafts":   "draft-queue.json",
    "campaign": "campaigns.json",
}

_EMPTY_DEFAULT = {
    "schedule": {},
    "profiles": [],
    "queue":    [],
    "drafts":   [],
    "campaign": [],
}


def _make_store(key: str, db: WebUIDatabase):
    if key == "schedule":
        from webui_store.schedule import ScheduleSqliteStore
        return ScheduleSqliteStore(db)
    if key == "profiles":
        from webui_store.profiles import ProfilesSqliteStore
        return ProfilesSqliteStore(db)
    if key == "queue":
        from webui_store.queue_store import QueueSqliteStore
        return QueueSqliteStore(db)
    if key == "drafts":
        from webui_store.drafts import DraftsSqliteStore
        return DraftsSqliteStore(db)
    if key == "campaign":
        from webui_store.campaign_store import CampaignSqliteStore
        return CampaignSqliteStore(db)
    raise ValueError(key)


# ── empty startup ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("key", STORE_PARAMS)
def test_empty_startup_returns_default(tmp_path, monkeypatch, key):
    """No JSON, no SQLite → documented empty default; no exception."""
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
    store = _make_store(key, _db(tmp_path))
    store.migrate_from_json(tmp_path)
    result = store.load()
    assert result == _EMPTY_DEFAULT[key], f"{key}: expected {_EMPTY_DEFAULT[key]!r}, got {result!r}"
    # Positive: store is accessible and returns correct type
    assert isinstance(result, type(_EMPTY_DEFAULT[key]))


# ── corrupt / non-UTF-8 / empty JSON ─────────────────────────────────────────

@pytest.mark.parametrize("key", STORE_PARAMS)
@pytest.mark.parametrize("bad_bytes,label", [
    (b"\xff\xfe\x00\x01",    "binary"),
    ("valid json".encode("latin-1"), "latin1-non-utf8"),
    (b"",                    "zero-byte"),
])
def test_corrupt_json_skips_migration(tmp_path, monkeypatch, key, bad_bytes, label):
    """Corrupt/non-UTF-8/zero-byte JSON → sentinel NOT written; empty default returned."""
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
    json_path = tmp_path / _JSON[key]
    json_path.write_bytes(bad_bytes)

    store = _make_store(key, _db(tmp_path))
    store.migrate_from_json(tmp_path)

    sentinel = tmp_path / _SENTINEL[key]
    # Negative: sentinel must NOT be written (allows retry when file is fixed)
    assert not sentinel.exists(), f"{key}/{label}: sentinel should not be written on corrupt input"
    # Positive: store returns empty default (not an exception, not stale data)
    result = store.load()
    assert result == _EMPTY_DEFAULT[key], f"{key}/{label}: expected empty default after skipped migration"


# ── crash recovery: .migrated exists, sentinel absent ─────────────────────────

@pytest.mark.parametrize("key", STORE_PARAMS)
def test_crash_recovery_writes_sentinel(tmp_path, monkeypatch, key):
    """.json.migrated exists but sentinel absent → sentinel written; no re-migration."""
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
    json_path = tmp_path / _JSON[key]
    migrated_path = json_path.with_suffix(".json.migrated")

    # Simulate a prior migration that completed rename but crashed before sentinel
    migrated_path.write_text("[]", encoding="utf-8")
    assert not (tmp_path / _SENTINEL[key]).exists()

    store = _make_store(key, _db(tmp_path))
    store.migrate_from_json(tmp_path)

    sentinel = tmp_path / _SENTINEL[key]
    # Positive: sentinel written on crash recovery
    assert sentinel.exists(), f"{key}: sentinel should be written in crash recovery"
    # Positive: store accessible and returns empty default (DB has no data)
    result = store.load()
    assert result == _EMPTY_DEFAULT[key]


# ── sentinel idempotency ──────────────────────────────────────────────────────

@pytest.mark.parametrize("key", STORE_PARAMS)
def test_sentinel_prevents_double_migration(tmp_path, monkeypatch, key):
    """Second call to migrate_from_json with sentinel present → no-op."""
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
    (tmp_path / _SENTINEL[key]).write_text("migrated", encoding="utf-8")

    # Place a valid JSON file — it must NOT be imported
    json_path = tmp_path / _JSON[key]
    json_path.write_text('{"should_not_appear": true}', encoding="utf-8")

    store = _make_store(key, _db(tmp_path))
    store.migrate_from_json(tmp_path)

    result = store.load()
    # Negative: sentinel-blocked migration must not import the JSON
    if isinstance(result, dict):
        assert "should_not_appear" not in result
    elif isinstance(result, list):
        assert result == []


# ── queue pending-task recovery ───────────────────────────────────────────────

def test_queue_pending_task_survives_migration(tmp_path, monkeypatch):
    """JSON with one pending task → migrate → second instance → get_runnable() returns task."""
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
    from webui_store.queue_store import QueueSqliteStore

    pending = [{"id": "task-001", "status": "pending", "next_retry_at": None,
                "data": {"url": "https://example.com"}}]
    json_path = tmp_path / "publish-queue.json"
    json_path.write_text(json.dumps(pending), encoding="utf-8")

    db = _db(tmp_path)
    store1 = QueueSqliteStore(db)
    store1.migrate_from_json(tmp_path)

    # Sentinel written — second instance should find data without re-migrating
    assert (tmp_path / ".webui-queue-migrated-v1").exists()

    db2 = WebUIDatabase(tmp_path / "webui.db")
    store2 = QueueSqliteStore(db2)
    # Positive: get_runnable returns the pending task
    runnable = store2.get_runnable()
    assert len(runnable) == 1
    assert runnable[0]["id"] == "task-001"
    assert runnable[0]["status"] == "pending"
