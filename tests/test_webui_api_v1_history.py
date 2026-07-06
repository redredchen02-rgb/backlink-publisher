"""Contract tests for ``/api/v1/history*`` — Plan 2026-06-18-002 U7.

Hermetic: the module-level ``HistoryAPI`` instance is patched so we exercise the
HTTP binding (envelope, validation → 422, not-found → 404, the "every mutation
returns the refreshed list" contract) without touching events.db / the recheck
network path.

Named ``test_webui_*`` so the route-coverage meta-test sees the literal
``client.post("/api/v1/history/...")`` calls.
"""

from __future__ import annotations

__tier__ = "integration"

import webui_app.api.v1.history as history_mod

PROBLEM_CT = "application/problem+json"

_ROW = {"id": "7", "target_url": "https://example.com/", "status": "published"}


def _patch(monkeypatch, **methods):
    for name, fn in methods.items():
        monkeypatch.setattr(history_mod._api, name, fn)


def test_webui_history_list_returns_items_envelope(client, monkeypatch):
    _patch(monkeypatch, list=lambda: [_ROW])
    resp = client.get("/api/v1/history")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["items"] == [_ROW]  # object envelope, never a bare array


def test_webui_history_delete_returns_refreshed_list(client, monkeypatch):
    _patch(monkeypatch, delete=lambda _id: {"ok": True, "history": []})
    resp = client.post("/api/v1/history/delete", json={"id": "7"})
    assert resp.status_code == 200
    assert resp.get_json()["items"] == []


def test_webui_history_delete_missing_id_returns_422(client):
    resp = client.post("/api/v1/history/delete", json={})
    assert resp.status_code == 422
    assert resp.headers["Content-Type"].startswith(PROBLEM_CT)
    assert resp.get_json()["type"].endswith("invalid_request")


def test_webui_history_bulk_delete_returns_list_and_message(client, monkeypatch):
    _patch(
        monkeypatch,
        bulk_delete=lambda ids: {"ok": True, "flash_msg": f"已删除 {len(ids)} 条历史记录"},
        list=lambda: [_ROW],
    )
    resp = client.post("/api/v1/history/bulk-delete", json={"ids": ["7", "8"]})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["items"] == [_ROW]
    assert "2" in body["message"]


def test_webui_history_bulk_delete_empty_ids_returns_422(client):
    resp = client.post("/api/v1/history/bulk-delete", json={"ids": []})
    assert resp.status_code == 422


def test_webui_history_purge_failed_noop_is_200_not_error(client, monkeypatch):
    # purge with nothing to purge is a no-op (ok=False), but must NOT be an error.
    _patch(
        monkeypatch,
        purge_failed=lambda: {"ok": False, "flash_msg": "没有失败记录可清除"},
        list=lambda: [_ROW],
    )
    resp = client.post("/api/v1/history/purge-failed", json={})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["items"] == [_ROW]
    assert "没有失败记录" in body["message"]


def test_webui_history_recheck_returns_refreshed_list(client, monkeypatch):
    _patch(
        monkeypatch,
        recheck=lambda _id: {"ok": True, "flash_msg": "已重新核实：状态 → published"},
        list=lambda: [_ROW],
    )
    resp = client.post("/api/v1/history/recheck", json={"id": "7"})
    assert resp.status_code == 200
    assert resp.get_json()["items"] == [_ROW]


def test_webui_history_recheck_not_found_returns_404(client, monkeypatch):
    _patch(monkeypatch, recheck=lambda _id: {"ok": False, "flash_msg": "记录不存在"})
    resp = client.post("/api/v1/history/recheck", json={"id": "nope"})
    assert resp.status_code == 404
    assert resp.headers["Content-Type"].startswith(PROBLEM_CT)
    assert resp.get_json()["error_class"] == "not_found"


# ── POST /api/v1/queue/<task_id>/retry — Plan 2026-07-06-004 Unit 3 ─────────


def test_webui_queue_retry_success_returns_200_and_envelope(client, monkeypatch):
    _patch(
        monkeypatch,
        retry_task=lambda _id: {
            "ok": True,
            "flash_type": "success",
            "flash_msg": "任务已重新排入队列，等待后台处理",
            "message": "任务已重新排入队列，等待后台处理",
        },
    )
    resp = client.post("/api/v1/queue/7/retry")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert body["flash_type"] == "success"
    # Honest wording: "requeued", never "retry succeeded" / "published".
    assert "重新排入队列" in body["message"]


def test_webui_queue_retry_not_found_returns_404(client, monkeypatch):
    _patch(
        monkeypatch,
        retry_task=lambda _id: {
            "ok": False,
            "error_code": "NOT_FOUND",
            "flash_type": "warning",
            "flash_msg": "任务不存在，可能已被处理",
            "message": "任务不存在，可能已被处理",
        },
    )
    resp = client.post("/api/v1/queue/vanished/retry")
    assert resp.status_code == 404
    assert resp.headers["Content-Type"].startswith(PROBLEM_CT)
    assert resp.get_json()["error_class"] == "not_found"


def test_webui_queue_retry_processing_returns_409_and_leaves_task_alone(client, monkeypatch):
    calls: list[str] = []

    def _retry(task_id):
        calls.append(task_id)
        return {
            "ok": False,
            "error_code": "TASK_PROCESSING",
            "flash_type": "warning",
            "flash_msg": "任务正在处理中，暂不能重试",
            "message": "任务正在处理中，暂不能重试",
        }

    _patch(monkeypatch, retry_task=_retry)
    resp = client.post("/api/v1/queue/7/retry")
    assert resp.status_code == 409
    assert resp.headers["Content-Type"].startswith(PROBLEM_CT)
    assert resp.get_json()["error_class"] == "task_processing"
    # retry_task is the single source of truth for the conditional UPDATE —
    # this route must never separately touch the task's status.
    assert calls == ["7"]
