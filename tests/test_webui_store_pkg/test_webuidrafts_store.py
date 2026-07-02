"""Tests for webui_store.drafts — DraftsSqliteStore.

Plan 2026-06-30 Phase 3+ T3.6: webui_store test coverage expansion.
"""

from __future__ import annotations

__tier__ = "unit"

from pathlib import Path
from typing import Any

import pytest

from webui_store.drafts import DraftsSqliteStore, DraftsStore
from webui_store.sqlite_base import WebUIDatabase


@pytest.fixture
def drafts(tmp_path: Path) -> DraftsSqliteStore:
    return DraftsSqliteStore(WebUIDatabase(tmp_path / "webui.db"))


def _make_draft(item_id: str, **overrides: Any) -> dict:
    return {
        "id": item_id,
        "campaign_id": "test-campaign",
        "status": "draft",
        "title": f"Article {item_id}",
        **overrides,
    }


class TestDraftsSqliteStore:
    """DraftsSqliteStore unit tests."""

    # ── Store protocol ─────────────────────────────────────────────────────

    def test_load_returns_empty_list_when_empty(self, drafts: DraftsSqliteStore) -> None:
        assert drafts.load() == []

    def test_save_and_load_round_trip(self, drafts: DraftsSqliteStore) -> None:
        items = [_make_draft("1"), _make_draft("2")]
        drafts.save(items)
        loaded = drafts.load()
        assert len(loaded) == 2

    def test_load_returns_newest_first(self, drafts: DraftsSqliteStore) -> None:
        """load() returns drafts ordered by inserted_at DESC (newest first)."""
        drafts.save([
            _make_draft("a", inserted_at=100),
            _make_draft("b", inserted_at=200),
            _make_draft("c", inserted_at=300),
        ])
        loaded = drafts.load()
        assert [d["id"] for d in loaded] == ["c", "b", "a"]

    def test_save_overwrites_existing(self, drafts: DraftsSqliteStore) -> None:
        drafts.save([_make_draft("1")])
        drafts.save([_make_draft("2")])
        loaded = drafts.load()
        assert len(loaded) == 1
        assert loaded[0]["id"] == "2"

    def test_update_atomic(self, drafts: DraftsSqliteStore) -> None:
        drafts.save([_make_draft("1")])

        def add_item(data: list) -> list:
            data.append(_make_draft("2"))
            return data

        result = drafts.update(add_item)
        assert len(result) == 2

    def test_update_returns_new_value(self, drafts: DraftsSqliteStore) -> None:
        result = drafts.update(lambda data: data + [_make_draft("1")])
        assert len(result) == 1

    # ── get_item ───────────────────────────────────────────────────────────

    def test_get_item_returns_draft(self, drafts: DraftsSqliteStore) -> None:
        drafts.save([_make_draft("1", title="Hello")])
        item = drafts.get_item("1")
        assert item is not None
        assert item["title"] == "Hello"

    def test_get_item_returns_none_for_missing(self, drafts: DraftsSqliteStore) -> None:
        assert drafts.get_item("nonexistent") is None

    # ── update_item ────────────────────────────────────────────────────────

    def test_update_item_merges_fields(self, drafts: DraftsSqliteStore) -> None:
        drafts.save([_make_draft("1", status="draft")])
        drafts.update_item("1", status="published")
        item = drafts.get_item("1")
        assert item is not None
        assert item["status"] == "published"
        assert item["title"] == "Article 1"  # unchanged

    def test_update_item_returns_false_for_missing(self, drafts: DraftsSqliteStore) -> None:
        assert drafts.update_item("nonexistent", status="published") is False

    # ── delete_item ────────────────────────────────────────────────────────

    def test_delete_item_removes_draft(self, drafts: DraftsSqliteStore) -> None:
        drafts.save([_make_draft("1")])
        assert drafts.delete_item("1") is True
        assert drafts.get_item("1") is None

    def test_delete_item_returns_false_for_missing(self, drafts: DraftsSqliteStore) -> None:
        assert drafts.delete_item("nonexistent") is False

    # ── insert_first ───────────────────────────────────────────────────────

    def test_insert_first_prepends(self, drafts: DraftsSqliteStore) -> None:
        drafts.save([_make_draft("b", inserted_at=100)])
        result = drafts.insert_first(_make_draft("a"))
        assert result[0]["id"] == "a"

    def test_insert_first_into_empty(self, drafts: DraftsSqliteStore) -> None:
        result = drafts.insert_first(_make_draft("first"))
        assert len(result) == 1
        assert result[0]["id"] == "first"

    def test_insert_first_timestamp_ordering(self, drafts: DraftsSqliteStore) -> None:
        """insert_first gives the new item a higher inserted_at than existing max."""
        drafts.save([_make_draft("existing", inserted_at=500)])
        result = drafts.insert_first(_make_draft("newcomer"))
        assert result[0]["id"] == "newcomer"

    # ── get_by_campaign_id ─────────────────────────────────────────────────

    def test_get_by_campaign_id_filters(self, drafts: DraftsSqliteStore) -> None:
        drafts.save([
            _make_draft("a", campaign_id="camp-1"),
            _make_draft("b", campaign_id="camp-2"),
            _make_draft("c", campaign_id="camp-1"),
        ])
        camp1 = drafts.get_by_campaign_id("camp-1")
        assert len(camp1) == 2
        assert all(d["campaign_id"] == "camp-1" for d in camp1)

    def test_get_by_campaign_id_returns_empty_list_when_no_match(
        self, drafts: DraftsSqliteStore
    ) -> None:
        assert drafts.get_by_campaign_id("nonexistent") == []

    def test_get_by_campaign_id_newest_first(self, drafts: DraftsSqliteStore) -> None:
        drafts.save([
            _make_draft("old", campaign_id="c", inserted_at=100),
            _make_draft("new", campaign_id="c", inserted_at=200),
        ])
        result = drafts.get_by_campaign_id("c")
        assert result[0]["id"] == "new"

    # ── bulk_delete ────────────────────────────────────────────────────────

    def test_bulk_delete_removes_multiple(self, drafts: DraftsSqliteStore) -> None:
        drafts.save([_make_draft(f"{i}") for i in range(5)])
        count = drafts.bulk_delete(["0", "2", "4"])
        assert count == 3
        assert drafts.get_item("0") is None
        assert drafts.get_item("1") is not None

    def test_bulk_delete_returns_zero_for_empty_list(
        self, drafts: DraftsSqliteStore
    ) -> None:
        assert drafts.bulk_delete([]) == 0

    # ── bulk_update ────────────────────────────────────────────────────────

    def test_bulk_update_merges_fields(self, drafts: DraftsSqliteStore) -> None:
        drafts.save([_make_draft("x"), _make_draft("y")])
        count = drafts.bulk_update(["x", "y"], status="archived")
        assert count == 2
        assert drafts.get_item("x")["status"] == "archived"
        assert drafts.get_item("y")["status"] == "archived"

    def test_bulk_update_returns_zero_for_empty(self, drafts: DraftsSqliteStore) -> None:
        assert drafts.bulk_update([], status="x") == 0

    def test_bulk_update_unknown_ids(self, drafts: DraftsSqliteStore) -> None:
        assert drafts.bulk_update(["unknown"], status="x") == 0

    # ── bulk_publish_now ────────────────────────────────────────────────────

    def test_bulk_publish_now_publishes(self, drafts: DraftsSqliteStore) -> None:
        drafts.save([_make_draft("pub-me"), _make_draft("pub-me-too")])

        def publish_fn(draft: dict) -> dict:
            return {"ok": True, "url": f"https://example.com/{draft['id']}"}

        result = drafts.bulk_publish_now(["pub-me", "pub-me-too"], publish_fn)
        assert result["published"] == 2
        assert result["failed"] == 0
        assert drafts.get_item("pub-me")["status"] == "published"

    def test_bulk_publish_now_partial_failure(self, drafts: DraftsSqliteStore) -> None:
        drafts.save([_make_draft("ok"), _make_draft("fail")])

        def publish_fn(draft: dict) -> dict:
            if draft["id"] == "fail":
                return {"ok": False, "error": "adapter rejected"}
            return {"ok": True}

        result = drafts.bulk_publish_now(["ok", "fail"], publish_fn)
        assert result["published"] == 1
        assert result["failed"] == 1
        assert drafts.get_item("fail")["status"] == "failed"

    def test_bulk_publish_now_exception_handling(self, drafts: DraftsSqliteStore) -> None:
        drafts.save([_make_draft("crash")])

        def publish_fn(draft: dict) -> dict:
            raise RuntimeError("simulated crash")

        result = drafts.bulk_publish_now(["crash"], publish_fn)
        assert result["published"] == 0
        assert result["failed"] == 1

    # ── backward compat ────────────────────────────────────────────────────

    def test_drafts_store_alias(self) -> None:
        """DraftsStore is a backward-compat alias for DraftsSqliteStore."""
        assert DraftsStore is DraftsSqliteStore

    def test_path_property(self, tmp_path: Path) -> None:
        store = DraftsSqliteStore(WebUIDatabase(tmp_path / "webui.db"))
        assert store.path == tmp_path / "webui.db"
