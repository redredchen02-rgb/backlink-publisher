"""Tests for PublishDefaultsSqliteStore + quick-publish routes (Plan 2026-06-09-001 U5)."""

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
    monkeypatch.setattr(_ws.publish_defaults_store, "path", state_dir / "webui.db")


# ── store unit tests ──────────────────────────────────────────────────────────

class TestPublishDefaultsSqliteStore:
    def test_load_returns_empty_dict_when_no_row(self, tmp_path):
        from webui_store.publish_defaults import PublishDefaultsSqliteStore
        from webui_store.sqlite_base import WebUIDatabase
        store = PublishDefaultsSqliteStore(WebUIDatabase(tmp_path / "test.db"))
        assert store.load() == {}

    def test_save_and_load_roundtrip(self, tmp_path):
        from webui_store.publish_defaults import PublishDefaultsSqliteStore
        from webui_store.sqlite_base import WebUIDatabase
        store = PublishDefaultsSqliteStore(WebUIDatabase(tmp_path / "test.db"))
        data = {"last_platforms": ["medium", "blogger"], "last_target_ids": ["t1", "t2"]}
        store.save(data)
        loaded = store.load()
        assert loaded["last_platforms"] == ["medium", "blogger"]
        assert loaded["last_target_ids"] == ["t1", "t2"]

    def test_save_overwrites_previous(self, tmp_path):
        from webui_store.publish_defaults import PublishDefaultsSqliteStore
        from webui_store.sqlite_base import WebUIDatabase
        store = PublishDefaultsSqliteStore(WebUIDatabase(tmp_path / "test.db"))
        store.save({"last_platforms": ["medium"], "last_target_ids": []})
        store.save({"last_platforms": ["velog"], "last_target_ids": ["x"]})
        loaded = store.load()
        assert loaded["last_platforms"] == ["velog"]
        assert loaded["last_target_ids"] == ["x"]

    def test_load_returns_empty_dict_on_corrupt_json(self, tmp_path):
        from webui_store.publish_defaults import PublishDefaultsSqliteStore
        from webui_store.sqlite_base import WebUIDatabase
        store = PublishDefaultsSqliteStore(WebUIDatabase(tmp_path / "test.db"))
        # Directly insert corrupt JSON
        with store._db.connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO publish_defaults (id, data_json) VALUES (1, ?)",
                ("not-json{{{",),
            )
        assert store.load() == {}


# ── route tests ───────────────────────────────────────────────────────────────

class TestGetPublishDefaults:
    def test_returns_204_when_no_defaults(self, client):
        from unittest.mock import patch
        with patch("webui_store.publish_defaults_store.load", return_value={}):
            resp = client.get("/publish/defaults")
        assert resp.status_code == 204

    def test_returns_200_with_platforms_when_defaults_exist(self, client):
        from unittest.mock import patch
        defaults = {"last_platforms": ["medium"], "last_target_ids": ["t1"]}
        with patch("webui_store.publish_defaults_store.load", return_value=defaults):
            resp = client.get("/publish/defaults")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["platforms"] == ["medium"]
        assert data["target_ids"] == ["t1"]

    def test_returns_204_when_last_platforms_empty(self, client):
        from unittest.mock import patch
        with patch("webui_store.publish_defaults_store.load",
                   return_value={"last_platforms": [], "last_target_ids": []}):
            resp = client.get("/publish/defaults")
        assert resp.status_code == 204


class TestPostPublishQuick:
    def test_returns_400_when_no_defaults(self, client, monkeypatch):
        import webui_store as _ws
        monkeypatch.setattr(_ws.publish_defaults_store, "load", lambda: {})
        resp = client.post("/publish/quick")
        assert resp.status_code == 400
        assert resp.get_json()["error"] == "no defaults saved"

    def test_returns_202_with_task_id_when_defaults_exist(self, client, monkeypatch):
        import webui_store as _ws
        defaults = {"last_platforms": ["medium"], "last_target_ids": ["t1"]}
        monkeypatch.setattr(_ws.publish_defaults_store, "load", lambda: defaults)
        calls = []
        monkeypatch.setattr(_ws.queue_store, "update", lambda fn: calls.append(fn([])))
        resp = client.post("/publish/quick")
        assert resp.status_code == 202
        data = resp.get_json()
        assert data["status"] == "queued"
        assert "task_id" in data
        assert len(calls) == 1

    def test_queued_task_includes_platforms(self, client, monkeypatch):
        import webui_store as _ws
        defaults = {"last_platforms": ["blogger", "velog"], "last_target_ids": []}
        monkeypatch.setattr(_ws.publish_defaults_store, "load", lambda: defaults)
        captured = []
        monkeypatch.setattr(_ws.queue_store, "update", lambda fn: captured.extend(fn([])))
        client.post("/publish/quick")
        assert len(captured) == 1
        assert "blogger" in captured[0]["config"]["platform"]
        assert captured[0]["source"] == "quick_publish"


class TestPostSavePublishDefaults:
    def test_saves_platforms_and_target_ids(self, client):
        from unittest.mock import MagicMock, patch
        mock_save = MagicMock()
        with patch("webui_store.publish_defaults_store.save", mock_save):
            resp = client.post(
                "/publish/save-defaults",
                json={"platforms": ["medium"], "target_ids": ["t1", "t2"]},
            )
        assert resp.status_code == 200
        assert resp.get_json()["ok"] is True
        mock_save.assert_called_once_with(
            {"last_platforms": ["medium"], "last_target_ids": ["t1", "t2"]}
        )

    def test_returns_400_when_platforms_not_a_list(self, client):
        resp = client.post(
            "/publish/save-defaults",
            json={"platforms": "medium", "target_ids": []},
        )
        assert resp.status_code == 400

    def test_accepts_empty_platforms_list(self, client):
        from unittest.mock import MagicMock, patch
        mock_save = MagicMock()
        with patch("webui_store.publish_defaults_store.save", mock_save):
            resp = client.post(
                "/publish/save-defaults",
                json={"platforms": [], "target_ids": []},
            )
        assert resp.status_code == 200
        mock_save.assert_called_once()
