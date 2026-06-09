"""Tests for ChannelStatusSqliteStore (Unit 4) — channel_status_store → webui.db.

Covers load/save/update roundtrip incl. ``extra_json`` fidelity for
identity-mismatch records, the functional API over the SQLite backing,
startup migration from ``channel-status.json``, and Store protocol compliance.

Plan: docs/plans/2026-06-03-008-refactor-webui-store-sqlite-unification-plan.md
"""

from __future__ import annotations


__tier__ = "integration"
import json
import os
from pathlib import Path

import pytest

from backlink_publisher.config.loader import _config_dir
from webui_store import channel_status_store
from webui_store.base import Store
from webui_store.channel_status import (
    ChannelStatusSqliteStore,
    _JSON_FILENAME,
    _SENTINEL_NAME,
    get_status,
    list_all,
    mark_bound,
    mark_expired,
    mark_identity_mismatch,
    mark_verified,
    reconcile_on_load,
)
from webui_store.sqlite_base import WebUIDatabase


def _store(tmp_path: Path) -> ChannelStatusSqliteStore:
    return ChannelStatusSqliteStore(WebUIDatabase(tmp_path / "webui.db"))


# ── Core Store protocol ───────────────────────────────────────────────────────


class TestChannelStatusSqliteStoreProtocol:
    def test_isinstance_store(self, tmp_path):
        assert isinstance(_store(tmp_path), Store)

    def test_load_returns_empty_dict_when_absent(self, tmp_path):
        assert _store(tmp_path).load() == {}

    def test_save_and_load_roundtrip(self, tmp_path):
        store = _store(tmp_path)
        value = {
            "medium": {
                "status": "bound",
                "bound_at": "2026-01-01T00:00:00+00:00",
                "storage_state_path": "/cfg/medium.json",
                "last_verified_at": None,
            }
        }
        store.save(value)
        assert store.load() == value

    def test_save_overwrites_previous_full_rewrite(self, tmp_path):
        store = _store(tmp_path)
        store.save({"a": {"status": "bound", "bound_at": None,
                          "storage_state_path": None, "last_verified_at": None}})
        store.save({"b": {"status": "expired", "bound_at": None,
                          "storage_state_path": None, "last_verified_at": None}})
        loaded = store.load()
        assert set(loaded.keys()) == {"b"}

    def test_save_empty_dict(self, tmp_path):
        store = _store(tmp_path)
        store.save({"a": {"status": "bound", "bound_at": None,
                          "storage_state_path": None, "last_verified_at": None}})
        store.save({})
        assert store.load() == {}

    def test_update_merges_channel(self, tmp_path):
        store = _store(tmp_path)
        store.save({"medium": {"status": "bound", "bound_at": None,
                               "storage_state_path": None, "last_verified_at": None}})
        result = store.update(
            lambda d: {**d, "velog": {"status": "expired", "bound_at": None,
                                      "storage_state_path": None,
                                      "last_verified_at": None}}
        )
        assert set(result.keys()) == {"medium", "velog"}
        assert store.load()["velog"]["status"] == "expired"


# ── extra_json round-trip fidelity ────────────────────────────────────────────


class TestExtraJsonRoundTrip:
    def test_identity_mismatch_extra_keys_survive(self, tmp_path):
        store = _store(tmp_path)
        value = {
            "velog": {
                "status": "identity_mismatch",
                "bound_at": "2026-01-01T00:00:00+00:00",
                "storage_state_path": "/cfg/velog.json",
                "last_verified_at": None,
                "identity_mismatch_old": "alice",
                "identity_mismatch_new": "bob",
            }
        }
        store.save(value)
        loaded = store.load()
        assert loaded == value
        assert loaded["velog"]["identity_mismatch_old"] == "alice"
        assert loaded["velog"]["identity_mismatch_new"] == "bob"

    def test_records_without_extra_have_no_spurious_keys(self, tmp_path):
        store = _store(tmp_path)
        store.save({"medium": {"status": "bound", "bound_at": None,
                               "storage_state_path": None, "last_verified_at": None}})
        rec = store.load()["medium"]
        assert set(rec.keys()) == {
            "status", "bound_at", "storage_state_path", "last_verified_at"
        }

    def test_extra_json_column_null_when_no_extra(self, tmp_path):
        store = _store(tmp_path)
        store.save({"medium": {"status": "bound", "bound_at": None,
                               "storage_state_path": None, "last_verified_at": None}})
        with store._db.connect() as conn:
            row = conn.execute(
                "SELECT extra_json FROM channel_status WHERE channel = 'medium'"
            ).fetchone()
        assert row[0] is None

    def test_extra_json_column_populated_when_extra(self, tmp_path):
        store = _store(tmp_path)
        store.save({"velog": {"status": "identity_mismatch", "bound_at": None,
                              "storage_state_path": None, "last_verified_at": None,
                              "identity_mismatch_old": "a",
                              "identity_mismatch_new": "b"}})
        with store._db.connect() as conn:
            row = conn.execute(
                "SELECT extra_json FROM channel_status WHERE channel = 'velog'"
            ).fetchone()
        assert json.loads(row[0]) == {
            "identity_mismatch_old": "a", "identity_mismatch_new": "b"
        }


# ── Functional API over the SQLite backing ────────────────────────────────────


class TestFunctionalApiOverSqlite:
    @pytest.fixture(autouse=True)
    def _reset_store(self, tmp_path):
        # Redirect the lazy singleton at a fresh webui.db per test.
        channel_status_store.path = tmp_path / "webui.db"

    def test_mark_bound_then_get_status(self):
        target = _config_dir() / "medium-state.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("{}")
        mark_bound("medium", target)
        rec = get_status("medium")
        assert rec["status"] == "bound"
        assert rec["storage_state_path"] == str(target)

    def test_mark_verified_updates_only_timestamp(self):
        target = _config_dir() / "medium-state.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("{}")
        mark_bound("medium", target)
        bound_at = get_status("medium")["bound_at"]
        mark_verified("medium")
        rec = get_status("medium")
        assert rec["status"] == "bound"
        assert rec["bound_at"] == bound_at
        assert rec["last_verified_at"] is not None

    def test_mark_expired_clears_last_verified(self):
        target = _config_dir() / "medium-state.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("{}")
        mark_bound("medium", target)
        mark_verified("medium")
        mark_expired("medium")
        rec = get_status("medium")
        assert rec["status"] == "expired"
        assert rec["last_verified_at"] is None

    def test_mark_identity_mismatch_roundtrip_extra_json(self):
        target = _config_dir() / "velog-state.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("{}")
        mark_bound("velog", target)
        mark_identity_mismatch("velog", old_account="alice", new_account="bob")
        rec = get_status("velog")
        assert rec["status"] == "identity_mismatch"
        assert rec["identity_mismatch_old"] == "alice"
        assert rec["identity_mismatch_new"] == "bob"
        # And it survives a full reload (load() reconstructs from columns).
        assert list_all()["velog"]["identity_mismatch_new"] == "bob"

    def test_get_status_unknown_returns_default(self):
        rec = get_status("unknown_channel")
        assert rec == {
            "status": "unbound", "bound_at": None,
            "storage_state_path": None, "last_verified_at": None,
        }

    def test_reconcile_demotes_missing_file(self):
        target = _config_dir() / "velog-state.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("{}")
        mark_bound("velog", target)
        target.unlink()
        reconcile_on_load()
        assert get_status("velog")["status"] == "expired"

    def test_reconcile_leaves_identity_mismatch(self):
        target = _config_dir() / "velog-state.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("{}")
        mark_bound("velog", target)
        mark_identity_mismatch("velog", old_account="a", new_account="b")
        target.unlink()
        reconcile_on_load()
        assert get_status("velog")["status"] == "identity_mismatch"


# ── Startup migration ─────────────────────────────────────────────────────────


class TestStartupMigration:
    def test_migrates_all_records_from_json(self, tmp_path):
        data = {
            "medium": {
                "status": "bound",
                "bound_at": "2026-01-01T00:00:00+00:00",
                "storage_state_path": "/cfg/medium.json",
                "last_verified_at": None,
            },
            "velog": {
                "status": "identity_mismatch",
                "bound_at": None,
                "storage_state_path": None,
                "last_verified_at": None,
                "identity_mismatch_old": "alice",
                "identity_mismatch_new": "bob",
            },
        }
        (tmp_path / _JSON_FILENAME).write_text(json.dumps(data), encoding="utf-8")
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
        assert (migrated.stat().st_mode & 0o777) == 0o600

    def test_idempotent_when_sentinel_exists(self, tmp_path):
        (tmp_path / _JSON_FILENAME).write_text(
            json.dumps({"medium": {"status": "bound", "bound_at": None,
                                   "storage_state_path": None,
                                   "last_verified_at": None}}),
            encoding="utf-8",
        )
        (tmp_path / _SENTINEL_NAME).write_text("migrated", encoding="utf-8")
        store = _store(tmp_path)
        store.migrate_from_json(tmp_path)
        assert (tmp_path / _JSON_FILENAME).exists()  # untouched
        assert store.load() == {}

    def test_no_op_when_json_absent(self, tmp_path):
        store = _store(tmp_path)
        store.migrate_from_json(tmp_path)
        assert not (tmp_path / _SENTINEL_NAME).exists()
        assert store.load() == {}

    def test_corrupt_json_skipped_no_sentinel(self, tmp_path):
        (tmp_path / _JSON_FILENAME).write_text("not valid {", encoding="utf-8")
        store = _store(tmp_path)
        store.migrate_from_json(tmp_path)
        assert not (tmp_path / _SENTINEL_NAME).exists()
        assert (tmp_path / _JSON_FILENAME).exists()

    def test_crash_recovery_migrated_exists_no_sentinel(self, tmp_path):
        (tmp_path / (_JSON_FILENAME + ".migrated")).write_text("{}", encoding="utf-8")
        store = _store(tmp_path)
        store.migrate_from_json(tmp_path)
        assert (tmp_path / _SENTINEL_NAME).exists()
