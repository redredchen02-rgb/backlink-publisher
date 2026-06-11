"""WebUI route contract tests — content routes."""

from __future__ import annotations

__tier__ = "integration"

import json
import os
import re
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ── _no_real_subprocess: belt-and-suspenders backup for _no_run_pipe ─────────

@pytest.fixture(autouse=True)
def _no_real_subprocess():
    """Stub subprocess.run so routes never shell out to real CLI binaries."""
    import subprocess as sp_mod

    def _fake_run(cmd, *_args, **_kwargs):
        result = sp_mod.CompletedProcess(args=cmd, returncode=0)
        result.stdout = ""
        result.stderr = ""
        return result

    with patch("subprocess.run", side_effect=_fake_run):
        yield

# ── _no_run_pipe: stub run_pipe so routes don't shell out ─────────────────────

@pytest.fixture(autouse=True)
def _no_run_pipe():
    """Stub run_pipe in every webui consumer module so routes don't shell out."""

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


# ── _isolated_webui_state: redirect store singletons to per-test tmp ─────────

@pytest.fixture(autouse=True)
def _isolated_webui_state(tmp_path, monkeypatch):
    """Redirect webui_store singleton paths to a per-test tmp dir."""
    import webui_store as _ws

    state_dir = tmp_path / "webui_state"
    state_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(_ws.history_store, "path", state_dir / "publish-history.json")
    monkeypatch.setattr(_ws.profiles_store, "path", state_dir / "webui.db")
    monkeypatch.setattr(_ws.drafts_store, "path", state_dir / "webui.db")
    monkeypatch.setattr(_ws.schedule_store, "path", state_dir / "webui.db")



# ═════════════════════════════════════════════════════════════════════════════

class TestUrlVerifyRoutes:
    """Plan v1.0 Unit 3 — /url-verify route smoke. Full lifecycle in
    tests/test_webui_url_verify_routes.py; this satisfies the route-coverage
    gate below."""

    def test_post_url_verify_missing_csrf_returns_403(self, client):
        resp = client.post("/url-verify")
        assert resp.status_code == 403



class TestSeoVizRoutes:
    """Contract test for /api/seo/anchors — exposes report-anchors data
    to the dashboard charting layer."""

    def test_anchors_missing_domain_returns_400(self, client):
        """GET /api/seo/anchors without ?domain= rejects with 400 + json."""
        resp = client.get("/api/seo/anchors")
        assert resp.status_code == 400
        assert resp.is_json
        body = resp.get_json()
        assert "error" in body

    def test_anchors_with_domain_invokes_report_anchors(self, client, monkeypatch):
        """GET /api/seo/anchors?domain=<d> calls AnchorData.from_report
        and returns the chart-data shape on success."""
        from webui_app.services import seo_viz as svc

        fake = svc.AnchorData(
            main_domain="https://example.com",
            total_entries=3,
            type_stats={"brand": {"count": 1}, "natural": {"count": 2}},
            alarm={},
        )
        monkeypatch.setattr(svc.AnchorData, "from_report", classmethod(lambda cls, d: fake))
        resp = client.get("/api/seo/anchors?domain=https://example.com")
        assert resp.status_code == 200
        assert resp.is_json
        body = resp.get_json()
        assert "labels" in body



class TestLlmRoutes:
    def test_llm_logs_route_is_removed(self, client):
        # /settings/llm-logs (llm_diag blueprint) was a placeholder returning
        # mocked metrics; removed in webui-006 Quick-Wins along with its
        # settings.html consumer block. A 404 here is the contract.
        resp = client.get("/settings/llm-logs")
        assert resp.status_code == 404

    def test_test_llm_connection_returns_json(self, client):
        resp = client.post("/settings/test-llm-connection", data={})
        assert resp.status_code == 200
        assert resp.is_json

    def test_save_llm_config_redirects(self, client):
        resp = client.post(
            "/settings/save-llm-config",
            data={"endpoint": "https://api.example.com/v1", "api_key": "sk-test",
                  "model": "gpt-4o", "temperature": "0.7"},
        )
        assert resp.status_code == 302
        assert resp.headers["Location"].startswith("/settings?")

    def test_save_llm_config_clear_action_redirects(self, client):
        resp = client.post("/settings/save-llm-config", data={"action": "clear"})
        assert resp.status_code == 302
        assert resp.headers["Location"].startswith("/settings?")



class TestEquityLedgerRoutes:
    """Plan 2026-05-25-004 — equity-ledger route smoke. Full lifecycle in
    tests/test_webui_equity_ledger_route.py + _recheck.py; this satisfies the
    route-coverage gate below."""

    def test_get_equity_ledger(self, client):
        resp = client.get("/ce:equity-ledger")
        assert resp.status_code == 200

    def test_post_equity_ledger_recheck_missing_csrf_or_body(self, client):
        resp = client.post("/ce:equity-ledger/recheck")
        assert resp.status_code in (400, 403, 404, 415)



class TestEquityLedgerOptRoutes:
    def test_batch_recheck_invalid_filter_returns_400(self, client):
        resp = client.post("/ce:equity-ledger/batch-recheck", json={"filter": "bogus"})
        assert resp.status_code == 400

    def test_batch_recheck_status_unknown_job_returns_404(self, client):
        resp = client.get("/ce:equity-ledger/batch-recheck/nonexistent-job/status")
        assert resp.status_code == 404

    def test_fill_gaps_missing_target_returns_400(self, client):
        resp = client.post("/ce:equity-ledger/fill-gaps", json={})
        assert resp.status_code == 400


# ═════════════════════════════════════════════════════════════════════════════
# Queue + Dashboard routes — /ce:queue-task, /ce:dashboard, /ce:retry-task
# ═════════════════════════════════════════════════════════════════════════════



