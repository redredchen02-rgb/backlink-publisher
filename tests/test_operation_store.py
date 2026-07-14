"""Unit tests for ``OperationSqliteStore`` — Plan 2026-07-09 (U1)."""

from __future__ import annotations

from pathlib import Path

from webui_store.operation_store import OperationSqliteStore
from webui_store.sqlite_base import WebUIDatabase


def _store(tmp_path: Path) -> OperationSqliteStore:
    return OperationSqliteStore(WebUIDatabase(tmp_path / "webui.db"))


def test_create_returns_op_id_and_persists(tmp_path: Path) -> None:
    store = _store(tmp_path)
    op_id = store.create(kind="publish", cfg={"platform": "blogger"})
    assert op_id
    op = store.get(op_id)
    assert op is not None
    assert op["kind"] == "publish"
    assert op["status"] == "pending"
    assert op["cfg"] == {"platform": "blogger"}
    # publish kind carries a single-stage list for the step indicator.
    assert op["stages"] == ["发布"]


def test_create_chain_carries_three_stages(tmp_path: Path) -> None:
    store = _store(tmp_path)
    op_id = store.create(kind="publish_chain", cfg={"urls": ["http://x"]})
    op = store.get(op_id)
    assert op["stages"] == ["生成", "验证", "发布"]


def test_update_merges_and_clamps_progress(tmp_path: Path) -> None:
    store = _store(tmp_path)
    op_id = store.create(kind="publish", cfg={})
    assert store.update_fields(op_id, status="running", stage="发布", progress_pct=250.0)
    op = store.get(op_id)
    assert op["status"] == "running"
    assert op["stage"] == "发布"
    # progress is clamped to 0-100.
    assert op["progress_pct"] == 100.0


def test_update_rejects_bad_status(tmp_path: Path) -> None:
    store = _store(tmp_path)
    op_id = store.create(kind="publish", cfg={})
    try:
        store.update_fields(op_id, status="bogus")
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for invalid status")
    assert store.get(op_id)["status"] == "pending"


def test_canceled_is_terminal_late_worker_write_cannot_resurrect(tmp_path: Path) -> None:
    # finding [37]: cancel() sets status="canceled", but the still-running worker
    # thread later writes status="success"/"failed", clobbering the terminal
    # cancel. 'canceled' must be a terminal sink: subsequent writes are no-ops.
    store = _store(tmp_path)
    op_id = store.create(kind="publish", cfg={})
    store.update_fields(op_id, status="running", progress_pct=50)
    assert store.update_fields(op_id, status="canceled")

    # The abandoned worker completes and tries to record a terminal success.
    store.update_fields(
        op_id, status="success", progress_pct=100, result={"n_ok": 1}
    )

    op = store.get(op_id)
    assert op["status"] == "canceled"
    assert op.get("result") in (None, {})  # the success payload never landed


def test_canceled_op_ignores_progress_and_stage_writes(tmp_path: Path) -> None:
    # Once canceled, even non-status stage/progress bumps from the worker are frozen.
    store = _store(tmp_path)
    op_id = store.create(kind="publish", cfg={})
    store.update_fields(op_id, status="canceled", stage="", progress_pct=30)
    store.update_fields(op_id, stage="发布", progress_pct=75, detail="正在发布…")
    op = store.get(op_id)
    assert op["status"] == "canceled"
    assert op["progress_pct"] == 30


def test_list_and_active(tmp_path: Path) -> None:
    store = _store(tmp_path)
    a = store.create(kind="publish", cfg={"n": 1})
    b = store.create(kind="publish", cfg={"n": 2})
    store.update_fields(a, status="running")
    # b stays pending (also "active"); move it to a terminal state so only a is active.
    store.update_fields(b, status="success")
    active = store.list_active()
    assert {op["op_id"] for op in active} == {a}
    listed = store.list(limit=10)
    assert len(listed) == 2
    # newest first.
    assert listed[0]["op_id"] == b


def test_get_missing_returns_none(tmp_path: Path) -> None:
    store = _store(tmp_path)
    assert store.get("does-not-exist") is None
