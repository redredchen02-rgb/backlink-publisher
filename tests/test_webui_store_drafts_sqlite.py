"""Tests for DraftsSqliteStore (Unit 6) — drafts_store → webui.db ``drafts`` table.

Covers insert_first→get_item, update_item isolation, get_by_campaign_id WHERE,
bulk_delete/bulk_update counts, update_item absent→False, bulk_publish_now
partial failure + publish_fn raise (no re-raise), newest-first ordering, and
startup migration. Plus Store protocol compliance.

Plan: docs/plans/2026-06-03-008-refactor-webui-store-sqlite-unification-plan.md
"""

from __future__ import annotations

__tier__ = "integration"
import json
from pathlib import Path

from _mode_assertions import assert_file_mode
from webui_store.base import Store
from webui_store.drafts import (
    _JSON_FILENAME,
    _SENTINEL_NAME,
    DraftsSqliteStore,
)
from webui_store.sqlite_base import WebUIDatabase


def _store(tmp_path: Path) -> DraftsSqliteStore:
    return DraftsSqliteStore(WebUIDatabase(tmp_path / "webui.db"))


# ── Core Store protocol ───────────────────────────────────────────────────────

class TestDraftsSqliteStoreProtocol:
    def test_isinstance_store(self, tmp_path):
        assert isinstance(_store(tmp_path), Store)

    def test_load_returns_empty_list_when_absent(self, tmp_path):
        assert _store(tmp_path).load() == []

    def test_load_returns_list_not_none(self, tmp_path):
        assert isinstance(_store(tmp_path).load(), list)

    def test_save_and_load_roundtrip_preserves_order(self, tmp_path):
        store = _store(tmp_path)
        drafts = [{"id": f"d{i}", "status": "pending"} for i in range(5)]
        store.save(drafts)
        assert [d["id"] for d in store.load()] == [f"d{i}" for i in range(5)]

    def test_save_overwrites_previous(self, tmp_path):
        store = _store(tmp_path)
        store.save([{"id": "a"}])
        store.save([{"id": "b"}])
        assert [d["id"] for d in store.load()] == ["b"]

    def test_save_empty_list(self, tmp_path):
        store = _store(tmp_path)
        store.save([{"id": "a"}])
        store.save([])
        assert store.load() == []

    def test_update_roundtrip(self, tmp_path):
        store = _store(tmp_path)
        store.save([{"id": "d1"}])
        result = store.update(lambda ds: ds + [{"id": "d2"}])
        assert {d["id"] for d in result} == {"d1", "d2"}
        assert {d["id"] for d in store.load()} == {"d1", "d2"}


# ── insert_first / get_item / newest-first ordering ───────────────────────────

class TestInsertFirstOrdering:
    def test_insert_first_then_get_item(self, tmp_path):
        store = _store(tmp_path)
        item = {"id": "x", "campaign_id": "c1", "status": "draft"}
        store.insert_first(item)
        got = store.get_item("x")
        assert got["id"] == "x"
        assert got["status"] == "draft"

    def test_insert_first_returns_full_list(self, tmp_path):
        store = _store(tmp_path)
        store.save([{"id": "old"}])
        result = store.insert_first({"id": "new"})
        assert isinstance(result, list)
        assert {d["id"] for d in result} == {"old", "new"}

    def test_newest_first_ordering_preserved(self, tmp_path):
        store = _store(tmp_path)
        # Each insert_first stamps a fresh, later inserted_at → top of list.
        store.insert_first({"id": "first"})
        store.insert_first({"id": "second"})
        store.insert_first({"id": "third"})
        assert [d["id"] for d in store.load()] == ["third", "second", "first"]

    def test_get_item_absent_returns_none(self, tmp_path):
        store = _store(tmp_path)
        store.save([{"id": "a"}])
        assert store.get_item("zzz") is None


# ── update_item (targeted, isolation) ─────────────────────────────────────────

class TestUpdateItem:
    def test_mutates_only_target(self, tmp_path):
        store = _store(tmp_path)
        store.save([
            {"id": "a", "status": "pending", "x": 1},
            {"id": "b", "status": "pending", "x": 2},
        ])
        assert store.update_item("a", status="published") is True
        loaded = {d["id"]: d for d in store.load()}
        assert loaded["a"]["status"] == "published"
        assert loaded["a"]["x"] == 1
        assert loaded["b"] == {"id": "b", "status": "pending", "x": 2}

    def test_merges_new_keys(self, tmp_path):
        store = _store(tmp_path)
        store.save([{"id": "a", "status": "pending"}])
        store.update_item("a", error="boom", attempts=3)
        d = store.get_item("a")
        assert d["error"] == "boom"
        assert d["attempts"] == 3
        assert d["status"] == "pending"

    def test_absent_id_returns_false_no_write(self, tmp_path):
        store = _store(tmp_path)
        store.save([{"id": "a", "status": "pending"}])
        assert store.update_item("zzz", status="x") is False
        assert store.load() == [{"id": "a", "status": "pending"}]

    def test_absent_on_empty_store(self, tmp_path):
        store = _store(tmp_path)
        assert store.update_item("x", status="y") is False

    def test_preserves_order_after_update(self, tmp_path):
        store = _store(tmp_path)
        store.save([{"id": f"d{i}"} for i in range(5)])
        store.update_item("d2", status="done")
        assert [d["id"] for d in store.load()] == [f"d{i}" for i in range(5)]


# ── delete_item ──────────────────────────────────────────────────────────────

class TestDeleteItem:
    def test_removes(self, tmp_path):
        store = _store(tmp_path)
        store.save([{"id": "a"}, {"id": "b"}])
        assert store.delete_item("a") is True
        assert [d["id"] for d in store.load()] == ["b"]

    def test_absent_returns_false(self, tmp_path):
        store = _store(tmp_path)
        store.save([{"id": "a"}])
        assert store.delete_item("zzz") is False
        assert [d["id"] for d in store.load()] == ["a"]


# ── get_by_campaign_id (indexed WHERE) ────────────────────────────────────────

class TestGetByCampaignId:
    def test_returns_matching_only(self, tmp_path):
        store = _store(tmp_path)
        store.save([
            {"id": "a", "campaign_id": "c1"},
            {"id": "b", "campaign_id": "c1"},
            {"id": "c", "campaign_id": "c2"},
        ])
        assert {d["id"] for d in store.get_by_campaign_id("c1")} == {"a", "b"}

    def test_unknown_campaign_empty(self, tmp_path):
        store = _store(tmp_path)
        store.save([{"id": "a", "campaign_id": "c1"}])
        assert store.get_by_campaign_id("nope") == []

    def test_empty_store(self, tmp_path):
        assert _store(tmp_path).get_by_campaign_id("c1") == []

    def test_missing_campaign_id_field_excluded(self, tmp_path):
        store = _store(tmp_path)
        store.save([
            {"id": "a"},
            {"id": "b", "campaign_id": "c1"},
        ])
        assert [d["id"] for d in store.get_by_campaign_id("c1")] == ["b"]


# ── bulk_delete / bulk_update counts ──────────────────────────────────────────

class TestBulkDelete:
    def test_returns_deleted_count(self, tmp_path):
        store = _store(tmp_path)
        store.save([{"id": "a"}, {"id": "b"}, {"id": "c"}])
        assert store.bulk_delete(["a", "b"]) == 2
        assert [d["id"] for d in store.load()] == ["c"]

    def test_missing_ids_skipped(self, tmp_path):
        store = _store(tmp_path)
        store.save([{"id": "a"}])
        assert store.bulk_delete(["a", "zzz"]) == 1

    def test_empty_ids_noop(self, tmp_path):
        store = _store(tmp_path)
        store.save([{"id": "a"}])
        assert store.bulk_delete([]) == 0
        assert [d["id"] for d in store.load()] == ["a"]


class TestBulkUpdate:
    def test_returns_updated_count(self, tmp_path):
        store = _store(tmp_path)
        store.save([{"id": "a"}, {"id": "b"}])
        assert store.bulk_update(["a"], status="reviewing") == 1
        loaded = {d["id"]: d for d in store.load()}
        assert loaded["a"]["status"] == "reviewing"
        assert "status" not in loaded["b"]

    def test_partial_match(self, tmp_path):
        store = _store(tmp_path)
        store.save([{"id": "a"}, {"id": "b"}])
        assert store.bulk_update(["a", "zzz"], status="x") == 1

    def test_empty_ids_or_fields_noop(self, tmp_path):
        store = _store(tmp_path)
        store.save([{"id": "a", "status": "pending"}])
        assert store.bulk_update([], status="x") == 0
        assert store.bulk_update(["a"]) == 0
        assert store.load()[0]["status"] == "pending"


# ── bulk_publish_now ──────────────────────────────────────────────────────────

class TestBulkPublishNow:
    def test_all_success(self, tmp_path):
        store = _store(tmp_path)
        store.save([{"id": "a", "status": "draft"}, {"id": "b", "status": "draft"}])
        result = store.bulk_publish_now(["a", "b"], lambda d: {"ok": True})
        assert result == {"published": 2, "failed": 0, "errors": []}
        assert store.get_item("a")["status"] == "published"
        assert store.get_item("b")["status"] == "published"

    def test_partial_failure_marks_failed_and_continues(self, tmp_path):
        store = _store(tmp_path)
        store.save([
            {"id": "a", "status": "draft"},
            {"id": "b", "status": "draft"},
            {"id": "c", "status": "draft"},
        ])

        def _pub(d):
            if d["id"] == "b":
                return {"ok": False, "error": "rejected"}
            return {"ok": True}

        result = store.bulk_publish_now(["a", "b", "c"], _pub)
        assert result["published"] == 2
        assert result["failed"] == 1
        assert "b" in result["errors"][0]
        # The loop continued past the failure: c was still published.
        assert store.get_item("a")["status"] == "published"
        assert store.get_item("b")["status"] == "failed"
        assert store.get_item("c")["status"] == "published"

    def test_publish_fn_raises_marks_failed_no_reraise(self, tmp_path):
        store = _store(tmp_path)
        store.save([{"id": "a", "status": "draft"}])

        def _boom(_d):
            raise RuntimeError("network down")

        result = store.bulk_publish_now(["a"], _boom)  # must NOT raise
        assert result["published"] == 0
        assert result["failed"] == 1
        assert "network down" in result["errors"][0]
        assert store.get_item("a")["status"] == "failed"
        assert "network down" in store.get_item("a")["error"]

    def test_unknown_ids_skipped(self, tmp_path):
        store = _store(tmp_path)
        store.save([{"id": "a", "status": "draft"}])
        result = store.bulk_publish_now(["a", "ghost"], lambda d: {"ok": True})
        assert result == {"published": 1, "failed": 0, "errors": []}

    def test_empty_ids_noop(self, tmp_path):
        store = _store(tmp_path)
        store.save([{"id": "a", "status": "draft"}])
        result = store.bulk_publish_now([], lambda d: {"ok": True})
        assert result == {"published": 0, "failed": 0, "errors": []}
        assert store.get_item("a")["status"] == "draft"


# ── Startup migration ─────────────────────────────────────────────────────────

class TestStartupMigration:
    def test_migrates_preserving_order(self, tmp_path):
        drafts = [
            {"id": "d1", "campaign_id": "c1", "status": "pending"},
            {"id": "d2", "campaign_id": "c1", "status": "draft"},
            {"id": "d3", "campaign_id": "c2", "status": "done"},
        ]
        (tmp_path / _JSON_FILENAME).write_text(json.dumps(drafts), encoding="utf-8")
        store = _store(tmp_path)
        store.migrate_from_json(tmp_path)

        assert [d["id"] for d in store.load()] == ["d1", "d2", "d3"]
        assert (tmp_path / (_JSON_FILENAME + ".migrated")).exists()
        assert (tmp_path / _SENTINEL_NAME).exists()
        assert not (tmp_path / _JSON_FILENAME).exists()

    def test_migrated_file_chmod_600(self, tmp_path):
        (tmp_path / _JSON_FILENAME).write_text("[]", encoding="utf-8")
        store = _store(tmp_path)
        store.migrate_from_json(tmp_path)
        migrated = tmp_path / (_JSON_FILENAME + ".migrated")
        assert_file_mode(migrated, 0o600)

    def test_idempotent_when_sentinel_exists(self, tmp_path):
        (tmp_path / _JSON_FILENAME).write_text(
            json.dumps([{"id": "d1"}]), encoding="utf-8"
        )
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


# ── No duplicate method definitions ───────────────────────────────────────────

def test_no_duplicate_method_definitions():
    """Unit 6 requirement: get_by_campaign_id and bulk_publish_now were each
    defined twice in the JsonStore version; confirm one definition each now."""
    import ast
    import inspect

    import webui_store.drafts as mod

    src = inspect.getsource(mod)
    tree = ast.parse(src)
    cls = next(
        n for n in tree.body
        if isinstance(n, ast.ClassDef) and n.name == "DraftsSqliteStore"
    )

    def _is_property(fn: ast.FunctionDef) -> bool:
        for dec in fn.decorator_list:
            if isinstance(dec, ast.Name) and dec.id == "property":
                return True
            if isinstance(dec, ast.Attribute) and dec.attr == "setter":
                return True
        return False

    # Only plain methods (not property getter/setter pairs, which legitimately
    # share a name) — the 9 public CRUD methods + load/save/_init_table/etc.
    method_names = [
        n.name for n in cls.body
        if isinstance(n, ast.FunctionDef) and not _is_property(n)
    ]
    for name in method_names:
        assert method_names.count(name) == 1, f"duplicate def: {name}"

    # The two historically-duplicated methods are now defined exactly once.
    for once in ("get_by_campaign_id", "bulk_publish_now"):
        assert method_names.count(once) == 1, f"{once} not singular"
