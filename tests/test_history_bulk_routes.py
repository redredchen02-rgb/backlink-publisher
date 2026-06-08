"""Plan 2026-05-19-006 Unit 4 — history bulk-delete + purge-failed routes."""
from __future__ import annotations

__tier__ = "unit"
from urllib.parse import unquote

import pytest
from werkzeug.datastructures import MultiDict

from webui_store import history_store
from backlink_publisher.events import kinds as _kinds
from backlink_publisher.events.history_query import EventStore, list_history


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(history_store, "_path", tmp_path / "history.json")
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
    import webui
    webui.app.config["TESTING"] = True
    webui.app.config["WTF_CSRF_ENABLED"] = False
    return webui.app.test_client()


@pytest.fixture
def isolated_history(tmp_path, monkeypatch):
    monkeypatch.setattr(history_store, "_path", tmp_path / "history.json")
    return history_store


@pytest.fixture
def db_store(tmp_path, monkeypatch):
    """Isolated EventStore pre-seeded into the same config dir as client."""
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
    return EventStore()


def _insert(store: EventStore, kind: str, url: str) -> int:
    """Insert one article + event, return article_id."""
    aid = store.add_article({"live_url": url})
    if kind == _kinds.PUBLISH_FAILED:
        payload: dict = {"error_class": "E", "error_message_clean": "err"}
    else:
        payload = {"live_url": url}
    store.append(kind=kind, payload=payload, article_id=aid,
                 target_url=url, host="example.com")
    return aid


class TestHistoryBulkDelete:
    def test_removes_selected(self, client, db_store):
        id_a = _insert(db_store, _kinds.PUBLISH_CONFIRMED, "https://a.example.com")
        id_b = _insert(db_store, _kinds.PUBLISH_FAILED, "https://b.example.com")
        id_c = _insert(db_store, _kinds.PUBLISH_CONFIRMED, "https://c.example.com")
        resp = client.post(
            "/ce:history/bulk-delete",
            data=MultiDict([("ids", str(id_a)), ("ids", str(id_c))]),
        )
        assert resp.status_code == 302
        assert "已删除 2 条" in unquote(resp.location)
        remaining = list_history()
        assert len(remaining) == 1
        assert remaining[0]["id"] == str(id_b)

    def test_empty_ids_returns_warning(self, client, isolated_history):
        isolated_history.save([{"id": "a"}])
        resp = client.post("/ce:history/bulk-delete", data={})
        assert resp.status_code == 302
        assert "flash_type=warning" in resp.location
        assert len(isolated_history.load()) == 1

    def test_unknown_ids_silently_ignored(self, client, isolated_history):
        isolated_history.save([{"id": "a"}])
        resp = client.post(
            "/ce:history/bulk-delete",
            data=MultiDict([("ids", "zzz")]),
        )
        assert resp.status_code == 302
        assert "已删除 0 条" in unquote(resp.location)


class TestHistoryPurgeFailed:
    def test_removes_only_failed(self, client, db_store):
        _insert(db_store, _kinds.PUBLISH_FAILED, "https://a.example.com")
        _insert(db_store, _kinds.PUBLISH_CONFIRMED, "https://b.example.com")
        _insert(db_store, _kinds.PUBLISH_FAILED, "https://c.example.com")
        _insert(db_store, _kinds.PUBLISH_UNVERIFIED, "https://d.example.com")
        resp = client.post("/ce:history/purge-failed", data={})
        assert resp.status_code == 302
        assert "已清除 2 条" in unquote(resp.location)
        remaining = list_history()
        assert len(remaining) == 2

    def test_no_failures_returns_info(self, client, isolated_history):
        isolated_history.save([{"id": "a", "status": "published"}])
        resp = client.post("/ce:history/purge-failed", data={})
        assert resp.status_code == 302
        assert "flash_type=info" in resp.location
        assert "没有失败记录可清除" in unquote(resp.location)
        assert len(isolated_history.load()) == 1

    def test_does_not_touch_unverified(self, client, db_store):
        """purge-failed must not delete KIND_UNVERIFIED records."""
        _insert(db_store, _kinds.PUBLISH_UNVERIFIED, "https://a.example.com")
        _insert(db_store, _kinds.PUBLISH_UNVERIFIED, "https://b.example.com")
        _insert(db_store, _kinds.PUBLISH_FAILED, "https://c.example.com")
        resp = client.post("/ce:history/purge-failed", data={})
        assert resp.status_code == 302
        assert "已清除 1 条" in unquote(resp.location)
        remaining = list_history()
        assert len(remaining) == 2
