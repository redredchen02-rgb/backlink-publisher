"""WebUI route contract tests — sites routes."""

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


def _fetch_csrf(client) -> str:
    """Grab the hidden csrf_token from GET /sites."""
    resp = client.get("/sites")
    assert resp.status_code == 200, resp.data[:200]
    match = re.search(r'name="csrf_token"\s+value="([^"]+)"', resp.data.decode())
    assert match, "csrf_token not found in /sites HTML"
    return match.group(1)


class TestSitesPostRoutes:
    def test_save_three_url_missing_csrf_returns_403(self, csrf_client):
        resp = csrf_client.post(
            "/sites/save-three-url",
            data={"main_url": "https://x.com/"},
        )
        assert resp.status_code == 403

    def test_save_three_url_invalid_main_url_returns_422(self, client):
        token = _fetch_csrf(client)
        resp = client.post(
            "/sites/save-three-url",
            data={"csrf_token": token, "main_url": "http://insecure.com/"},
        )
        assert resp.status_code == 422

    def test_save_three_url_valid_redirects(self, client, monkeypatch):
        # Avoid TDK fetch + work_scraper hitting the network
        monkeypatch.setattr(
            "webui.fetch_full_tdk",
            lambda url: {"title": "T", "description": "D"},
        )
        monkeypatch.setattr(
            "backlink_publisher.content.scraper.fetch_work_urls_from_list",
            lambda *a, **k: [],
        )
        token = _fetch_csrf(client)
        resp = client.post(
            "/sites/save-three-url",
            data={"csrf_token": token, "main_url": "https://x.com/"},
        )
        assert resp.status_code == 302
        assert resp.headers["Location"].startswith("/sites?")

    def test_sites_run_missing_csrf_returns_403(self, csrf_client):
        resp = csrf_client.post("/sites/run", data={"main_url": "https://x.com/"})
        assert resp.status_code == 403

    def test_sites_run_redirects_to_keep_alive(self, client):
        # U8/R2: POST /sites/run is collapsed into the keep-alive flow — it no
        # longer runs a plan or 400s on unknown domains; it always 302-redirects.
        resp = client.post("/sites/run", data={"main_url": "https://x.com/"})
        assert resp.status_code == 302
        assert resp.headers["Location"].endswith("/ce:keep-alive")


# ═════════════════════════════════════════════════════════════════════════════
# Batch campaign + equity-ledger optimization routes (Plan 2026-06-02-001 /
# 2026-06-05-001) — contract coverage so the route-contract gate stays green.
# Functional behavior lives in their own dedicated test modules.
# ═════════════════════════════════════════════════════════════════════════════



class TestCampaignRoutes:
    def test_batch_campaign_form_returns_200(self, client):
        resp = client.get("/batch-campaign")
        assert resp.status_code == 200

    def test_campaign_progress_unknown_id_returns_404(self, client):
        resp = client.get("/campaign/nonexistent-campaign-id")
        assert resp.status_code == 404

    def test_campaign_status_api_unknown_id_returns_404(self, client):
        resp = client.get("/api/campaign/nonexistent-campaign-id/status")
        assert resp.status_code == 404
        assert resp.headers["Content-Type"].startswith("application/json")



class TestScheduleRoutes:
    """Contract tests for /schedule and /api/scheduled (Plan 2026-05-29-001 Unit 2)."""

    def test_get_schedule_page(self, client, monkeypatch):
        """GET /schedule renders HTML."""
        import webui_app.api.scheduled_api as sched_api

        monkeypatch.setattr(sched_api, "list_scheduled", lambda: {"ok": True, "items": []})
        resp = client.get("/schedule")
        assert resp.status_code == 200
        assert b"html" in resp.data.lower()

    def test_get_api_scheduled(self, client, monkeypatch):
        """GET /api/scheduled returns JSON with ok + items keys."""
        import webui_app.api.scheduled_api as sched_api

        monkeypatch.setattr(sched_api, "list_scheduled", lambda: {"ok": True, "items": []})
        resp = client.get("/api/scheduled")
        assert resp.status_code == 200
        assert resp.is_json
        data = resp.get_json()
        assert "ok" in data
        assert "items" in data



class TestPrQueueRoutes:
    """Contract tests for /pr-queue and /api/pr-queue (B1 PR opportunity queue)."""

    def test_get_pr_queue_page(self, client, monkeypatch):
        """GET /pr-queue renders HTML."""
        import webui_app.routes.pr_queue as pq_mod

        monkeypatch.setattr(pq_mod, "_load", lambda: [])
        resp = client.get("/pr-queue")
        assert resp.status_code == 200
        assert b"html" in resp.data.lower()

    def test_get_api_pr_queue(self, client, monkeypatch):
        """GET /api/pr-queue returns JSON with ok + items keys."""
        import webui_app.routes.pr_queue as pq_mod

        monkeypatch.setattr(pq_mod, "_load", lambda: [])
        resp = client.get("/api/pr-queue")
        assert resp.status_code == 200
        assert resp.is_json
        data = resp.get_json()
        assert data["ok"] is True
        assert "items" in data

    def test_post_api_pr_queue_status_missing_csrf_returns_403(self, csrf_client):
        """POST /api/pr-queue/status without CSRF token is rejected."""
        resp = csrf_client.post(
            "/api/pr-queue/status",
            json={"id": "opp-1", "status": "won"},
        )
        assert resp.status_code == 403



