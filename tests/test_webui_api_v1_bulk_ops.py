"""Contract tests for the U3 batch-ops parity endpoints (Plan 2026-07-02-001 U3).

Hermetic: module-level ``_api`` facade instances are patched, mirroring
test_webui_api_v1_drafts.py's convention, so we exercise the HTTP binding +
error mapping without touching drafts_store/history_store/APScheduler.

Named ``test_webui_*`` so the route-coverage meta-test sees the literal
``client.post("/api/v1/...")`` calls.
"""

from __future__ import annotations

__tier__ = "integration"

import webui_app.api.v1.drafts as drafts_mod
import webui_app.api.v1.history as history_mod

PROBLEM_CT = "application/problem+json"


def _patch_history(monkeypatch, **methods):
    for name, fn in methods.items():
        monkeypatch.setattr(history_mod._api, name, fn)


def _patch_drafts(monkeypatch, **methods):
    for name, fn in methods.items():
        monkeypatch.setattr(drafts_mod._api, name, fn)


# ── history/bulk-recheck ─────────────────────────────────────────────────


def test_webui_history_bulk_recheck_returns_refreshed_list(client, monkeypatch):
    _patch_history(
        monkeypatch,
        bulk_recheck=lambda ids: {"ok": True, "flash_msg": f"已核实 {len(ids)} 条：..."},
        list=lambda: [{"id": "1", "status": "published"}],
    )
    resp = client.post("/api/v1/history/bulk-recheck", json={"ids": ["1", "2"]})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["items"] == [{"id": "1", "status": "published"}]
    assert "已核实" in body["message"]


def test_webui_history_bulk_recheck_empty_ids_returns_422(client):
    resp = client.post("/api/v1/history/bulk-recheck", json={"ids": []})
    assert resp.status_code == 422
    assert resp.headers["Content-Type"].startswith(PROBLEM_CT)


def test_webui_history_bulk_recheck_missing_ids_key_returns_422(client):
    resp = client.post("/api/v1/history/bulk-recheck", json={})
    assert resp.status_code == 422


def test_webui_history_bulk_recheck_no_match_is_ok_false_but_422(client, monkeypatch):
    # bulk_recheck's own contract: no items matched -> ok:False, not a crash.
    _patch_history(
        monkeypatch,
        bulk_recheck=lambda ids: {"ok": False, "flash_msg": "未匹配到记录"},
        list=lambda: [],
    )
    resp = client.post("/api/v1/history/bulk-recheck", json={"ids": ["nope"]})
    assert resp.status_code == 422
    assert resp.headers["Content-Type"].startswith(PROBLEM_CT)


# ── drafts/bulk-publish-now ───────────────────────────────────────────────


def test_webui_drafts_bulk_publish_now_returns_refreshed_list(client, monkeypatch):
    _patch_drafts(
        monkeypatch,
        bulk_publish_now=lambda ids: {"ok": True, "flash_msg": f"正在批量发布 {len(ids)} 项，请稍候刷新页面"},
        list_all=lambda: [{"id": "1", "status": "scheduled"}],
    )
    resp = client.post("/api/v1/drafts/bulk-publish-now", json={"ids": ["1", "2"]})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["items"][0]["status"] == "scheduled"
    assert "批量发布" in body["message"]


def test_webui_drafts_bulk_publish_now_empty_ids_returns_422(client):
    resp = client.post("/api/v1/drafts/bulk-publish-now", json={"ids": []})
    assert resp.status_code == 422
    assert resp.headers["Content-Type"].startswith(PROBLEM_CT)


def test_webui_drafts_bulk_publish_now_scheduler_failure_returns_502(client, monkeypatch):
    _patch_drafts(
        monkeypatch,
        bulk_publish_now=lambda ids: {
            "ok": False,
            "error_code": "BULK_SCHEDULER_FAILURE",
            "flash_msg": "批量发布失败：调度器注册异常，已回滚所有变更 (RuntimeError)",
        },
    )
    resp = client.post("/api/v1/drafts/bulk-publish-now", json={"ids": ["1"]})
    assert resp.status_code == 502
    assert resp.headers["Content-Type"].startswith(PROBLEM_CT)
    assert resp.get_json()["error_class"] == "bulk_scheduler_failure"


def test_webui_drafts_bulk_publish_now_double_submit_returns_409(client, monkeypatch):
    """A second concurrent call while one is mid-flight must not double-schedule
    the batch -- it gets 409, not queued (single-flight, mirrors
    routes/keep_alive.py's start_recheck() guard)."""
    entered = []

    def _slow_bulk_publish(ids):
        entered.append(ids)
        # Simulate a second request arriving while this one still holds the lock.
        second = client.post("/api/v1/drafts/bulk-publish-now", json={"ids": ["other"]})
        assert second.status_code == 409
        assert second.headers["Content-Type"].startswith(PROBLEM_CT)
        assert second.get_json()["error_class"] == "already_running"
        return {"ok": True, "flash_msg": "正在批量发布 1 项，请稍候刷新页面"}

    _patch_drafts(monkeypatch, bulk_publish_now=_slow_bulk_publish, list_all=lambda: [])
    resp = client.post("/api/v1/drafts/bulk-publish-now", json={"ids": ["1"]})
    assert resp.status_code == 200
    assert entered == [["1"]]


# ── drafts/bulk-cancel ────────────────────────────────────────────────────


def test_webui_drafts_bulk_cancel_returns_refreshed_list(client, monkeypatch):
    _patch_drafts(
        monkeypatch,
        bulk_cancel=lambda ids: {"ok": True, "flash_msg": f"已取消 {len(ids)} 项排程"},
        list_all=lambda: [{"id": "1", "status": "pending"}],
    )
    resp = client.post("/api/v1/drafts/bulk-cancel", json={"ids": ["1"]})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["items"][0]["status"] == "pending"
    assert "取消" in body["message"]


def test_webui_drafts_bulk_cancel_empty_ids_returns_422(client):
    resp = client.post("/api/v1/drafts/bulk-cancel", json={"ids": []})
    assert resp.status_code == 422
    assert resp.headers["Content-Type"].startswith(PROBLEM_CT)


def test_webui_drafts_bulk_cancel_failure_returns_502(client, monkeypatch):
    _patch_drafts(
        monkeypatch,
        bulk_cancel=lambda ids: {
            "ok": False,
            "error_code": "BULK_CANCEL_FAILURE",
            "flash_msg": "批量取消失敗：後台任務同步異常，已中止操作 (RuntimeError)",
        },
    )
    resp = client.post("/api/v1/drafts/bulk-cancel", json={"ids": ["1"]})
    assert resp.status_code == 502
    assert resp.headers["Content-Type"].startswith(PROBLEM_CT)
    assert resp.get_json()["error_class"] == "bulk_cancel_failure"
