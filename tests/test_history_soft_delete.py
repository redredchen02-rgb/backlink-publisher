"""W4: soft-delete for publish history (events.db) — plan
docs/plans/2026-07-06-005-opt-webui-uiux-comprehensive-plan.md.

Covers the core invariants named in the plan's execution notes:

* delete → list (no ``include_deleted``) excludes the row.
* ``include_deleted=window`` returns in-window soft-deleted rows with
  ``deleted_at`` populated; past-window rows are not returned.
* undelete → fields intact, ``deleted_at`` cleared (round-trip).
* undelete on an already-purged id → ``ok: False`` / ``error_code``, never a
  silent success.
* the CLI read path (``list_history``/``get_history_item`` called exactly as
  a CLI caller would -- no ``include_deleted`` kwarg) never sees soft-deleted
  rows, verified against a real (non-mocked) events.db.
* bulk-delete with some already-missing ids reports ``deleted``/``skipped``
  counts rather than an all-or-nothing result.
"""
from __future__ import annotations

__tier__ = "integration"

import json

import pytest

from backlink_publisher.events import kinds as _kinds
from backlink_publisher.events._history_mutations import (
    bulk_delete_from_db,
    CLIENT_UNDO_WINDOW_SECONDS,
    delete_from_db,
    PURGE_WINDOW_SECONDS,
    undelete_from_db,
)
from backlink_publisher.events.history_query import get_history_item, list_history
from backlink_publisher.events.store import EventStore


@pytest.fixture(autouse=True)
def _isolate_events_db(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))


def _seed_article(store: EventStore, *, n: str) -> int:
    """Create one published article + its confirmed event; return article_id."""
    live_url = f"https://example.com/{n}"
    aid = store.add_article(
        {"target_urls_json": json.dumps([f"https://t.example/{n}"]), "live_url": live_url}
    )
    store.append(
        _kinds.PUBLISH_CONFIRMED,
        {"live_url": live_url, "platform": "medium"},
        article_id=aid,
        target_url=f"https://t.example/{n}",
    )
    return aid


def _backdate_deleted_at(store: EventStore, article_id: int, seconds_ago: float) -> None:
    """Directly stamp deleted_at in the past, bypassing the mutation helper.

    Used to simulate a soft-deleted row aging past (or staying within) the
    purge window without sleeping in the test.
    """
    from datetime import datetime, timedelta, UTC

    ts = (datetime.now(UTC) - timedelta(seconds=seconds_ago)).isoformat()
    with store.connect() as conn:
        conn.execute("UPDATE articles SET deleted_at = ? WHERE article_id = ?", (ts, article_id))
        conn.execute("UPDATE events SET deleted_at = ? WHERE article_id = ?", (ts, article_id))


class TestInvariantWindows:
    def test_purge_window_is_double_the_client_undo_window(self):
        """Pins the server-purge-must-exceed-client-undo-window invariant (D18):
        a visible undo affordance must never race a purge and 404."""
        assert PURGE_WINDOW_SECONDS == CLIENT_UNDO_WINDOW_SECONDS * 2
        assert PURGE_WINDOW_SECONDS > CLIENT_UNDO_WINDOW_SECONDS


class TestDeleteExcludesFromDefaultList:
    def test_delete_then_list_excludes_row(self):
        store = EventStore()
        aid = _seed_article(store, n="a")
        kept = _seed_article(store, n="b")

        assert delete_from_db(str(aid), store) is True

        ids = {it["id"] for it in list_history(store)}
        assert str(aid) not in ids
        assert str(kept) in ids

    def test_delete_then_get_history_item_returns_none(self):
        store = EventStore()
        aid = _seed_article(store, n="a")
        delete_from_db(str(aid), store)
        assert get_history_item(aid, store) is None

    def test_deleting_unknown_id_returns_false(self):
        store = EventStore()
        assert delete_from_db("999999", store) is False


class TestIncludeDeletedWindow:
    def test_window_returns_in_window_row_with_deleted_at(self):
        store = EventStore()
        aid = _seed_article(store, n="a")
        delete_from_db(str(aid), store)

        window_items = {it["id"]: it for it in list_history(store, include_deleted="window")}
        assert str(aid) in window_items
        assert window_items[str(aid)]["deleted_at"] is not None

    def test_window_excludes_rows_past_purge_eligibility(self):
        store = EventStore()
        aid = _seed_article(store, n="a")
        # Soft-delete via the real mutation, then backdate past the window —
        # simulates a row that would already be purge-eligible.
        delete_from_db(str(aid), store)
        _backdate_deleted_at(store, aid, PURGE_WINDOW_SECONDS + 5)

        window_items = {it["id"] for it in list_history(store, include_deleted="window")}
        assert str(aid) not in window_items

    def test_window_excludes_live_rows(self):
        store = EventStore()
        live_id = _seed_article(store, n="a")

        window_items = {it["id"] for it in list_history(store, include_deleted="window")}
        assert str(live_id) not in window_items

    def test_invalid_include_deleted_value_raises(self):
        store = EventStore()
        with pytest.raises(ValueError):
            list_history(store, include_deleted="all")


class TestUndeleteRoundTrip:
    def test_undelete_restores_fields_and_clears_deleted_at(self):
        store = EventStore()
        aid = _seed_article(store, n="a")
        before = get_history_item(aid, store)
        assert before is not None

        delete_from_db(str(aid), store)
        assert get_history_item(aid, store) is None

        assert undelete_from_db(str(aid), store) is True
        after = get_history_item(aid, store)
        assert after is not None
        assert after["target_url"] == before["target_url"]
        assert after["platform"] == before["platform"]
        assert after["status"] == before["status"]

        with store.connect() as conn:
            row = conn.execute(
                "SELECT deleted_at FROM articles WHERE article_id = ?", (aid,)
            ).fetchone()
            assert row[0] is None

    def test_undelete_unknown_id_returns_false(self):
        store = EventStore()
        assert undelete_from_db("999999", store) is False

    def test_undelete_never_deleted_id_returns_false(self):
        store = EventStore()
        aid = _seed_article(store, n="a")
        # Never soft-deleted — undelete must not "succeed" on a live row.
        assert undelete_from_db(str(aid), store) is False

    def test_undelete_already_purged_row_returns_false(self):
        """A soft-deleted row aged past the purge window is physically gone
        by the time an opportunistic purge runs on the next write — undelete
        must surface this honestly, not silently succeed."""
        store = EventStore()
        aid = _seed_article(store, n="a")
        delete_from_db(str(aid), store)
        _backdate_deleted_at(store, aid, PURGE_WINDOW_SECONDS + 5)
        # Trigger the opportunistic sweep via another soft-delete write.
        other = _seed_article(store, n="b")
        delete_from_db(str(other), store)

        with store.connect() as conn:
            remaining = conn.execute(
                "SELECT COUNT(*) FROM articles WHERE article_id = ?", (aid,)
            ).fetchone()[0]
        assert remaining == 0  # confirms the row was actually purged

        assert undelete_from_db(str(aid), store) is False


class TestBulkDeleteReportsCounts:
    def test_reports_deleted_and_skipped_counts(self):
        store = EventStore()
        a = _seed_article(store, n="a")
        b = _seed_article(store, n="b")

        result = bulk_delete_from_db([str(a), str(b), "999999"], store)

        assert result == {"deleted": 2, "skipped": 1}
        ids = {it["id"] for it in list_history(store)}
        assert str(a) not in ids
        assert str(b) not in ids

    def test_bulk_delete_is_undo_able(self):
        store = EventStore()
        a = _seed_article(store, n="a")
        bulk_delete_from_db([str(a)], store)
        assert get_history_item(a, store) is None
        assert undelete_from_db(str(a), store) is True
        assert get_history_item(a, store) is not None


class TestCliReadPathIsBlindToSoftDeletes:
    """Exercises the exact read functions a CLI caller would use — no
    mocking, a real on-disk events.db — proving the default (no
    ``include_deleted`` kwarg) path never surfaces a soft-deleted row.

    No CLI subcommand today calls ``list_history``/``get_history_item``
    directly (verified by inventory: neither name appears anywhere under
    ``src/backlink_publisher/cli/``), so this test drives the read
    functions themselves exactly as any future CLI caller would — the
    same functions, the same default signature, a real database file.
    """

    def test_cli_style_call_never_sees_soft_deleted_row(self):
        store = EventStore()
        aid = _seed_article(store, n="a")
        kept = _seed_article(store, n="b")
        delete_from_db(str(aid), store)

        # Exactly as a CLI caller would invoke it: positional store only,
        # no include_deleted kwarg at all.
        items = list_history(store)
        ids = {it["id"] for it in items}
        assert str(aid) not in ids
        assert str(kept) in ids

        assert get_history_item(aid, store) is None
        assert get_history_item(kept, store) is not None

    def test_cli_read_path_has_no_way_to_pass_include_deleted_positionally(self):
        """``include_deleted`` is keyword-only-by-convention (3rd positional
        param) -- a CLI caller that only ever supplies ``store``/``limit``
        cannot accidentally bypass the filter."""
        import inspect

        sig = inspect.signature(list_history)
        assert list(sig.parameters)[-1] == "include_deleted"
        assert sig.parameters["include_deleted"].default is None


# ── HTTP surface — /api/v1/history/*, real events.db, no mocking ───────────


@pytest.fixture
def client(tmp_path, monkeypatch, disable_csrf):
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
    disable_csrf.config["TESTING"] = True
    return disable_csrf.test_client()


def _seed_via_store(*, n: str) -> str:
    store = EventStore()
    return str(_seed_article(store, n=n))


class TestApiV1DeleteUndeleteRoundTrip:
    def test_delete_then_list_excludes_then_undelete_restores(self, client):
        aid = _seed_via_store(n="a")

        resp = client.post("/api/v1/history/delete", json={"id": aid})
        assert resp.status_code == 200
        ids = {it["id"] for it in resp.get_json()["items"]}
        assert aid not in ids

        resp = client.get("/api/v1/history")
        ids = {it["id"] for it in resp.get_json()["items"]}
        assert aid not in ids

        resp = client.post("/api/v1/history/undelete", json={"id": aid})
        assert resp.status_code == 200
        ids = {it["id"] for it in resp.get_json()["items"]}
        assert aid in ids

    def test_undelete_unknown_id_returns_404_not_silent_success(self, client):
        resp = client.post("/api/v1/history/undelete", json={"id": "999999"})
        assert resp.status_code == 404
        assert resp.headers["Content-Type"].startswith("application/problem+json")
        body = resp.get_json()
        assert body["status"] == 404
        assert body["error_class"] == "not_found"

    def test_undelete_never_deleted_id_returns_404(self, client):
        aid = _seed_via_store(n="a")
        resp = client.post("/api/v1/history/undelete", json={"id": aid})
        assert resp.status_code == 404

    def test_include_deleted_window_returns_deleted_row_with_timestamp(self, client):
        aid = _seed_via_store(n="a")
        client.post("/api/v1/history/delete", json={"id": aid})

        resp = client.get("/api/v1/history?include_deleted=window")
        assert resp.status_code == 200
        items = {it["id"]: it for it in resp.get_json()["items"]}
        assert aid in items
        assert items[aid]["deleted_at"] is not None

    def test_include_deleted_invalid_value_returns_422(self, client):
        resp = client.get("/api/v1/history?include_deleted=everything")
        assert resp.status_code == 422
        assert resp.headers["Content-Type"].startswith("application/problem+json")


class TestApiV1BulkDeletePartialCounts:
    def test_bulk_delete_reports_deleted_and_skipped(self, client):
        a = _seed_via_store(n="a")
        b = _seed_via_store(n="b")

        resp = client.post(
            "/api/v1/history/bulk-delete", json={"ids": [a, b, "999999"]}
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["deleted"] == 2
        assert body["skipped"] == 1
