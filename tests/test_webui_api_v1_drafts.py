"""Contract tests for ``/api/v1/drafts*`` — Plan 2026-06-18-002 U7 (drafts page).

Hermetic: the module-level ``DraftAPI`` instance is patched so we exercise the
HTTP binding + the nuanced error mapping (SCHEDULER_SYNC_FAILED → 200-with-warning
because the store DID mutate; PERSISTENCE_FAILURE → 502; missing params → 422)
without touching drafts_store / APScheduler.

Named ``test_webui_*`` so the route-coverage meta-test sees the literal
``client.post("/api/v1/drafts/...")`` calls.
"""

from __future__ import annotations

__tier__ = "integration"

import webui_app.api.v1.drafts as drafts_mod

PROBLEM_CT = "application/problem+json"

_DRAFT = {"id": "ab12cd34", "target_url": "https://a.com/", "status": "pending", "platform": "velog"}


def _patch(monkeypatch, **methods):
    for name, fn in methods.items():
        monkeypatch.setattr(drafts_mod._api, name, fn)


def test_webui_drafts_list_returns_items_envelope(client, monkeypatch):
    _patch(monkeypatch, list_all=lambda: [_DRAFT])
    resp = client.get("/api/v1/drafts")
    assert resp.status_code == 200
    assert resp.get_json()["items"] == [_DRAFT]


def test_webui_drafts_schedule_returns_refreshed_list(client, monkeypatch):
    _patch(
        monkeypatch,
        schedule=lambda _id, _at: {"ok": True, "flash_msg": "已排程：2026-06-20 09:00"},
        list_all=lambda: [{**_DRAFT, "status": "scheduled"}],
    )
    resp = client.post(
        "/api/v1/drafts/schedule", json={"id": "ab12cd34", "scheduled_at": "2026-06-20T09:00"}
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["items"][0]["status"] == "scheduled"
    assert "已排程" in body["message"]


def test_webui_drafts_schedule_missing_id_returns_422(client):
    resp = client.post("/api/v1/drafts/schedule", json={"scheduled_at": "2026-06-20T09:00"})
    assert resp.status_code == 422
    assert resp.headers["Content-Type"].startswith(PROBLEM_CT)


def test_webui_drafts_publish_now_returns_refreshed_list(client, monkeypatch):
    _patch(
        monkeypatch,
        publish_now=lambda _id: {"ok": True, "flash_msg": "正在发布，请稍候刷新页面"},
        list_all=lambda: [{**_DRAFT, "status": "scheduled"}],
    )
    resp = client.post("/api/v1/drafts/publish-now", json={"id": "ab12cd34"})
    assert resp.status_code == 200
    assert resp.get_json()["items"][0]["status"] == "scheduled"


def test_webui_drafts_delete_scheduler_sync_failed_is_200_warning(client, monkeypatch):
    # Store mutation succeeded; only the background job lingered → soft success.
    _patch(
        monkeypatch,
        delete=lambda _id: {
            "ok": False,
            "error_code": "SCHEDULER_SYNC_FAILED",
            "flash_msg": "刪除失敗：無法同步刪除後台調度任務，該任務可能仍在運行！",
        },
        list_all=lambda: [],
    )
    resp = client.post("/api/v1/drafts/delete", json={"id": "ab12cd34"})
    assert resp.status_code == 200  # the draft IS gone from the store; warn, don't error
    body = resp.get_json()
    assert body["items"] == []
    assert "後台調度任務" in body["message"]


def test_webui_drafts_delete_persistence_failure_returns_502(client, monkeypatch):
    _patch(
        monkeypatch,
        delete=lambda _id: {
            "ok": False,
            "error_code": "PERSISTENCE_FAILURE",
            "flash_msg": "刪除失敗：本地儲存刪除失敗 (OSError)",
        },
    )
    resp = client.post("/api/v1/drafts/delete", json={"id": "ab12cd34"})
    assert resp.status_code == 502
    assert resp.headers["Content-Type"].startswith(PROBLEM_CT)
    assert resp.get_json()["error_class"] == "persistence_failure"


def test_webui_drafts_cancel_returns_refreshed_list(client, monkeypatch):
    _patch(
        monkeypatch,
        cancel=lambda _id: {"ok": True, "flash_msg": "已取消排程"},
        list_all=lambda: [_DRAFT],
    )
    resp = client.post("/api/v1/drafts/cancel", json={"id": "ab12cd34"})
    assert resp.status_code == 200
    assert resp.get_json()["items"] == [_DRAFT]


def test_webui_drafts_bulk_delete_empty_ids_returns_422(client):
    resp = client.post("/api/v1/drafts/bulk-delete", json={"ids": []})
    assert resp.status_code == 422


def test_webui_drafts_bulk_delete_returns_list_and_message(client, monkeypatch):
    _patch(
        monkeypatch,
        bulk_delete=lambda ids: {"ok": True, "flash_msg": f"已删除 {len(ids)} 项"},
        list_all=lambda: [],
    )
    resp = client.post("/api/v1/drafts/bulk-delete", json={"ids": ["ab12cd34", "ef56"]})
    assert resp.status_code == 200
    assert "2" in resp.get_json()["message"]
