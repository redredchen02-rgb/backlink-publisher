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

    def test_get_health_alerts_returns_200(self, client):
        """GET /health/alerts returns 200 with active alert list."""
        resp = client.get("/health/alerts")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "active" in data
        assert "count" in data
        assert isinstance(data["active"], list)
        assert isinstance(data["count"], int)

    def test_get_health_alerts_no_csrf_token_required(self, csrf_client):
        """GET /health/alerts does not require CSRF token (GET is exempt)."""
        resp = csrf_client.get("/health/alerts")
        assert resp.status_code == 200
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
        assert result["last_successful_pipeline_run"] is None

    def test_last_successful_pipeline_run_picks_latest_published(self, monkeypatch):
        """Sprint E3: informational timestamp of the last *successful* run,
        distinct from last_pipeline_run (which counts any attempt)."""
        import webui_app.services.health_projection as hp

        monkeypatch.setattr("webui_store.channel_status.list_all", lambda: {})
        _sched = type("S", (), {"running": True, "get_jobs": lambda self: []})()
        monkeypatch.setattr("webui_app.scheduler._scheduler", _sched)
        import webui_store as _ws
        monkeypatch.setattr(
            _ws.history_store,
            "load",
            lambda: [
                {"created_at": "2026-06-01T00:00:00Z", "status": "published"},
                {"created_at": "2026-06-15T00:00:00Z", "status": "failed"},
            ],
        )
        result = hp.compute_health_json()
        # last_pipeline_run counts the failed attempt too (most recent overall).
        assert result["last_pipeline_run"] == "2026-06-15T00:00:00Z"
        # last_successful_pipeline_run only considers the "published" item.
        assert result["last_successful_pipeline_run"] == "2026-06-01T00:00:00Z"

    def test_last_successful_pipeline_run_none_when_all_failed(self, monkeypatch):
        """No GSC/pipeline-success data yet (every run failed or unverified):
        degrade gracefully to None, never raise."""
        import webui_app.services.health_projection as hp

        monkeypatch.setattr("webui_store.channel_status.list_all", lambda: {})
        _sched = type("S", (), {"running": True, "get_jobs": lambda self: []})()
        monkeypatch.setattr("webui_app.scheduler._scheduler", _sched)
        import webui_store as _ws
        monkeypatch.setattr(
            _ws.history_store,
            "load",
            lambda: [
                {"created_at": "2026-06-01T00:00:00Z", "status": "failed"},
                {"created_at": "2026-06-02T00:00:00Z", "status": "blogger_unverified"},
            ],
        )
        result = hp.compute_health_json()
        assert result["last_pipeline_run"] == "2026-06-02T00:00:00Z"
        assert result["last_successful_pipeline_run"] is None


class TestWeightsSnapshotPanel:
    """GET /ce:health weights snapshot panel (Plan 2026-06-16-002 U9)."""

    def test_weights_snapshot_empty_state(self, client, monkeypatch):
        """No optimization_state.json → page renders 200, no 500."""
        monkeypatch.setattr(
            "webui_app.health_metrics.weights_snapshot",
            lambda: None,
        )
        resp = client.get("/ce:health")
        assert resp.status_code == 200
        body = resp.data.decode()
        assert "尚未執行 weights optimize" in body

    def test_weights_snapshot_with_data(self, client, monkeypatch):
        """With optimization state, /ce:health shows top-channel names and weights."""
        fake_snap = {
            "updated_at": "2026-06-16T07:00:00Z",
            "top_channels": [
                {"name": "blogger", "weight": 1.2, "updated_at": "2026-06-16T07:00:00Z"},
                {"name": "medium", "weight": 1.0, "updated_at": "2026-06-16T07:00:00Z"},
            ],
        }
        monkeypatch.setattr(
            "webui_app.health_metrics.weights_snapshot",
            lambda: fake_snap,
        )
        resp = client.get("/ce:health")
        assert resp.status_code == 200
        body = resp.data.decode()
        assert "blogger" in body
        assert "Weights 優化快照" in body


class TestDecayAlertBanner:
    def test_no_decay_alerts_renders_ok(self, client, monkeypatch):
        """No decay.alert events → page renders 200, no banner."""
        monkeypatch.setattr(
            "webui_app.routes.health._decay_alerts",
            lambda: [],
        )
        resp = client.get("/ce:health")
        assert resp.status_code == 200
        assert "Decay alert" not in resp.data.decode()

    def test_decay_alerts_shown_in_banner(self, client, monkeypatch):
        """decay.alert events → red banner with target_url and lost_count."""
        fake_alerts = [
            {"target_url": "https://example.com/page", "lost_count": 3, "ts": "2026-06-16T04:30:00Z"},
        ]
        monkeypatch.setattr(
            "webui_app.routes.health._decay_alerts",
            lambda: fake_alerts,
        )
        resp = client.get("/ce:health")
        assert resp.status_code == 200
        body = resp.data.decode()
        assert "Decay alert" in body
        assert "example.com/page" in body
        assert "3 link" in body
