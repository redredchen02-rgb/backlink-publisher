"""Tests for CampaignStore (Plan 2026-06-02-001 U1).

Test scenarios:
- Create campaign returns valid campaign_id with pending status
- Get campaign by ID returns full schema
- Update status propagates correctly
- Update per-seed status updates progress_pct automatically
- List returns campaigns sorted by created_at desc
- Concurrent read/write does not corrupt data
- Persists across process restart (read back after store reload)
"""
from __future__ import annotations

__tier__ = "unit"
import json
from pathlib import Path
import re
import threading

import pytest

from webui_store.campaign_store import CampaignStore

# ── Helpers ───────────────────────────────────────────────────────────

_SEED_TEXT_PATTERN = re.compile(r"\d+\.\s.+")  # e.g. "1. seed content"


def _make_seeds(n: int = 3) -> list[dict]:
    return [{"seed_text": f"{i}. seed content for campaign"} for i in range(n)]


def _assert_valid_campaign(c: dict, *, check_seeds: int = 3) -> None:
    """Assert that a campaign dict has the expected schema."""
    assert isinstance(c, dict)
    assert re.match(r"^[0-9a-f-]{36}$", c["campaign_id"])
    assert c["status"] in (
        "pending", "running", "draft_review", "completed", "failed"
    )
    assert c["mode"] in ("draft", "publish")
    assert isinstance(c["platforms"], list)
    assert len(c["platforms"]) > 0
    assert isinstance(c["seeds"], list)
    assert len(c["seeds"]) == check_seeds
    assert 0.0 <= c["progress_pct"] <= 100.0
    assert c["created_at"] <= c["updated_at"]
    assert c["_schema_version"] == 1


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def store(tmp_path: Path) -> CampaignStore:
    """Create a CampaignStore backed by a temp JSON file."""
    return CampaignStore(tmp_path / "campaigns.json")


# ── Create ────────────────────────────────────────────────────────────


class TestCreate:
    def test_create_returns_valid_campaign_id(self, store: CampaignStore):
        seeds = _make_seeds(2)
        cid = store.create(mode="draft", platforms=["blogger"], seeds=seeds)
        assert re.match(r"^[0-9a-f-]{36}$", cid)

    def test_created_campaign_pending_status(self, store: CampaignStore):
        seeds = _make_seeds(2)
        cid = store.create(mode="draft", platforms=["blogger"], seeds=seeds)
        c = store.get(cid)
        assert c is not None
        assert c["status"] == "pending"
        assert c["progress_pct"] == 0.0
        assert c["result_summary"] is None

    def test_created_campaign_full_schema(self, store: CampaignStore):
        seeds = _make_seeds(3)
        cid = store.create(
            mode="publish",
            platforms=["blogger", "medium"],
            seeds=seeds,
            cap=5,
        )
        c = store.get(cid)
        _assert_valid_campaign(c, check_seeds=3)
        assert c["mode"] == "publish"
        assert c["platforms"] == ["blogger", "medium"]
        assert c["cap"] == 5
        assert c["progress_pct"] == 0.0
        for seed in c["seeds"]:
            assert seed["status"] == "idle"
            assert seed["error"] is None
            assert seed["draft_count"] == 0
            assert seed["published_count"] == 0

    def test_create_with_cap_none(self, store: CampaignStore):
        seeds = _make_seeds(1)
        cid = store.create(mode="draft", platforms=["blogger"], seeds=seeds)
        c = store.get(cid)
        assert c is not None
        assert c["cap"] is None

    def test_create_empty_seeds_raises(self, store: CampaignStore):
        with pytest.raises(ValueError, match="At least one seed"):
            store.create(mode="draft", platforms=["blogger"], seeds=[])

    def test_create_empty_platforms_raises(self, store: CampaignStore):
        seeds = _make_seeds(1)
        with pytest.raises(ValueError, match="At least one platform"):
            store.create(mode="draft", platforms=[], seeds=seeds)

    def test_create_invalid_mode_raises(self, store: CampaignStore):
        seeds = _make_seeds(1)
        with pytest.raises(ValueError, match="mode must be"):
            store.create(mode="invalid", platforms=["blogger"], seeds=seeds)

    def test_multiple_campaigns_unique_ids(self, store: CampaignStore):
        cid1 = store.create(mode="draft", platforms=["blogger"], seeds=_make_seeds(1))
        cid2 = store.create(mode="draft", platforms=["blogger"], seeds=_make_seeds(1))
        assert cid1 != cid2
        assert store.get(cid1) is not None
        assert store.get(cid2) is not None


# ── Get ───────────────────────────────────────────────────────────────


class TestGet:
    def test_get_existing(self, store: CampaignStore):
        cid = store.create(mode="draft", platforms=["blogger"], seeds=_make_seeds(2))
        c = store.get(cid)
        assert c is not None
        assert c["campaign_id"] == cid

    def test_get_nonexistent_returns_none(self, store: CampaignStore):
        assert store.get("nonexistent-id") is None

    def test_get_empty_store_returns_none(self, store: CampaignStore):
        assert store.get("some-id") is None

    def test_get_after_delete(self, store: CampaignStore):
        cid = store.create(mode="draft", platforms=["blogger"], seeds=_make_seeds(1))
        store.update_status(cid, status="completed")
        # Direct file manipulation: remove the campaign from the list
        def _remove(items):
            return [c for c in items if c.get("campaign_id") != cid]
        store.update(_remove)
        assert store.get(cid) is None


# ── Update Status ─────────────────────────────────────────────────────


class TestUpdateStatus:
    def test_update_status_propagates(self, store: CampaignStore):
        cid = store.create(mode="draft", platforms=["blogger"], seeds=_make_seeds(2))
        ok = store.update_status(cid, status="running")
        assert ok is True
        c = store.get(cid)
        assert c is not None
        assert c["status"] == "running"

    def test_update_progress_pct(self, store: CampaignStore):
        cid = store.create(mode="draft", platforms=["blogger"], seeds=_make_seeds(2))
        store.update_status(cid, progress_pct=50.0)
        c = store.get(cid)
        assert c is not None
        assert c["progress_pct"] == 50.0

    def test_update_progress_pct_clamped(self, store: CampaignStore):
        cid = store.create(mode="draft", platforms=["blogger"], seeds=_make_seeds(2))
        store.update_status(cid, progress_pct=150.0)
        c = store.get(cid)
        assert c["progress_pct"] == 100.0

        store.update_status(cid, progress_pct=-10.0)
        c = store.get(cid)
        assert c["progress_pct"] == 0.0

    def test_update_result_summary(self, store: CampaignStore):
        cid = store.create(mode="draft", platforms=["blogger"], seeds=_make_seeds(2))
        summary = {
            "total_seeds": 2,
            "successful_seeds": 2,
            "failed_seeds": 0,
            "total_drafts": 4,
            "platform_breakdown": {"blogger": {"success": 2, "failed": 0}},
        }
        store.update_status(cid, result_summary=summary)
        c = store.get(cid)
        assert c is not None
        assert c["result_summary"] == summary

    def test_update_status_invalid_value_raises(self, store: CampaignStore):
        cid = store.create(mode="draft", platforms=["blogger"], seeds=_make_seeds(2))
        with pytest.raises(ValueError, match="campaign status"):
            store.update_status(cid, status="invalid_status")

    def test_update_nonexistent_returns_false(self, store: CampaignStore):
        ok = store.update_status("no-such-id", status="completed")
        assert ok is False

    def test_update_empty_kwargs_returns_false(self, store: CampaignStore):
        cid = store.create(mode="draft", platforms=["blogger"], seeds=_make_seeds(2))
        ok = store.update_status(cid)
        assert ok is False

    def test_update_updates_timestamp(self, store: CampaignStore):
        cid = store.create(mode="draft", platforms=["blogger"], seeds=_make_seeds(2))
        c_before = store.get(cid)
        import time
        time.sleep(0.01)  # ensure clock tick
        store.update_status(cid, status="running")
        c_after = store.get(cid)
        assert c_after["updated_at"] > c_before["updated_at"]


# ── Update Seed Status ────────────────────────────────────────────────


class TestUpdateSeedStatus:
    def test_update_seed_status_propagates(self, store: CampaignStore):
        seeds = _make_seeds(3)
        cid = store.create(mode="draft", platforms=["blogger"], seeds=seeds)
        ok = store.update_seed_status(cid, 0, status="processing")
        assert ok is True
        c = store.get(cid)
        assert c is not None
        assert c["seeds"][0]["status"] == "processing"

    def test_update_seed_draft_count(self, store: CampaignStore):
        seeds = _make_seeds(2)
        cid = store.create(mode="draft", platforms=["blogger"], seeds=seeds)
        store.update_seed_status(cid, 0, draft_count=3)
        c = store.get(cid)
        assert c["seeds"][0]["draft_count"] == 3

    def test_update_seed_error(self, store: CampaignStore):
        seeds = _make_seeds(2)
        cid = store.create(mode="draft", platforms=["blogger"], seeds=seeds)
        store.update_seed_status(cid, 1, status="failed", error="Platform rejected")
        c = store.get(cid)
        assert c["seeds"][1]["status"] == "failed"
        assert c["seeds"][1]["error"] == "Platform rejected"

    def test_progress_pct_updates_automatically(self, store: CampaignStore):
        seeds = _make_seeds(4)
        cid = store.create(mode="draft", platforms=["blogger"], seeds=seeds)

        # 0/4 done → 0%
        assert store.get(cid)["progress_pct"] == 0.0

        # 1/4 done → 25%
        store.update_seed_status(cid, 0, status="success")
        assert store.get(cid)["progress_pct"] == 25.0

        # 2/4 done → 50%
        store.update_seed_status(cid, 1, status="success")
        assert store.get(cid)["progress_pct"] == 50.0

        # 3/4 done → 75%
        store.update_seed_status(cid, 2, status="failed")
        assert store.get(cid)["progress_pct"] == 75.0

        # 4/4 done → 100%
        store.update_seed_status(cid, 3, status="skipped")
        assert store.get(cid)["progress_pct"] == 100.0

    def test_update_nonexistent_seed_returns_false(self, store: CampaignStore):
        seeds = _make_seeds(2)
        cid = store.create(mode="draft", platforms=["blogger"], seeds=seeds)
        ok = store.update_seed_status(cid, 99, status="success")
        assert ok is False

    def test_update_seed_invalid_status_raises(self, store: CampaignStore):
        seeds = _make_seeds(2)
        cid = store.create(mode="draft", platforms=["blogger"], seeds=seeds)
        with pytest.raises(ValueError, match="seed status"):
            store.update_seed_status(cid, 0, status="invalid_seed_status")

    def test_update_seed_empty_kwargs_returns_false(self, store: CampaignStore):
        seeds = _make_seeds(2)
        cid = store.create(mode="draft", platforms=["blogger"], seeds=seeds)
        ok = store.update_seed_status(cid, 0)
        assert ok is False


# ── List ──────────────────────────────────────────────────────────────


class TestList:
    def test_list_empty(self, store: CampaignStore):
        assert store.list() == []

    def test_list_sorted_by_created_at_desc(self, store: CampaignStore):
        import time
        cid1 = store.create(mode="draft", platforms=["blogger"], seeds=_make_seeds(1))
        time.sleep(0.01)
        cid2 = store.create(mode="draft", platforms=["blogger"], seeds=_make_seeds(1))
        time.sleep(0.01)
        cid3 = store.create(mode="draft", platforms=["blogger"], seeds=_make_seeds(1))

        campaigns = store.list()
        assert len(campaigns) == 3
        # Newest first
        assert campaigns[0]["campaign_id"] == cid3
        assert campaigns[1]["campaign_id"] == cid2
        assert campaigns[2]["campaign_id"] == cid1

    def test_list_full_schema_each_entry(self, store: CampaignStore):
        store.create(mode="draft", platforms=["blogger"], seeds=_make_seeds(2))
        store.create(mode="publish", platforms=["medium"], seeds=_make_seeds(3))
        campaigns = store.list()
        for c in campaigns:
            _assert_valid_campaign(c, check_seeds=len(c["seeds"]))

    def test_list_multiple_campaigns_count(self, store: CampaignStore):
        for _ in range(5):
            store.create(mode="draft", platforms=["blogger"], seeds=_make_seeds(2))
        assert len(store.list()) == 5


# ── Persistence ───────────────────────────────────────────────────────


class TestPersistence:
    def test_read_back_after_store_reload(self, tmp_path: Path):
        path = tmp_path / "campaigns.json"
        store1 = CampaignStore(path)
        cid = store1.create(mode="draft", platforms=["blogger"], seeds=_make_seeds(2))
        store1.update_seed_status(cid, 0, status="success")
        store1.update_status(cid, status="running")

        # Reload from same file (simulates process restart)
        store2 = CampaignStore(path)
        campaigns = store2.list()
        assert len(campaigns) == 1
        c = store2.get(cid)
        assert c is not None
        assert c["status"] == "running"
        assert c["seeds"][0]["status"] == "success"

    def test_persisted_row_roundtrips(self, tmp_path: Path):
        # SQLite-backed: persistence is verified by reopening the store
        # against the same db file rather than reading raw JSON off disk.
        path = tmp_path / "webui.db"
        store = CampaignStore(path)
        cid = store.create(mode="draft", platforms=["blogger"], seeds=_make_seeds(2))
        store.update_status(cid, status="completed")

        reopened = CampaignStore(path)
        rows = reopened.list()
        assert isinstance(rows, list)
        assert len(rows) == 1
        assert rows[0]["campaign_id"] == cid
        assert rows[0]["status"] == "completed"

    def test_empty_db_falls_back_to_empty(self, tmp_path: Path):
        # A freshly-created db (no campaigns) loads as an empty list.
        path = tmp_path / "webui.db"
        store = CampaignStore(path)
        assert store.list() == []


# ── Concurrency ───────────────────────────────────────────────────────


class TestConcurrency:
    def test_concurrent_writes_no_corruption(self, store: CampaignStore):
        """Two threads writing different campaigns should not lose data."""
        n = 10
        cid1 = store.create(mode="draft", platforms=["blogger"], seeds=_make_seeds(1))
        cid2 = store.create(mode="draft", platforms=["blogger"], seeds=_make_seeds(1))
        errors = []

        def writer1():
            try:
                for i in range(n):
                    store.update_seed_status(cid1, 0, draft_count=i)
            except Exception as e:
                errors.append(f"w1: {e}")

        def writer2():
            try:
                for i in range(n):
                    store.update_seed_status(cid2, 0, published_count=i)
            except Exception as e:
                errors.append(f"w2: {e}")

        t1 = threading.Thread(target=writer1)
        t2 = threading.Thread(target=writer2)
        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

        assert not errors, f"Concurrent write errors: {errors}"
        c1 = store.get(cid1)
        c2 = store.get(cid2)
        assert c1 is not None
        assert c2 is not None
        assert c1["seeds"][0]["draft_count"] == n - 1
        assert c2["seeds"][0]["published_count"] == n - 1

    def test_read_during_write_no_corruption(self, store: CampaignStore):
        """Reads from store while a write is happening should never see partial state."""
        cid = store.create(
            mode="draft",
            platforms=["blogger"],
            seeds=_make_seeds(5),
        )
        errors = []

        def writer():
            try:
                for i in range(50):
                    idx = i % 5
                    store.update_seed_status(
                        cid, idx, draft_count=i, status="processing",
                    )
                store.update_seed_status(cid, 0, status="success")
            except Exception as e:
                errors.append(f"w: {e}")

        def reader():
            try:
                for _ in range(20):
                    c = store.get(cid)
                    if c is not None:
                        for seed in c["seeds"]:
                            assert isinstance(seed["draft_count"], int)
            except Exception as e:
                errors.append(f"r: {e}")

        t1 = threading.Thread(target=writer)
        t2 = threading.Thread(target=reader)
        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

        assert not errors, f"Read/write errors: {errors}"
        c = store.get(cid)
        assert c["seeds"][0]["status"] == "success"
