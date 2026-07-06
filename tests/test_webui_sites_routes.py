"""WebUI route contract tests — sites routes."""

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
        resp = client.get("/campaign/nonexistent-campaign-id/jinja")
        assert resp.status_code == 404

    def test_campaign_progress_redirects_to_spa(self, client):
        # /campaign/<id> now redirects to the SPA; the /jinja fallback
        # (test_campaign_progress_unknown_id_returns_404 above) covers the render path.
        resp = client.get("/campaign/some-id")
        assert resp.status_code == 302
        assert "/app/campaign/some-id" in resp.location

    def test_campaign_status_api_unknown_id_returns_404(self, client):
        resp = client.get("/api/campaign/nonexistent-campaign-id/status")
        assert resp.status_code == 404
        assert resp.headers["Content-Type"].startswith("application/json")



class TestScheduleRoutes:
    """Contract tests for /schedule and /api/scheduled (Plan 2026-05-29-001 Unit 2)."""

    def test_get_schedule_redirects_to_spa(self, client):
        """GET /schedule redirects to SPA /app/schedule (Sprint B1)."""
        resp = client.get("/schedule")
        assert resp.status_code == 302
        assert resp.headers["Location"] == "/app/schedule"

    def test_get_schedule_jinja_page(self, client, monkeypatch):
        """GET /schedule/jinja renders HTML (legacy fallback)."""
        import webui_app.api.scheduled_api as sched_api

        monkeypatch.setattr(sched_api, "list_scheduled", lambda: {"ok": True, "items": []})
        resp = client.get("/schedule/jinja")
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
        """GET /pr-queue/jinja renders HTML (legacy fallback)."""
        import webui_app.routes.pr_queue as pq_mod

        monkeypatch.setattr(pq_mod, "_load", lambda: [])
        resp = client.get("/pr-queue/jinja")
        assert resp.status_code == 200
        assert b"html" in resp.data.lower()

    def test_get_pr_queue_redirects_to_spa(self, client):
        # /pr-queue now redirects to the SPA; the /jinja fallback
        # (test_get_pr_queue_page above) covers the render path.
        resp = client.get("/pr-queue")
        assert resp.status_code == 302
        assert "/app/pr-queue" in resp.location

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


# ── Autopilot routes (Plan 2026-06-09-001 U8) ─────────────────────────────

from datetime import UTC
import sys
import types


def _make_mock_scheduler(register_fn=None, remove_raises=False):
    """Build a minimal mock webui_app.scheduler for autopilot route tests."""
    from unittest.mock import MagicMock

    mod = types.ModuleType("webui_app.scheduler")
    mod._autopilot_job_id = lambda u: "autopilot_" + u.replace("://", "_").replace("/", "_").rstrip("_")
    mod._register_autopilot_job = register_fn or (lambda *a: None)
    mock_sch = MagicMock()
    if remove_raises:
        mock_sch.remove_job.side_effect = RuntimeError("not found")
    mock_sch.get_job.return_value.next_run_time.isoformat.return_value = "2026-06-17T10:00:00+08:00"
    mod._scheduler = mock_sch
    return mod


class TestSitesAutopilot:
    def test_enable_returns_200_and_updates_store(self, client, monkeypatch):
        import webui_store as _ws

        monkeypatch.setitem(sys.modules, "webui_app.scheduler", _make_mock_scheduler())
        resp = client.post("/sites/autopilot", json={
            "site_url": "https://example.com/",
            "enabled": True,
            "interval_seconds": 86400,
        })
        assert resp.status_code == 200
        assert resp.get_json()["ok"] is True
        targets = _ws.schedule_store.load().get("autopilot_targets", {})
        assert targets.get("https://example.com/", {}).get("enabled") is True

    def test_disable_removes_job(self, client, monkeypatch):
        import webui_store as _ws

        removed = []
        mock_sched = _make_mock_scheduler()
        mock_sched._scheduler.remove_job.side_effect = lambda jid: removed.append(jid)
        monkeypatch.setitem(sys.modules, "webui_app.scheduler", mock_sched)

        resp = client.post("/sites/autopilot", json={
            "site_url": "https://example.com/",
            "enabled": False,
        })
        assert resp.status_code == 200
        targets = _ws.schedule_store.load().get("autopilot_targets", {})
        assert targets.get("https://example.com/", {}).get("enabled") is False

    def test_interval_3599_returns_422(self, client):
        resp = client.post("/sites/autopilot", json={
            "site_url": "https://example.com/",
            "enabled": True,
            "interval_seconds": 3599,
        })
        assert resp.status_code == 422

    def test_interval_2592001_returns_422(self, client):
        resp = client.post("/sites/autopilot", json={
            "site_url": "https://example.com/",
            "enabled": True,
            "interval_seconds": 2592001,
        })
        assert resp.status_code == 422

    def test_missing_site_url_returns_400(self, client):
        resp = client.post("/sites/autopilot", json={"enabled": True})
        assert resp.status_code == 400

    def test_scheduler_failure_returns_500_and_rolls_back(self, client, monkeypatch):
        import webui_store as _ws

        def _raise(*a):
            raise RuntimeError("APScheduler error")

        monkeypatch.setitem(sys.modules, "webui_app.scheduler", _make_mock_scheduler(register_fn=_raise))
        _ws.schedule_store.update(lambda s: {**s, "autopilot_targets": {}})

        resp = client.post("/sites/autopilot", json={
            "site_url": "https://example.com/",
            "enabled": True,
            "interval_seconds": 86400,
        })
        assert resp.status_code == 500
        targets = _ws.schedule_store.load().get("autopilot_targets", {})
        assert "https://example.com/" not in targets

    def test_enable_response_includes_next_run_time(self, client, monkeypatch):
        from datetime import datetime, timezone

        dt = datetime(2026, 6, 17, 12, 0, 0, tzinfo=UTC)
        mock = _make_mock_scheduler()
        mock._scheduler.get_job.return_value.next_run_time = dt
        monkeypatch.setitem(sys.modules, "webui_app.scheduler", mock)

        resp = client.post("/sites/autopilot", json={
            "site_url": "https://example.com/",
            "enabled": True,
            "interval_seconds": 86400,
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert "next_run_time" in data
        assert data["next_run_time"] is not None
        assert "2026-06-17" in data["next_run_time"]
        assert "last_run" in data

    def test_enable_response_next_run_time_null_when_get_job_none(self, client, monkeypatch):
        mock = _make_mock_scheduler()
        mock._scheduler.get_job.return_value = None
        monkeypatch.setitem(sys.modules, "webui_app.scheduler", mock)

        resp = client.post("/sites/autopilot", json={
            "site_url": "https://example.com/",
            "enabled": True,
            "interval_seconds": 86400,
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True
        assert data["next_run_time"] is None

    def test_disable_response_next_run_time_null(self, client, monkeypatch):
        monkeypatch.setitem(sys.modules, "webui_app.scheduler", _make_mock_scheduler())
        resp = client.post("/sites/autopilot", json={
            "site_url": "https://example.com/",
            "enabled": False,
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["next_run_time"] is None
        assert "last_run" in data

    def test_response_preserves_existing_fields(self, client, monkeypatch):
        monkeypatch.setitem(sys.modules, "webui_app.scheduler", _make_mock_scheduler())
        resp = client.post("/sites/autopilot", json={
            "site_url": "https://example.com/",
            "enabled": True,
            "interval_seconds": 86400,
        })
        data = resp.get_json()
        assert data["ok"] is True
        assert data["site_url"] == "https://example.com/"
        assert data["enabled"] is True


class TestSitesAutopilotStatus:
    """Tests for GET /sites returning autopilot status fields."""

    def test_get_sites_with_scheduler_returns_200(self, client, monkeypatch):
        from datetime import datetime, timezone

        dt = datetime(2026, 6, 17, 15, 0, 0, tzinfo=UTC)
        mock = _make_mock_scheduler()
        mock._scheduler.get_job.return_value.next_run_time = dt
        monkeypatch.setitem(sys.modules, "webui_app.scheduler", mock)

        resp = client.get("/sites")
        assert resp.status_code == 200

    def test_get_sites_with_alert_pending_no_500(self, client, monkeypatch):
        import webui_store as _ws

        _ws.schedule_store.update(lambda s: {**s, "autopilot_targets": {
            "https://example.com/": {"enabled": True, "alert_pending": True, "interval_seconds": 86400}
        }})
        monkeypatch.setitem(sys.modules, "webui_app.scheduler", _make_mock_scheduler())

        resp = client.get("/sites")
        assert resp.status_code == 200

    def test_get_sites_scheduler_unavailable_no_500(self, client):
        resp = client.get("/sites")
        assert resp.status_code == 200

    def test_get_sites_scheduler_present_but_unstarted_no_500(self, client, monkeypatch):
        import types
        mod = types.ModuleType("webui_app.scheduler")
        mod._scheduler = None
        mod._autopilot_job_id = lambda u: "autopilot_" + u
        monkeypatch.setitem(sys.modules, "webui_app.scheduler", mod)

        resp = client.get("/sites")
        assert resp.status_code == 200

    def test_get_sites_no_500(self, client, monkeypatch):
        monkeypatch.setitem(sys.modules, "webui_app.scheduler", _make_mock_scheduler())
        resp = client.get("/sites")
        assert resp.status_code == 200

    # ── HTML content tests for the 4 Jinja status branches ───────────────

    @staticmethod
    def _register_site(url="https://example.com/"):
        """Add a minimal ThreeUrlConfig entry so the template renders site rows."""
        from backlink_publisher.config import load_config, save_config, ThreeUrlConfig
        save_config(load_config(), target_three_url={
            url.rstrip("/"): ThreeUrlConfig(
                main_url=url, list_url=url,
                branded_pool=["Example"], partial_pool=["example"], exact_pool=["example.com"], work_urls=[],
            )
        })

    def test_html_disabled_shows_dash(self, client, monkeypatch):
        """Branch: not site.autopilot_enabled → '—' span."""
        import webui_store as _ws

        self._register_site()
        _ws.schedule_store.update(lambda s: {**s, "autopilot_targets": {
            "https://example.com/": {"enabled": False, "interval_seconds": 86400}
        }})
        monkeypatch.setitem(sys.modules, "webui_app.scheduler", _make_mock_scheduler())
        resp = client.get("/sites")
        assert resp.status_code == 200
        assert b"autopilot-row-status" in resp.data
        assert b"text-danger" not in resp.data
        assert b"autopilot-next-run" not in resp.data

    def test_html_alert_pending_shows_failure_span(self, client, monkeypatch):
        """Branch: site.alert_pending → text-danger '⚠ 上次失敗'."""
        import webui_store as _ws

        self._register_site()
        _ws.schedule_store.update(lambda s: {**s, "autopilot_targets": {
            "https://example.com/": {"enabled": True, "alert_pending": True, "interval_seconds": 86400}
        }})
        monkeypatch.setitem(sys.modules, "webui_app.scheduler", _make_mock_scheduler())
        resp = client.get("/sites")
        assert resp.status_code == 200
        assert b"text-danger" in resp.data
        assert "上次失敗".encode() in resp.data

    def test_html_next_run_time_shows_data_attribute(self, client, monkeypatch):
        """Branch: site.next_run_time_iso → autopilot-next-run span with data-next-run."""
        from datetime import datetime, timezone

        import webui_store as _ws

        self._register_site()
        _ws.schedule_store.update(lambda s: {**s, "autopilot_targets": {
            "https://example.com/": {"enabled": True, "interval_seconds": 86400}
        }})
        mock = _make_mock_scheduler()
        dt = datetime(2026, 6, 17, 15, 0, 0, tzinfo=UTC)
        mock._scheduler.get_job.return_value.next_run_time = dt
        monkeypatch.setitem(sys.modules, "webui_app.scheduler", mock)
        resp = client.get("/sites")
        assert resp.status_code == 200
        assert b"autopilot-next-run" in resp.data
        assert b"data-next-run=" in resp.data
        assert b"2026-06-17" in resp.data

    def test_html_enabled_no_next_run_shows_scheduling(self, client, monkeypatch):
        """Branch: enabled + no alert_pending + no next_run_time_iso → '排程中…'."""
        import webui_store as _ws

        self._register_site()
        _ws.schedule_store.update(lambda s: {**s, "autopilot_targets": {
            "https://example.com/": {"enabled": True, "interval_seconds": 86400}
        }})
        mock = _make_mock_scheduler()
        mock._scheduler.get_job.return_value = None   # no job → next_run_time_iso stays None
        monkeypatch.setitem(sys.modules, "webui_app.scheduler", mock)
        resp = client.get("/sites")
        assert resp.status_code == 200
        assert "排程中…".encode() in resp.data


class TestPlanGapSummary:
    def test_missing_file_returns_missing_status(self, tmp_path):
        from webui_app.routes.sites import _plan_gap_summary

        summary = _plan_gap_summary(tmp_path / "missing.json")

        assert summary == {"status": "missing"}

    def test_valid_jsonl_counts_candidates_and_targets(self, tmp_path):
        from webui_app.routes.sites import _plan_gap_summary

        path = tmp_path / "plan-gap-latest.json"
        path.write_text(
            "\n".join([
                json.dumps({"target_url": "https://example.com/a", "platform": "blogger"}),
                json.dumps({"target_url": "https://example.com/a", "platform": "medium"}),
                json.dumps({"target_url": "https://example.com/b", "platform": "devto"}),
            ]),
            encoding="utf-8",
        )

        summary = _plan_gap_summary(path)

        assert summary["status"] == "ok"
        assert summary["candidate_count"] == 3
        assert summary["target_count"] == 2
        assert "triggered_at" in summary

    def test_invalid_jsonl_returns_invalid_status(self, tmp_path):
        from webui_app.routes.sites import _plan_gap_summary

        path = tmp_path / "plan-gap-latest.json"
        path.write_text('{"target_url": "https://example.com/a"}\n{broken', encoding="utf-8")

        summary = _plan_gap_summary(path)

        assert summary["status"] == "invalid"
        assert "JSONL" in summary["error"]


class TestDashboardAutopilotAlertDismiss:
    def test_dismiss_clears_alert_pending(self, client):
        import webui_store as _ws

        _ws.schedule_store.update(lambda s: {
            **s,
            "autopilot_targets": {
                "https://example.com/": {"enabled": True, "alert_pending": True}
            }
        })
        resp = client.post(
            "/dashboard/autopilot-alert/dismiss",
            json={"site_url": "https://example.com/"},
        )
        assert resp.status_code == 200
        targets = _ws.schedule_store.load().get("autopilot_targets", {})
        assert targets["https://example.com/"]["alert_pending"] is False

    def test_dismiss_does_not_disable_autopilot(self, client):
        import webui_store as _ws

        _ws.schedule_store.update(lambda s: {
            **s,
            "autopilot_targets": {
                "https://example.com/": {"enabled": True, "alert_pending": True}
            }
        })
        client.post(
            "/dashboard/autopilot-alert/dismiss",
            json={"site_url": "https://example.com/"},
        )
        targets = _ws.schedule_store.load().get("autopilot_targets", {})
        assert targets["https://example.com/"]["enabled"] is True

    def test_dismiss_missing_site_url_returns_400(self, client):
        resp = client.post("/dashboard/autopilot-alert/dismiss", json={})
        assert resp.status_code == 400


class TestHealthAutopilotAlerts:
    def test_health_route_renders_alert_banner_when_pending(self, client):
        import webui_store as _ws

        _ws.schedule_store.update(lambda s: {
            **s,
            "autopilot_targets": {
                "https://example.com/": {"enabled": True, "alert_pending": True, "error": "timeout"}
            }
        })
        resp = client.get("/ce:health")
        assert resp.status_code == 200
        assert b"autopilot-alert-banner" in resp.data

    def test_health_route_no_banner_when_no_alerts(self, client):
        resp = client.get("/ce:health")
        assert resp.status_code == 200
        assert b"autopilot-alert-banner" not in resp.data
