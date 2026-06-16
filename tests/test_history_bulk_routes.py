"""Plan 2026-05-19-006 Unit 4 — history bulk-delete + purge-failed routes.

Updated for the plan-007-u7 migration (commit 026e741): the bulk-delete /
purge-failed routes now operate on events.db via ``bulk_delete_from_db`` /
``purge_failed_from_db``, NOT the legacy ``history_store`` JSON. The fixtures
seed events.db (article + status event) and assert against ``list_history``,
matching what the migrated routes actually read and delete. The UI id of a
history item is ``str(article_id)`` (see history_query._build_history_item).
"""
from __future__ import annotations

__tier__ = "unit"
import json
from urllib.parse import unquote

import pytest
from werkzeug.datastructures import MultiDict

from backlink_publisher.events import EventStore, kinds
from backlink_publisher.events.history_query import list_history

_STATUS_KIND = {
    "published": kinds.PUBLISH_CONFIRMED,
    "published_unverified": kinds.PUBLISH_UNVERIFIED,
    "drafted_unverified": kinds.PUBLISH_UNVERIFIED,
    "failed": kinds.PUBLISH_FAILED,
}


@pytest.fixture
def client(tmp_path, monkeypatch):
    # Isolate events.db under the per-test config dir so the migrated routes and
    # the seeding helper share one empty store.
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
    import webui
    webui.app.config["TESTING"] = True
    webui.app.config["WTF_CSRF_ENABLED"] = False
    return webui.app.test_client()


def _seed(status: str, *, n: str) -> str:
    """Create one article + its status event in events.db; return its UI id."""
    store = EventStore()
    live_url = f"https://example.com/{n}"
    aid = store.add_article(
        {"target_urls_json": json.dumps([f"https://t.example/{n}"]), "live_url": live_url}
    )
    kind = _STATUS_KIND[status]
    if kind is kinds.PUBLISH_FAILED:
        payload = {"platform": "medium", "error_class": "ExternalServiceError",
                   "error_message_clean": "boom"}
    else:
        payload = {"platform": "medium", "live_url": live_url}
    store.append(kind, payload, article_id=aid, target_url=f"https://t.example/{n}")
    return str(aid)


def _remaining_ids() -> set[str]:
    return {str(it["id"]) for it in list_history()}


class TestHistoryBulkDelete:
    def test_removes_selected(self, client):
        a = _seed("published", n="a")
        b = _seed("failed", n="b")
        c = _seed("published", n="c")
        resp = client.post(
            "/ce:history/bulk-delete",
            data=MultiDict([("ids", a), ("ids", c)]),
        )
        assert resp.status_code == 302
        assert "已删除 2 条" in unquote(resp.location)
        assert _remaining_ids() == {b}

    def test_empty_ids_returns_warning(self, client):
        _seed("published", n="a")
        resp = client.post("/ce:history/bulk-delete", data={})
        assert resp.status_code == 302
        assert "flash_type=warning" in resp.location
        assert len(_remaining_ids()) == 1

    def test_unknown_ids_silently_ignored(self, client):
        _seed("published", n="a")
        resp = client.post(
            "/ce:history/bulk-delete",
            data=MultiDict([("ids", "999999")]),  # valid-shaped but absent id
        )
        assert resp.status_code == 302
        assert "已删除 0 条" in unquote(resp.location)


class TestHistoryPurgeFailed:
    def test_removes_only_failed(self, client):
        _seed("failed", n="a")
        b = _seed("published", n="b")
        _seed("failed", n="c")
        d = _seed("published_unverified", n="d")
        resp = client.post("/ce:history/purge-failed", data={})
        assert resp.status_code == 302
        assert "已清除 2 条" in unquote(resp.location)
        assert _remaining_ids() == {b, d}

    def test_no_failures_returns_info(self, client):
        _seed("published", n="a")
        resp = client.post("/ce:history/purge-failed", data={})
        assert resp.status_code == 302
        assert "flash_type=info" in resp.location
        assert "没有失败记录可清除" in unquote(resp.location)
        assert len(_remaining_ids()) == 1

    def test_does_not_touch_unverified(self, client):
        """purge-failed must not delete `*_unverified` — those need the user's
        recheck, not a silent drop."""
        a = _seed("published_unverified", n="a")
        b = _seed("drafted_unverified", n="b")
        _seed("failed", n="c")
        resp = client.post("/ce:history/purge-failed", data={})
        assert resp.status_code == 302
        assert "已清除 1 条" in unquote(resp.location)
        assert _remaining_ids() == {a, b}
