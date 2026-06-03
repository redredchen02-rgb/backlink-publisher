"""Tests for DraftsStore — Plan 2026-06-02-001 U2 (bulk_publish_now, get_by_campaign_id).

Test scenarios:
- get_by_campaign_id returns only drafts matching campaign_id
- get_by_campaign_id with unknown campaign_id returns empty list
- bulk_publish_now with valid draft IDs publishes all and returns success count
- bulk_publish_now with mix of valid/invalid IDs reports partial failure
- bulk_publish_now with empty list returns 0 published (no-op)
- Draft status correctly transitions to published on success
- Draft status transitions to failed on callback error
- Callback exception is caught and reported
"""

from __future__ import annotations

from pathlib import Path

import pytest

from webui_store.drafts import DraftsStore


@pytest.fixture
def store(tmp_path: Path) -> DraftsStore:
    return DraftsStore(tmp_path / "drafts.json")


def _seed(store: DraftsStore, items: list[dict]) -> None:
    store.save(items)


# ── get_by_campaign_id ────────────────────────────────────────────────


class TestGetByCampaignId:
    def test_returns_matching_drafts(self, store: DraftsStore):
        _seed(store, [
            {"id": "a", "campaign_id": "c1", "status": "pending"},
            {"id": "b", "campaign_id": "c1", "status": "pending"},
            {"id": "c", "campaign_id": "c2", "status": "pending"},
        ])
        result = store.get_by_campaign_id("c1")
        assert [d["id"] for d in result] == ["a", "b"]

    def test_unknown_campaign_id_returns_empty(self, store: DraftsStore):
        _seed(store, [
            {"id": "a", "campaign_id": "c1", "status": "pending"},
        ])
        assert store.get_by_campaign_id("nonexistent") == []

    def test_empty_store_returns_empty(self, store: DraftsStore):
        assert store.get_by_campaign_id("c1") == []

    def test_drafts_missing_campaign_id_field(self, store: DraftsStore):
        _seed(store, [
            {"id": "a", "status": "pending"},
            {"id": "b", "campaign_id": "c1", "status": "pending"},
        ])
        result = store.get_by_campaign_id("c1")
        assert [d["id"] for d in result] == ["b"]

    def test_multiple_campaigns_return_correct_subsets(self, store: DraftsStore):
        _seed(store, [
            {"id": "1", "campaign_id": "c1"},
            {"id": "2", "campaign_id": "c2"},
            {"id": "3", "campaign_id": "c1"},
            {"id": "4", "campaign_id": "c3"},
        ])
        assert len(store.get_by_campaign_id("c1")) == 2
        assert len(store.get_by_campaign_id("c2")) == 1
        assert len(store.get_by_campaign_id("c3")) == 1
        assert len(store.get_by_campaign_id("c4")) == 0


# ── bulk_publish_now ──────────────────────────────────────────────────


class TestBulkPublishNow:
    def test_publish_all_success(self, store: DraftsStore):
        _seed(store, [
            {"id": "a", "campaign_id": "c1", "status": "draft"},
            {"id": "b", "campaign_id": "c1", "status": "draft"},
        ])
        result = store.bulk_publish_now(["a", "b"], publish_fn=lambda d: {"ok": True})
        assert result == {"published": 2, "failed": 0, "errors": []}
        assert store.get_item("a")["status"] == "published"
        assert store.get_item("b")["status"] == "published"

    def test_partial_failure(self, store: DraftsStore):
        _seed(store, [
            {"id": "a", "campaign_id": "c1", "status": "draft"},
            {"id": "b", "campaign_id": "c1", "status": "draft"},
            {"id": "c", "campaign_id": "c1", "status": "draft"},
        ])

        def _pub(draft: dict) -> dict:
            return {"ok": draft["id"] != "b", "error": "Platform rejected" if draft["id"] == "b" else None}

        result = store.bulk_publish_now(["a", "b", "c"], publish_fn=_pub)
        assert result["published"] == 2
        assert result["failed"] == 1
        assert len(result["errors"]) == 1
        assert "b" in result["errors"][0]
        assert store.get_item("a")["status"] == "published"
        assert store.get_item("b")["status"] == "failed"
        assert store.get_item("c")["status"] == "published"

    def test_empty_ids_returns_noop(self, store: DraftsStore):
        _seed(store, [{"id": "a", "status": "draft"}])
        result = store.bulk_publish_now([], publish_fn=lambda d: {"ok": True})
        assert result == {"published": 0, "failed": 0, "errors": []}
        assert store.get_item("a")["status"] == "draft"

    def test_callback_exception_caught(self, store: DraftsStore):
        _seed(store, [
            {"id": "a", "campaign_id": "c1", "status": "draft"},
        ])

        def _failing(_draft):
            raise RuntimeError("Network timeout")

        result = store.bulk_publish_now(["a"], publish_fn=_failing)
        assert result["published"] == 0
        assert result["failed"] == 1
        assert len(result["errors"]) == 1
        assert "Network timeout" in result["errors"][0]
        assert store.get_item("a")["status"] == "failed"
        assert "Network timeout" in store.get_item("a")["error"]

    def test_unknown_ids_are_skipped(self, store: DraftsStore):
        _seed(store, [
            {"id": "a", "campaign_id": "c1", "status": "draft"},
        ])
        result = store.bulk_publish_now(["a", "nonexistent"], publish_fn=lambda d: {"ok": True})
        # "a" succeeds, nonexistent is silently skipped
        assert result == {"published": 1, "failed": 0, "errors": []}

    def test_mixed_success_failure_error_detail(self, store: DraftsStore):
        _seed(store, [
            {"id": "ok1", "status": "draft"},
            {"id": "fail1", "status": "draft"},
            {"id": "ok2", "status": "draft"},
            {"id": "fail2", "status": "draft"},
        ])

        def _pub(d: dict) -> dict:
            if d["id"].startswith("fail"):
                return {"ok": False, "error": f"Publish failed for {d['id']}"}
            return {"ok": True}

        result = store.bulk_publish_now(
            ["ok1", "fail1", "ok2", "fail2"], publish_fn=_pub,
        )
        assert result == {
            "published": 2,
            "failed": 2,
            "errors": [
                "fail1: Publish failed for fail1",
                "fail2: Publish failed for fail2",
            ],
        }
