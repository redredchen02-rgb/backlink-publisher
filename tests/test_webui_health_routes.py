"""Tests for GET /health JSON endpoint (Plan 2026-06-09-001 U3 / R15–R17)."""

from __future__ import annotations

__tier__ = "integration"

import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture(autouse=True)
def _no_real_subprocess():
    import subprocess as sp_mod

    def _fake_run(cmd, *_args, **_kwargs):
        result = sp_mod.CompletedProcess(args=cmd, returncode=0)
        result.stdout = ""
        result.stderr = ""
        return result

    with patch("subprocess.run", side_effect=_fake_run):
        yield


@pytest.fixture(autouse=True)
def _no_run_pipe():
    def _fake(_cmd, _stdin):
        return {"stdout": "", "stderr": ""}

    def _fake_capture(_cmd, _stdin):
        return {"stdout": "", "stderr": "", "returncode": 0}

    targets = [
        ("webui_app.helpers.cli_runner.run_pipe", _fake),
        ("webui_app.api.pipeline_api.run_pipe", _fake),
        ("webui_app.api.pipeline_api.run_pipe_capture", _fake_capture),
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


@pytest.fixture()
def _mock_health(monkeypatch):
    """Patch compute_health_json so tests control payload without real deps."""

    def _set(payload):
        monkeypatch.setattr(
            "webui_app.services.health_projection.compute_health_json",
            lambda: payload,
        )

    return _set


class TestHealthJsonEndpoint:
    def test_get_health_returns_200_when_healthy(self, client, _mock_health):
        """GET /health returns 200 with all expected JSON keys (R15)."""
        _mock_health(
            {
                "healthy": True,
                "webui": "ok",
                "last_pipeline_run": "2026-06-09T12:00:00Z",
                "scheduler_running": True,
                "scheduler_job_count": 3,
                "channels": {"medium": "bound"},
                "degraded_reasons": [],
            }
        )
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.is_json
        data = resp.get_json()
        for key in ("healthy", "webui", "last_pipeline_run", "scheduler_running",
                    "scheduler_job_count", "channels", "degraded_reasons"):
            assert key in data, f"missing key: {key}"
        assert data["healthy"] is True

    def test_get_health_returns_503_when_channel_expired(self, client, _mock_health):
        """GET /health returns 503 when a channel is expired (R15)."""
        _mock_health(
            {
                "healthy": False,
                "webui": "ok",
                "last_pipeline_run": "2026-06-09T12:00:00Z",
                "scheduler_running": True,
                "scheduler_job_count": 2,
                "channels": {"medium": "bound", "blogger": "expired"},
                "degraded_reasons": ["channel:blogger:expired"],
            }
        )
        resp = client.get("/health")
        assert resp.status_code == 503
        data = resp.get_json()
        assert data["healthy"] is False
        assert "channel:blogger:expired" in data["degraded_reasons"]

    def test_get_health_returns_503_when_scheduler_not_running(self, client, _mock_health):
        """GET /health returns 503 when scheduler is not running (R15)."""
        _mock_health(
            {
                "healthy": False,
                "webui": "ok",
                "last_pipeline_run": "2026-06-09T12:00:00Z",
                "scheduler_running": False,
                "scheduler_job_count": 0,
                "channels": {},
                "degraded_reasons": ["scheduler:not_running"],
            }
        )
        resp = client.get("/health")
        assert resp.status_code == 503
        assert resp.get_json()["scheduler_running"] is False

    def test_get_health_returns_503_when_never_run(self, client, _mock_health):
        """GET /health returns 503 when last_pipeline_run is None (R15)."""
        _mock_health(
            {
                "healthy": False,
                "webui": "ok",
                "last_pipeline_run": None,
                "scheduler_running": True,
                "scheduler_job_count": 1,
                "channels": {},
                "degraded_reasons": ["pipeline:never_run"],
            }
        )
        resp = client.get("/health")
        assert resp.status_code == 503
        assert resp.get_json()["last_pipeline_run"] is None

    def test_get_health_no_csrf_token_required(self, csrf_client, _mock_health):
        """GET /health succeeds without a CSRF token (GET is exempt from guard)."""
        _mock_health({"healthy": True, "webui": "ok", "last_pipeline_run": None,
                      "scheduler_running": True, "scheduler_job_count": 0,
                      "channels": {}, "degraded_reasons": []})
        resp = csrf_client.get("/health")
        assert resp.status_code in (200, 503)
        assert resp.is_json


class TestComputeHealthJson:
    """Unit tests for compute_health_json() logic, independent of Flask."""

    def test_healthy_when_all_clear(self, monkeypatch):
        import webui_app.services.health_projection as hp

        monkeypatch.setattr(
            "webui_store.channel_status.list_all",
            lambda: {"medium": {"status": "bound"}},
        )
        _sched = type("S", (), {"running": True, "get_jobs": lambda self: [1, 2]})()
        monkeypatch.setattr("webui_app.scheduler._scheduler", _sched)
        import webui_store as _ws
        monkeypatch.setattr(_ws.history_store, "load",
                            lambda: [{"created_at": "2026-06-09T10:00:00Z"}])
        result = hp.compute_health_json()
        assert result["healthy"] is True
        assert result["degraded_reasons"] == []
        assert result["channels"] == {"medium": "bound"}

    def test_degraded_when_channel_expired(self, monkeypatch):
        import webui_app.services.health_projection as hp

        monkeypatch.setattr(
            "webui_store.channel_status.list_all",
            lambda: {"blogger": {"status": "expired"}},
        )
        _sched = type("S", (), {"running": True, "get_jobs": lambda self: []})()
        monkeypatch.setattr("webui_app.scheduler._scheduler", _sched)
        import webui_store as _ws
        monkeypatch.setattr(_ws.history_store, "load",
                            lambda: [{"created_at": "2026-06-09T10:00:00Z"}])
        result = hp.compute_health_json()
        assert result["healthy"] is False
        assert any("blogger" in r for r in result["degraded_reasons"])

    def test_degraded_when_no_history(self, monkeypatch):
        import webui_app.services.health_projection as hp

        monkeypatch.setattr("webui_store.channel_status.list_all", lambda: {})
        _sched = type("S", (), {"running": True, "get_jobs": lambda self: []})()
        monkeypatch.setattr("webui_app.scheduler._scheduler", _sched)
        import webui_store as _ws
        monkeypatch.setattr(_ws.history_store, "load", lambda: [])
        result = hp.compute_health_json()
        assert result["healthy"] is False
        assert "pipeline:never_run" in result["degraded_reasons"]
