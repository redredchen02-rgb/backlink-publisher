"""Contract tests for the /api/v1/operations endpoints — Plan 2026-07-09 (U1).

CSRF is disabled by the ``client`` fixture; the worker's ``start`` is patched
to run synchronously so each POST returns after the op completes, making the
poll endpoint deterministic.
"""

from __future__ import annotations

import time

import pytest

import backlink_publisher.sdk.api as sdk_api
import webui
import webui_app.services.operation_worker as ow


class _FakeResult:
    def __init__(
        self, *, success: bool = True, rows: list | None = None, stdout: str = "{}",
        error: str | None = None, error_class: str | None = "unrecognized",
    ) -> None:
        self.success = success
        self.rows = rows if rows is not None else []
        self.stdout = stdout
        self.stderr = ""
        self.error = error
        self.error_class = error_class


class _FakeAPI:
    def plan(self, *args: object, **kwargs: object) -> _FakeResult:
        return _FakeResult(success=True, stdout="{}")

    def validate(self, *args: object, **kwargs: object) -> _FakeResult:
        return _FakeResult(success=True, stdout="{}")

    def publish(self, *args: object, **kwargs: object) -> _FakeResult:
        return _FakeResult(
            success=True,
            rows=[
                {
                    "status": "published",
                    "published_url": "http://x.example/a",
                    "target_url": "http://main",
                    "platform": "blogger",
                    "language": "zh-CN",
                }
            ],
        )


@pytest.fixture
def op_client(client, monkeypatch: pytest.MonkeyPatch):
    api = _FakeAPI()
    monkeypatch.setattr(sdk_api, "PipelineAPI", lambda: api)
    monkeypatch.setattr(
        "webui_app.helpers.history._push_history_per_row", lambda *a, **k: []
    )
    monkeypatch.setattr(
        "webui_app.helpers.history._push_history_single_failure", lambda *a, **k: []
    )

    def _sync_start(self, op_id, kind, cfg):
        ow._execute_operation(op_id, kind, cfg)

    monkeypatch.setattr(ow.OperationWorker, "start", _sync_start)
    webui.app.config["OPERATION_WORKER"] = ow.OperationWorker()
    yield client


def test_create_publish_returns_202_and_polls_to_success(op_client) -> None:
    resp = op_client.post(
        "/api/v1/operations",
        json={"kind": "publish", "plans": [{"a": 1}], "platform": "blogger"},
    )
    assert resp.status_code == 202
    body = resp.get_json()
    assert body["kind"] == "publish"
    op_id = body["op_id"]

    status = op_client.get(f"/api/v1/operations/{op_id}").get_json()
    assert status["status"] == "success"
    assert status["progress_pct"] == 100.0
    assert status["done"] is True
    assert status["result"]["n_ok"] == 1


def test_create_chain_runs_three_stages(op_client) -> None:
    resp = op_client.post(
        "/api/v1/operations",
        json={"kind": "publish_chain", "urls": ["http://x.example"], "platform": "blogger"},
    )
    assert resp.status_code == 202
    op_id = resp.get_json()["op_id"]
    status = op_client.get(f"/api/v1/operations/{op_id}").get_json()
    assert status["status"] == "success"
    assert status["stages"] == ["生成", "验证", "发布"]


def test_create_rejects_invalid_kind(op_client) -> None:
    resp = op_client.post("/api/v1/operations", json={"kind": "frobnicate"})
    assert resp.status_code == 422
    assert resp.get_json()["error_class"] == "invalid_request"


def test_create_publish_requires_plans(op_client) -> None:
    resp = op_client.post("/api/v1/operations", json={"kind": "publish", "platform": "blogger"})
    assert resp.status_code == 422


def test_get_missing_returns_404(op_client) -> None:
    resp = op_client.get("/api/v1/operations/nope")
    assert resp.status_code == 404


def test_list_operations_returns_recent(op_client) -> None:
    op_client.post(
        "/api/v1/operations",
        json={"kind": "publish", "plans": [{"a": 1}], "platform": "blogger"},
    )
    resp = op_client.get("/api/v1/operations")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["count"] >= 1
    assert body["operations"][0]["kind"] == "publish"


def test_cancel_finished_op_is_noop(op_client) -> None:
    op_id = op_client.post(
        "/api/v1/operations",
        json={"kind": "publish", "plans": [{"a": 1}], "platform": "blogger"},
    ).get_json()["op_id"]
    resp = op_client.post(f"/api/v1/operations/{op_id}/cancel")
    assert resp.status_code == 200
    assert resp.get_json()["canceled"] is False
    assert resp.get_json()["status"] == "success"
