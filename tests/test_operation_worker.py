"""Unit tests for ``OperationWorker`` — Plan 2026-07-09 (U1).

Uses a fake ``PipelineAPI`` + no-op history helpers so the worker can be
exercised deterministically without real pipeline work or network.
"""

from __future__ import annotations

import time

import pytest

import backlink_publisher.sdk.api as sdk_api
import webui_app.services.operation_worker as ow
from webui_store import operation_store


class _FakeResult:
    def __init__(
        self,
        *,
        success: bool = True,
        rows: list | None = None,
        stdout: str = "{}",
        error: str | None = None,
        error_class: str | None = "unrecognized",
    ) -> None:
        self.success = success
        self.rows = rows if rows is not None else []
        self.stdout = stdout
        self.stderr = ""
        self.error = error
        self.error_class = error_class


class _FakeAPI:
    def __init__(self, publish_sleep: float = 0.0) -> None:
        self.publish_sleep = publish_sleep

    def plan(self, *args: object, **kwargs: object) -> _FakeResult:
        return _FakeResult(success=True, stdout="{}")

    def validate(self, *args: object, **kwargs: object) -> _FakeResult:
        return _FakeResult(success=True, stdout="{}")

    def publish(self, *args: object, **kwargs: object) -> _FakeResult:
        if self.publish_sleep:
            time.sleep(self.publish_sleep)
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
def fake_pipeline(monkeypatch: pytest.MonkeyPatch) -> None:
    api = _FakeAPI()
    monkeypatch.setattr(sdk_api, "PipelineAPI", lambda: api)
    monkeypatch.setattr(
        "webui_app.helpers.history._push_history_per_row", lambda *a, **k: []
    )
    monkeypatch.setattr(
        "webui_app.helpers.history._push_history_single_failure", lambda *a, **k: []
    )


def test_publish_op_succeeds(fake_pipeline: None) -> None:
    op_id = operation_store.create(
        kind="publish", cfg={"plans": [{"a": 1}], "platform": "blogger"}
    )
    worker = ow.OperationWorker()
    try:
        worker.start(op_id, "publish", operation_store.get(op_id)["cfg"])
        worker._running[op_id].result(timeout=5)
    finally:
        worker.shutdown()
    op = operation_store.get(op_id)
    assert op["status"] == "success"
    assert op["progress_pct"] == 100.0
    assert op["result"]["n_ok"] == 1


def test_publish_op_failure_records_error(
    fake_pipeline: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    api = _FakeAPI()

    def _fail_publish(*a: object, **k: object) -> _FakeResult:
        return _FakeResult(success=False, error="boom", error_class="content_gate_drop")

    monkeypatch.setattr(api, "publish", _fail_publish)
    monkeypatch.setattr(sdk_api, "PipelineAPI", lambda: api)

    op_id = operation_store.create(kind="publish", cfg={"plans": [], "platform": "blogger"})
    worker = ow.OperationWorker()
    try:
        worker.start(op_id, "publish", operation_store.get(op_id)["cfg"])
        worker._running[op_id].result(timeout=5)
    finally:
        worker.shutdown()
    op = operation_store.get(op_id)
    assert op["status"] == "failed"
    assert "content_gate_drop" in (op["error"] or "")


def test_single_flight_rejects_concurrent_publish(fake_pipeline: None) -> None:
    slow = _FakeAPI(publish_sleep=0.4)
    original = sdk_api.PipelineAPI
    sdk_api.PipelineAPI = lambda: slow
    try:
        worker = ow.OperationWorker()
        op1 = operation_store.create(kind="publish", cfg={"plans": [], "platform": "blogger"})
        op2 = operation_store.create(kind="publish", cfg={"plans": [], "platform": "blogger"})
        worker.start(op1, "publish", operation_store.get(op1)["cfg"])
        with pytest.raises(ow.AlreadyRunningError):
            worker.start(op2, "publish", operation_store.get(op2)["cfg"])
        worker._running[op1].result(timeout=5)
        worker.shutdown()
        assert operation_store.get(op1)["status"] == "success"
        # op2 was rejected before submission, so it never ran.
        assert operation_store.get(op2)["status"] == "pending"
    finally:
        sdk_api.PipelineAPI = original


def test_single_flight_atomic_under_concurrent_start(fake_pipeline: None) -> None:
    """Concurrent start() of single-flight ops must admit EXACTLY ONE.

    The check (_any_single_flight_running) and the reserve (self._running[id]=fut)
    must be atomic; otherwise two near-simultaneous submissions both pass the
    check before either inserts and two publishes run at once, racing dedup.db
    and spawning two Chrome subprocesses (audit [12] TOCTOU).
    """
    import threading

    slow = _FakeAPI(publish_sleep=0.5)
    original = sdk_api.PipelineAPI
    sdk_api.PipelineAPI = lambda: slow
    try:
        worker = ow.OperationWorker(max_workers=16)
        n = 16
        op_ids = [
            operation_store.create(kind="publish", cfg={"plans": [], "platform": "blogger"})
            for _ in range(n)
        ]
        barrier = threading.Barrier(n)
        admitted: list[str] = []
        rejected = {"n": 0}
        guard = threading.Lock()

        def _submit(oid: str) -> None:
            barrier.wait()  # release all threads into start() simultaneously
            try:
                worker.start(oid, "publish", operation_store.get(oid)["cfg"])
                with guard:
                    admitted.append(oid)
            except ow.AlreadyRunningError:
                with guard:
                    rejected["n"] += 1

        threads = [threading.Thread(target=_submit, args=(oid,)) for oid in op_ids]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)

        assert len(admitted) == 1, (
            f"admitted {len(admitted)} concurrent single-flight ops (expected 1) — "
            f"check-then-insert is not atomic"
        )
        assert rejected["n"] == n - 1
        worker._running[admitted[0]].result(timeout=5)
        worker.shutdown()
    finally:
        sdk_api.PipelineAPI = original


def test_cancel_pending_op(fake_pipeline: None) -> None:
    op_id = operation_store.create(kind="publish", cfg={"plans": [], "platform": "blogger"})
    worker = ow.OperationWorker()
    try:
        # Mark running, then cancel (no future registered → orphan recovery).
        operation_store.update_fields(op_id, status="running")
        assert worker.cancel(op_id) is True
        assert operation_store.get(op_id)["status"] == "canceled"
    finally:
        worker.shutdown()
