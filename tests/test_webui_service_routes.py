"""WebUI route contract tests — service routes."""

from __future__ import annotations

__tier__ = "integration"

import json
import os
from pathlib import Path
import re
import sys
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

class TestQueueDashboardRoutes:
    def test_ce_dashboard_redirects_to_health(self, client):
        """Plan 2026-05-25-006 U3 — /ce:dashboard 302 → /ce:health.

        Repurposed from the Plan 012 target (/ce:history?section=in-progress):
        "dashboard" now means the publishing health dashboard. The in-progress
        task list is still reachable directly at /ce:history?section=in-progress.
        """
        resp = client.get("/ce:dashboard", follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers["Location"].endswith("/ce:health")

    def test_ce_health_renders_read_only_dashboard(self, client):
        """Plan 2026-05-25-006 U3 — /ce:health GET renders the health dashboard."""
        resp = client.get("/ce:health")
        assert resp.status_code == 200
        assert "Publishing Health" in resp.get_data(as_text=True)

    def test_dashboard_html_template_removed(self):
        """Plan 012 Unit 2 — dashboard.html template file deleted."""
        tpl = Path(__file__).resolve().parents[1] / "webui_app" / "templates" / "dashboard.html"
        assert not tpl.exists(), f"dashboard.html should be deleted but exists at {tpl}"

    def test_publish_panel_dom_removed(self, client):
        """Plan 012 Unit 1 — #publishPanel tab + pane removed from index.html."""
        resp = client.get("/jinja")
        assert resp.status_code == 200
        body = resp.data.decode("utf-8", errors="ignore")
        assert 'id="publishPanel"' not in body
        assert 'id="publish-tab"' not in body
        assert "ready_to_publish" not in body

    def test_ce_queue_task_returns_json(self, client):
        resp = client.post(
            "/ce:queue-task",
            data={"platform": "medium", "urls_json": '["https://example.com/"]'},
        )
        assert resp.status_code == 200
        assert resp.is_json
        data = resp.get_json()
        assert data["status"] == "queued"
        assert "task_id" in data

    def test_ce_retry_task_missing_id_returns_error(self, client):
        resp = client.post("/ce:retry-task", data={})
        assert resp.status_code == 200
        assert resp.is_json
        data = resp.get_json()
        assert data["status"] == "error"

    def test_ce_retry_task_unknown_id_returns_error(self, client):
        """Plan 2026-07-06-004 Unit 1: the previous implementation silently
        claimed success for a vanished/unknown task id — QueueSqliteStore's
        conditional UPDATE now affects zero rows, and retry_task() surfaces
        that as an error rather than pretending the retry worked."""
        resp = client.post("/ce:retry-task", data={"task_id": "nonexistent-id"})
        assert resp.status_code == 200
        assert resp.is_json
        data = resp.get_json()
        assert data["status"] == "error"

    def test_ce_retry_task_failed_task_is_reset_to_pending(self, client):
        import uuid

        from webui_store import queue_store
        task_id = f"retry-happy-{uuid.uuid4().hex}"
        queue_store.update(
            lambda tasks: tasks + [{"id": task_id, "status": "failed", "error": "boom"}]
        )

        resp = client.post("/ce:retry-task", data={"task_id": task_id})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"

        tasks = {t["id"]: t for t in queue_store.load()}
        assert tasks[task_id]["status"] == "pending"
        assert tasks[task_id]["error"] is None

    def test_ce_retry_task_processing_task_is_rejected(self, client):
        """Plan 2026-07-06-004 Unit 1: retry must not clobber a task the
        background scheduler (webui_app/scheduler.py::_process_queue_job) is
        currently mid-publish on — that would risk a duplicate publish."""
        import uuid

        from webui_store import queue_store
        task_id = f"retry-processing-{uuid.uuid4().hex}"
        queue_store.update(
            lambda tasks: tasks + [{"id": task_id, "status": "processing"}]
        )

        resp = client.post("/ce:retry-task", data={"task_id": task_id})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "error"

        # Status must remain 'processing' — not silently flipped to pending.
        tasks = {t["id"]: t for t in queue_store.load()}
        assert tasks[task_id]["status"] == "processing"



class TestKeepAliveRoutes:
    """Plan 2026-06-04-001 Units 4–7 — keep-alive screen + recheck/republish job
    routes. Full behaviour in tests/test_webui_keep_alive_status.py and
    tests/test_webui_keepalive_*.py; this satisfies the route-coverage gate."""

    def test_get_keep_alive_renders(self, client):
        assert client.get("/ce:keep-alive").status_code == 200

    def test_get_keep_alive_redirects_to_spa(self, client):
        # /ce:keep-alive now redirects to the SPA (P15 A1); the Jinja fallback
        # (test_get_keep_alive_renders above) covers the LITE-mode render path.
        resp = client.get("/ce:keep-alive")
        assert resp.status_code == 302
        assert "/app/keep-alive" in resp.location

    def test_action_routes_covered(self, client):
        # Route-coverage gate: hit each action route once (guards + state
        # machine asserted in the dedicated keepalive tests).
        assert client.post("/ce:keep-alive/recheck").status_code in (202, 403, 409)
        assert client.get("/ce:keep-alive/recheck-status/x").status_code == 404
        assert client.post("/ce:keep-alive/recheck-cancel/x").status_code in (403, 404)
        assert client.get("/ce:keep-alive/republish-token").status_code == 200
        assert client.post("/ce:keep-alive/republish").status_code in (400, 403)
        assert client.get("/ce:keep-alive/republish-status/x").status_code == 404
        # R8: cycle panel routes (plan 2026-06-08-001).
        assert client.get("/ce:keep-alive/cycle-status").status_code == 200
        assert client.post("/ce:keep-alive/reset-exhausted").status_code in (400, 403)



class TestCopilotRoutes:
    """Copilot route smoke. Full lifecycle lives in tests/test_copilot_routes.py;
    these calls satisfy the route-coverage gate below."""

    def test_get_copilot_advice(self, client, monkeypatch):
        from webui_app.services.copilot_advisor import AggregateResult

        monkeypatch.setattr(
            "webui_app.routes.copilot.cached_aggregate",
            lambda **_kwargs: AggregateResult(
                tool_results=[],
                findings=[],
                degraded=False,
                considered=0,
                problem_count=0,
            ),
        )
        resp = client.get("/copilot/advice")
        assert resp.status_code == 200

    def test_post_copilot_run_live_guarded(self, client):
        resp = client.post("/copilot/run-live")
        assert resp.status_code == 403

    def test_post_copilot_ask_no_llm_returns_400(self, client, tmp_path):
        """POST /copilot/ask without an LLM config returns 400 + json."""
        resp = client.post(
            "/copilot/ask",
            data='{"question": "hello"}',
            content_type="application/json",
        )
        assert resp.status_code == 400
        assert resp.is_json



class TestMetricsRoutes:
    """Contract test for /metrics Prometheus scrape endpoint."""

    def test_get_metrics_returns_text(self, client, monkeypatch):
        """GET /metrics returns 200 with text/plain Prometheus format."""
        import webui_app.routes.metrics as metrics_mod

        monkeypatch.setattr(metrics_mod, "_scrape_events_db", lambda: [])
        monkeypatch.setattr(metrics_mod, "_scrape_content_cache", lambda: [])
        monkeypatch.setattr(metrics_mod, "_scrape_publish_history", lambda: [])
        resp = client.get("/metrics")
        assert resp.status_code == 200
        assert b"bp_publish_total" in resp.data



class TestHealthActionRoutes:
    """Contract tests for /ce:health maintenance actions (Plan 2026-06-03-004 P2)."""

    def test_pause_platform_toggles(self, client):
        resp = client.post("/ce:health/pause", json={"platform": "medium", "paused": True})
        assert resp.status_code == 200
        assert resp.get_json()["paused"] is True

    def test_reverify_platform_returns_json(self, client):
        resp = client.post("/ce:health/reverify", json={"platform": "medium"})
        assert resp.status_code == 200
        assert "ready" in resp.get_json()

    def test_circuit_reset_platform_ok(self, client):
        resp = client.post("/ce:health/circuit-reset", json={"platform": "medium"})
        assert resp.status_code == 200
        assert resp.get_json()["ok"] is True

    def test_scorecard_links_drawer_data(self, client):
        # Plan 2026-06-05-009 U2 — per-link drawer data, read-only, fail-open.
        resp = client.get("/ce:health/scorecard/telegraph/links")
        assert resp.status_code == 200
        assert resp.get_json()["ok"] is True

    def test_scorecard_recheck_link_requires_origin(self, client):
        # Plan 2026-06-05-009 U4 — outbound probe; Origin guard rejects a
        # request with no Origin header (non-5xx contract).
        resp = client.post(
            "/ce:health/scorecard/recheck-link", json={"live_url": "https://x/1"}
        )
        assert resp.status_code == 403



class TestVelogApiRoutes:
    def test_velog_login_spawns_ok(self, client, monkeypatch, tmp_path):
        """POST /api/velog/login returns 200 + ok:true when helper reports survival."""

        from webui_app.services import browser_login as bl

        log_path = tmp_path / "velog_login.log"
        log_path.write_bytes(b"")
        monkeypatch.setattr(
            bl,
            "spawn_browser_login",
            lambda module, **kw: bl.SpawnResult(ok=True, error=None, log_path=log_path),
        )
        resp = client.post("/api/velog/login")
        assert resp.status_code == 200
        assert resp.is_json
        body = resp.get_json()
        assert body["ok"] is True
        assert body["log_path"] == str(log_path)

    def test_velog_login_surfaces_subprocess_error(self, client, monkeypatch, tmp_path):
        """POST /api/velog/login returns 500 + tail when helper reports early death."""
        from webui_app.services import browser_login as bl

        log_path = tmp_path / "velog_login.log"
        log_path.write_bytes(b"")
        monkeypatch.setattr(
            bl,
            "spawn_browser_login",
            lambda module, **kw: bl.SpawnResult(
                ok=False,
                error="TypeError: PipelineLogger.info() takes 2 positional arguments",
                log_path=log_path,
            ),
        )
        resp = client.post("/api/velog/login")
        assert resp.status_code == 500
        body = resp.get_json()
        assert body["ok"] is False
        assert "error_code" in body
        assert body["log_path"] == str(log_path)

    def test_velog_status_returns_json(self, client):
        """GET /api/velog/status returns JSON with a 'state' key."""
        resp = client.get("/api/velog/status")
        assert resp.status_code == 200
        assert resp.is_json
        data = resp.get_json()
        assert "state" in data
        assert data["state"] in ("err", "ok", "fresh", "warn", "cap_reached", "permission_denied")



class TestOptimizationStatusRoutes:
    def test_get_optimization_status_page(self, client):
        """GET /optimization-status returns 200 with expected text."""
        resp = client.get("/optimization-status")
        assert resp.status_code == 200
        assert b"Optimization Status" in resp.data or b"optimisation" in resp.data.lower()

    def test_get_optimization_status_redirects_to_spa(self, client):
        # /optimization-status now redirects to the SPA; the Jinja fallback
        # (test_get_optimization_status_page above) covers the render path.
        resp = client.get("/optimization-status")
        assert resp.status_code == 302
        assert "/app/optimization-status" in resp.location

    def test_post_set_weight_missing_csrf_returns_403(self, csrf_client):
        """POST /optimization-status/set-weight without CSRF token returns 403."""
        resp = csrf_client.post("/optimization-status/set-weight", data={
            "platform": "blogger", "weight": "0.5",
        })
        assert resp.status_code == 403

    def test_post_unlock_weight_returns_200(self, client):
        """POST /optimization-status/unlock-weight returns 200."""
        resp = client.post("/optimization-status/unlock-weight", data={"platform": "blogger"})
        assert resp.status_code in (200, 302, 400)

    def test_post_api_set_weight_json_returns_200(self, client):
        """POST /api/optimization-status/set-weight (JSON twin the SPA calls,
        Sprint B2 audit gap — see docs/plans/2026-06-30-001 B2) returns 200."""
        resp = client.post("/api/optimization-status/set-weight", json={
            "platform": "blogger", "weight": 0.5,
        })
        assert resp.status_code == 200
        assert resp.get_json()["ok"] is True

    def test_post_api_set_weight_json_missing_fields_is_400(self, client):
        resp = client.post("/api/optimization-status/set-weight", json={"platform": "blogger"})
        assert resp.status_code == 400
        assert resp.get_json()["ok"] is False

    def test_post_api_unlock_weight_json_returns_200(self, client):
        """POST /api/optimization-status/unlock-weight (JSON twin the SPA calls,
        Sprint B2 audit gap) returns 200."""
        resp = client.post("/api/optimization-status/unlock-weight", json={"platform": "blogger"})
        assert resp.status_code == 200
        assert resp.get_json()["ok"] is True

    def test_post_api_unlock_weight_json_missing_platform_is_400(self, client):
        resp = client.post("/api/optimization-status/unlock-weight", json={})
        assert resp.status_code == 400
        assert resp.get_json()["ok"] is False



class TestSurvivalDashboardRoutes:
    def test_get_survival_dashboard_page(self, client):
        """GET /survival-dashboard returns 200 (never 500 on empty store)."""
        resp = client.get("/survival-dashboard")
        assert resp.status_code == 200
        assert "存活率".encode() in resp.data

    def test_get_survival_dashboard_redirects_to_spa(self, client):
        # /survival-dashboard now redirects to the SPA; the Jinja fallback
        # (test_get_survival_dashboard_page above) covers the render path.
        resp = client.get("/survival-dashboard")
        assert resp.status_code == 302
        assert "/app/survival" in resp.location



class TestCommandCenterRoutes:
    def test_get_command_center_page(self, client):
        """GET /ce:command-center returns 200."""
        resp = client.get("/ce:command-center")
        assert resp.status_code == 200

    def test_post_gap_closure_returns_202_or_409(self, client):
        """POST /ce:command-center/gap-closure returns 202 or 409."""
        resp = client.post("/ce:command-center/gap-closure")
        assert resp.status_code in (202, 409)
        assert resp.is_json

    def test_get_jobs_list_returns_json(self, client):
        """GET /ce:command-center/jobs returns 200 + json."""
        resp = client.get("/ce:command-center/jobs")
        assert resp.status_code == 200
        assert resp.is_json

    def test_get_job_by_id_returns_404(self, client):
        """GET /ce:command-center/job/<nonexistent> returns 404."""
        resp = client.get("/ce:command-center/job/nonexistent-job-id")
        assert resp.status_code == 404



