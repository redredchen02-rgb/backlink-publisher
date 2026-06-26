"""Tests for CampaignSqliteStore (Unit 7) — campaign_store → webui.db ``campaigns`` table.

Verifies create→get with seeds, update_status, single-transaction
update_seed_status with progress recompute, get-nonexistent, startup migration
(completeness + seed arrays preserved), validation, Store protocol compliance,
and concurrent update_seed_status on different seeds.

Plan: docs/plans/2026-06-03-008-refactor-webui-store-sqlite-unification-plan.md
"""

from __future__ import annotations

__tier__ = "integration"
import json
from pathlib import Path
import threading

import pytest

from webui_store.base import Store
from webui_store.campaign_store import (
    _JSON_FILENAME,
    _SENTINEL_NAME,
    CampaignSqliteStore,
)
from webui_store.sqlite_base import WebUIDatabase


def _store(tmp_path: Path) -> CampaignSqliteStore:
    return CampaignSqliteStore(WebUIDatabase(tmp_path / "webui.db"))


def _seeds(n: int = 3) -> list[dict]:
    return [{"seed_text": f"{i}. seed"} for i in range(n)]


# ── Store protocol ─────────────────────────────────────────────────────

class TestProtocol:
    def test_isinstance_store(self, tmp_path):
        assert isinstance(_store(tmp_path), Store)

    def test_load_empty(self, tmp_path):
        assert _store(tmp_path).load() == []

    def test_accepts_path_backcompat(self, tmp_path):
        store = CampaignSqliteStore(tmp_path / "webui.db")
        assert store.load() == []


# ── create → get ───────────────────────────────────────────────────────

class TestCreateGet:
    def test_create_get_with_seeds(self, tmp_path):
        store = _store(tmp_path)
        cid = store.create(mode="publish", platforms=["a", "b"], seeds=_seeds(3))
        c = store.get(cid)
        assert c is not None
        assert c["campaign_id"] == cid
        assert c["status"] == "pending"
        assert c["mode"] == "publish"
        assert c["platforms"] == ["a", "b"]
        assert len(c["seeds"]) == 3
        assert [s["seed_index"] for s in c["seeds"]] == [0, 1, 2]
        assert all(s["status"] == "idle" for s in c["seeds"])

    def test_get_nonexistent_returns_none(self, tmp_path):
        assert _store(tmp_path).get("no-such") is None

    def test_create_empty_seeds_raises(self, tmp_path):
        with pytest.raises(ValueError, match="At least one seed"):
            _store(tmp_path).create(mode="draft", platforms=["a"], seeds=[])

    def test_create_bad_mode_raises(self, tmp_path):
        with pytest.raises(ValueError, match="mode must be"):
            _store(tmp_path).create(mode="x", platforms=["a"], seeds=_seeds(1))


# ── update_status ──────────────────────────────────────────────────────

class TestUpdateStatus:
    def test_sets_status_and_updated_at(self, tmp_path):
        store = _store(tmp_path)
        cid = store.create(mode="draft", platforms=["a"], seeds=_seeds(2))
        before = store.get(cid)["updated_at"]
        import time
        time.sleep(0.01)
        assert store.update_status(cid, status="running") is True
        c = store.get(cid)
        assert c["status"] == "running"
        assert c["updated_at"] > before

    def test_invalid_status_raises(self, tmp_path):
        store = _store(tmp_path)
        cid = store.create(mode="draft", platforms=["a"], seeds=_seeds(1))
        with pytest.raises(ValueError, match="campaign status"):
            store.update_status(cid, status="bogus")

    def test_nonexistent_returns_false(self, tmp_path):
        assert _store(tmp_path).update_status("nope", status="completed") is False

    def test_column_mirror_used_for_ordering(self, tmp_path):
        # status column is mirrored — verify a queryable column reflects updates.
        store = _store(tmp_path)
        cid = store.create(mode="draft", platforms=["a"], seeds=_seeds(1))
        store.update_status(cid, status="completed")
        db = WebUIDatabase(tmp_path / "webui.db")
        with db.connect() as conn:
            row = conn.execute(
                "SELECT status FROM campaigns WHERE id = ?", (cid,)
            ).fetchone()
        assert row[0] == "completed"


# ── update_seed_status ─────────────────────────────────────────────────

class TestUpdateSeedStatus:
    def test_updates_seed_and_recomputes_progress(self, tmp_path):
        store = _store(tmp_path)
        cid = store.create(mode="draft", platforms=["a"], seeds=_seeds(4))
        assert store.update_seed_status(cid, 0, status="success") is True
        c = store.get(cid)
        assert c["seeds"][0]["status"] == "success"
        assert c["progress_pct"] == 25.0
        # Other seeds untouched.
        assert all(s["status"] == "idle" for s in c["seeds"][1:])

    def test_full_progress(self, tmp_path):
        store = _store(tmp_path)
        cid = store.create(mode="draft", platforms=["a"], seeds=_seeds(2))
        store.update_seed_status(cid, 0, status="success")
        store.update_seed_status(cid, 1, status="failed")
        assert store.get(cid)["progress_pct"] == 100.0

    def test_invalid_seed_status_raises(self, tmp_path):
        store = _store(tmp_path)
        cid = store.create(mode="draft", platforms=["a"], seeds=_seeds(2))
        with pytest.raises(ValueError, match="seed status"):
            store.update_seed_status(cid, 0, status="bogus")

    def test_nonexistent_seed_returns_false(self, tmp_path):
        store = _store(tmp_path)
        cid = store.create(mode="draft", platforms=["a"], seeds=_seeds(2))
        assert store.update_seed_status(cid, 99, status="success") is False

    def test_concurrent_different_seeds(self, tmp_path):
        store = _store(tmp_path)
        cid = store.create(mode="draft", platforms=["a"], seeds=_seeds(2))
        errors: list[str] = []

        def w(idx, key):
            try:
                for i in range(20):
                    store.update_seed_status(cid, idx, **{key: i})
            except Exception as e:  # noqa: BLE001
                errors.append(str(e))

        t1 = threading.Thread(target=w, args=(0, "draft_count"))
        t2 = threading.Thread(target=w, args=(1, "published_count"))
        t1.start(); t2.start()
        t1.join(timeout=10); t2.join(timeout=10)

        assert not errors, errors
        c = store.get(cid)
        assert c["seeds"][0]["draft_count"] == 19
        assert c["seeds"][1]["published_count"] == 19


# ── list ordering ──────────────────────────────────────────────────────

class TestList:
    def test_sorted_created_at_desc(self, tmp_path):
        import time
        store = _store(tmp_path)
        c1 = store.create(mode="draft", platforms=["a"], seeds=_seeds(1))
        time.sleep(0.01)
        c2 = store.create(mode="draft", platforms=["a"], seeds=_seeds(1))
        ids = [c["campaign_id"] for c in store.list()]
        assert ids == [c2, c1]


# ── Startup migration ──────────────────────────────────────────────────

class TestMigration:
    def test_migration_preserves_campaigns_and_seeds(self, tmp_path):
        legacy = [
            {
                "campaign_id": "c1",
                "status": "running",
                "mode": "draft",
                "platforms": ["a"],
                "cap": None,
                "_schema_version": 1,
                "created_at": "2026-01-01T00:00:00+00:00",
                "updated_at": "2026-01-02T00:00:00+00:00",
                "seeds": [
                    {"seed_index": 0, "seed_text": "s0", "status": "success",
                     "error": None, "draft_count": 2, "published_count": 1},
                    {"seed_index": 1, "seed_text": "s1", "status": "idle",
                     "error": None, "draft_count": 0, "published_count": 0},
                ],
                "progress_pct": 50.0,
                "result_summary": None,
            },
        ]
        (tmp_path / _JSON_FILENAME).write_text(
            json.dumps(legacy), encoding="utf-8"
        )

        store = _store(tmp_path)
        store.migrate_from_json(tmp_path)

        c = store.get("c1")
        assert c is not None
        assert c["status"] == "running"
        assert c["progress_pct"] == 50.0
        assert len(c["seeds"]) == 2
        assert c["seeds"][0]["status"] == "success"
        assert c["seeds"][0]["draft_count"] == 2
        # Sentinel written; original renamed.
        assert (tmp_path / _SENTINEL_NAME).exists()
        assert not (tmp_path / _JSON_FILENAME).exists()
        assert (tmp_path / "campaigns.json.migrated").exists()

    def test_migration_idempotent(self, tmp_path):
        (tmp_path / _JSON_FILENAME).write_text("[]", encoding="utf-8")
        store = _store(tmp_path)
        store.migrate_from_json(tmp_path)
        # Second call is a no-op (sentinel present).
        store.migrate_from_json(tmp_path)
        assert store.list() == []

    def test_migration_absent_json_noop(self, tmp_path):
        store = _store(tmp_path)
        store.migrate_from_json(tmp_path)
        assert not (tmp_path / _SENTINEL_NAME).exists()
        assert store.list() == []
