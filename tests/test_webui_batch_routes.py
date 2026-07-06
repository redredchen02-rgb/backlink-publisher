"""Tests for batch site operations routes + store (Plan 2026-06-09-001 U6)."""

from __future__ import annotations

__tier__ = "integration"

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ── file-local autouse fixtures ───────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _no_real_subprocess():
    import subprocess as sp_mod
    from unittest.mock import patch

    def _fake_run(cmd, *_args, **_kwargs):
        result = sp_mod.CompletedProcess(args=cmd, returncode=0)
        result.stdout = ""
        result.stderr = ""
        return result

    with patch("subprocess.run", side_effect=_fake_run):
        yield


@pytest.fixture(autouse=True)
def _no_run_pipe():
    from unittest.mock import patch

    def _fake(_cmd, _stdin):
        return {"stdout": "", "stderr": ""}

    def _fake_capture(_cmd, _stdin):
        return {"stdout": "", "stderr": "", "returncode": 0}

    targets = [
        ("backlink_publisher.sdk._cli_runner.run_pipe", _fake),
        ("backlink_publisher.sdk.api.run_pipe", _fake),
        ("backlink_publisher.sdk.api.run_pipe_capture", _fake_capture),
    ]
    patches = [patch(t, side_effect=f) for t, f in targets]
    for p in patches:
        p.start()
    try:
        yield
    finally:
        for p in patches:
            p.stop()


@pytest.fixture(autouse=True)
def _isolated_webui_state(tmp_path, monkeypatch):
    import webui_store as _ws
    state_dir = tmp_path / "webui_state"
    state_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(_ws.history_store, "path", state_dir / "publish-history.json")
    monkeypatch.setattr(_ws.profiles_store, "path", state_dir / "webui.db")
    monkeypatch.setattr(_ws.drafts_store, "path", state_dir / "webui.db")
    monkeypatch.setattr(_ws.schedule_store, "path", state_dir / "webui.db")
    monkeypatch.setattr(_ws.batch_ops_store, "path", state_dir / "webui.db")


# ── BatchOpsSqliteStore unit tests ────────────────────────────────────────────

class TestBatchOpsSqliteStore:
    def test_enqueue_many_writes_rows(self, tmp_path):
        from webui_store.batch_ops import BatchOpsSqliteStore
        from webui_store.sqlite_base import WebUIDatabase
        store = BatchOpsSqliteStore(WebUIDatabase(tmp_path / "test.db"))
        ids = store.enqueue_many(["https://a.com/", "https://b.com/"], "keep_alive")
        assert len(ids) == 2
        rows = store.list_status()
        assert len(rows) == 2
        assert all(r["status"] == "pending" for r in rows)
        assert all(r["operation"] == "keep_alive" for r in rows)

    def test_get_pending_one_returns_oldest(self, tmp_path):
        from webui_store.batch_ops import BatchOpsSqliteStore
        from webui_store.sqlite_base import WebUIDatabase
        store = BatchOpsSqliteStore(WebUIDatabase(tmp_path / "test.db"))
        ids = store.enqueue_many(["https://first.com/", "https://second.com/"], "recheck")
        first = store.get_pending_one()
        assert first is not None
        assert first["site_url"] == "https://first.com/"

    def test_get_pending_one_returns_none_when_empty(self, tmp_path):
        from webui_store.batch_ops import BatchOpsSqliteStore
        from webui_store.sqlite_base import WebUIDatabase
        store = BatchOpsSqliteStore(WebUIDatabase(tmp_path / "test.db"))
        assert store.get_pending_one() is None

    def test_update_row_changes_status(self, tmp_path):
        from webui_store.batch_ops import BatchOpsSqliteStore
        from webui_store.sqlite_base import WebUIDatabase
        store = BatchOpsSqliteStore(WebUIDatabase(tmp_path / "test.db"))
        ids = store.enqueue_many(["https://a.com/"], "keep_alive")
        store.update_row(ids[0], "done")
        rows = store.list_status()
        assert rows[0]["status"] == "done"
        assert rows[0]["error"] is None

    def test_update_row_stores_error(self, tmp_path):
        from webui_store.batch_ops import BatchOpsSqliteStore
        from webui_store.sqlite_base import WebUIDatabase
        store = BatchOpsSqliteStore(WebUIDatabase(tmp_path / "test.db"))
        ids = store.enqueue_many(["https://a.com/"], "recheck")
        store.update_row(ids[0], "failed", error="timeout")
        rows = store.list_status()
        assert rows[0]["status"] == "failed"
        assert rows[0]["error"] == "timeout"


# ── Route tests ───────────────────────────────────────────────────────────────

class TestPostBatchQueue:
    def test_queues_three_sites(self, client, monkeypatch):
        import webui_store as _ws
        calls = []
        monkeypatch.setattr(_ws.batch_ops_store, "enqueue_many",
                            lambda urls, op: (calls.append((urls, op)) or [str(i) for i in range(len(urls))]))
        resp = client.post(
            "/sites/batch-queue",
            json={"site_urls": ["https://a.com/", "https://b.com/", "https://c.com/"],
                  "operation": "keep_alive"},
        )
        assert resp.status_code == 202
        data = resp.get_json()
        assert data["queued"] == 3
        assert calls[0][1] == "keep_alive"

    def test_unknown_operation_returns_422(self, client):
        resp = client.post(
            "/sites/batch-queue",
            json={"site_urls": ["https://a.com/"], "operation": "publish"},
        )
        assert resp.status_code == 422

    def test_empty_site_urls_returns_400(self, client):
        resp = client.post(
            "/sites/batch-queue",
            json={"site_urls": [], "operation": "keep_alive"},
        )
        assert resp.status_code == 400

    def test_missing_site_urls_returns_400(self, client):
        resp = client.post(
            "/sites/batch-queue",
            json={"operation": "recheck"},
        )
        assert resp.status_code == 400


class TestGetBatchStatus:
    def test_returns_rows_list(self, client, monkeypatch):
        import webui_store as _ws
        rows = [{"id": "x", "site_url": "https://a.com/", "operation": "keep_alive",
                 "status": "done", "created_at": "2026-06-09T00:00:00Z",
                 "updated_at": "2026-06-09T00:01:00Z", "error": None}]
        monkeypatch.setattr(_ws.batch_ops_store, "list_status", lambda limit=200: rows)
        resp = client.get("/sites/batch-status")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "rows" in data
        assert len(data["rows"]) == 1

    def test_limit_param_accepted(self, client, monkeypatch):
        import webui_store as _ws
        received = []
        monkeypatch.setattr(_ws.batch_ops_store, "list_status",
                            lambda limit=200: (received.append(limit) or []))
        client.get("/sites/batch-status?limit=50")
        assert received[0] == 50
