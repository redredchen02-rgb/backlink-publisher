"""WebUI route contract tests — settings routes."""

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

class TestSettingsRoutes:
    def test_save_target_keywords_empty_redirects(self, client):
        resp = client.post(
            "/settings/save-target-keywords", data={"domain_count": "0"},
        )
        assert resp.status_code == 302
        assert resp.headers["Location"].startswith("/settings?")

    def test_save_target_keywords_with_oversize_keyword_redirects(self, client):
        """Keyword >60 chars → redirect with danger flash, not 422."""
        resp = client.post(
            "/settings/save-target-keywords",
            data={
                "domain_count": "1",
                "domain_1": "https://x.com/",
                "keywords_1": "X" * 100,
            },
        )
        assert resp.status_code == 302
        assert "/settings?" in resp.headers["Location"]

    def test_settings_schedule_save_valid_redirects(self, client):
        resp = client.post(
            "/settings/schedule",
            data={"min_interval_hours": "4", "jitter_minutes": "30"},
        )
        assert resp.status_code == 302
        assert resp.headers["Location"].startswith("/settings?")

    def test_settings_schedule_save_invalid_redirects(self, client):
        resp = client.post(
            "/settings/schedule",
            data={"min_interval_hours": "not-a-number"},
        )
        assert resp.status_code == 302
        assert resp.headers["Location"].startswith("/settings?")

    def test_save_blog_ids_redirects(self, client):
        resp = client.post(
            "/settings/save-blog-ids",
            data={"domain[]": "https://x.com/", "blog_id[]": "12345"},
        )
        assert resp.status_code == 302
        assert resp.headers["Location"].startswith("/settings?")

    def test_save_blog_ids_empty_redirects(self, client):
        resp = client.post("/settings/save-blog-ids", data={})
        assert resp.status_code == 302
        assert resp.headers["Location"].startswith("/settings?")

    def test_save_medium_token_with_value_redirects(self, client):
        resp = client.post(
            "/settings/save-medium-token",
            data={"medium_token": "Bearer test-token-1234"},
        )
        assert resp.status_code == 302
        assert resp.headers["Location"].startswith("/settings?")

    def test_save_medium_token_empty_redirects(self, client):
        resp = client.post(
            "/settings/save-medium-token", data={"medium_token": ""},
        )
        assert resp.status_code == 302
        assert resp.headers["Location"].startswith("/settings?")

    def test_clear_medium_token_redirects(self, client):
        resp = client.post("/settings/clear-medium-token")
        assert resp.status_code == 302
        assert resp.headers["Location"].startswith("/settings?")

    def test_clear_medium_oauth_redirects(self, client):
        resp = client.post("/settings/clear-medium-oauth")
        assert resp.status_code == 302
        assert resp.headers["Location"].startswith("/settings?")

    # ── Plan 013 Phase B: browser-login routes ────────────────────────────────
    # CSRF: the bespoke before_request 302-danger layer was retired (it was dead
    # code behind the app-level _global_csrf_guard). A POST without a valid
    # canonical csrf_token is now rejected with 403 by the global guard.

    def test_medium_launch_browser_login_no_csrf_forbidden(self, client):
        resp = client.post("/settings/medium/launch-browser-login", data={})
        assert resp.status_code == 403

    def test_medium_probe_browser_login_no_csrf_forbidden(self, client):
        resp = client.post("/settings/medium/probe-browser-login", data={})
        assert resp.status_code == 403

    def test_medium_clear_browser_login_no_csrf_forbidden(self, client):
        resp = client.post("/settings/medium/clear-browser-login", data={})
        assert resp.status_code == 403

    def test_revoke_blogger_redirects(self, client):
        resp = client.post("/settings/revoke-blogger")
        assert resp.status_code == 302
        assert resp.headers["Location"].startswith("/settings?")

    def test_save_blogger_oauth_missing_creds_redirects(self, client):
        resp = client.post(
            "/settings/save-blogger-oauth",
            data={"client_id": "", "client_secret": ""},
        )
        assert resp.status_code == 302
        assert resp.headers["Location"].startswith("/settings?")

    def test_save_blogger_oauth_with_creds_redirects(self, client):
        resp = client.post(
            "/settings/save-blogger-oauth",
            data={"client_id": "fake-id", "client_secret": "fake-secret"},
        )
        assert resp.status_code == 302
        assert resp.headers["Location"].startswith("/settings?")

    def test_blogger_oauth_start_missing_creds_redirects(self, client):
        resp = client.post(
            "/settings/blogger/oauth-start",
            data={"client_id": "", "client_secret": ""},
        )
        assert resp.status_code == 302
        assert resp.headers["Location"].startswith("/settings?")

    def test_profiles_save_empty_name_returns_json_error(self, client):
        resp = client.post("/profiles/save", data={"profile_name": ""})
        assert resp.status_code == 200
        assert resp.is_json
        data = resp.get_json()
        assert data["ok"] is False

    def test_profiles_save_with_name_returns_json_ok(self, client):
        resp = client.post(
            "/profiles/save",
            data={
                "profile_name": "test",
                "platform": "blogger",
                "language": "zh-CN",
            },
        )
        assert resp.status_code == 200
        assert resp.is_json
        data = resp.get_json()
        assert data["ok"] is True

    def test_profiles_delete_redirects(self, client):
        resp = client.post(
            "/profiles/delete", data={"profile_name": "nonexistent"},
        )
        # No referer → redirect to /
        assert resp.status_code == 302


# ═════════════════════════════════════════════════════════════════════════════
# Checkpoint POST routes — /checkpoint/*
# ═════════════════════════════════════════════════════════════════════════════



class TestBindRoutes:
    """Plan 2026-05-19-001 Unit 4 + Plan 003 Unit 4 — POST + GET smoke for
    the bind blueprint and identity-mismatch resolution routes.

    Deeper lifecycle assertions live in test_webui_bind_routes.py. The
    smoke tests here exist to satisfy the route-coverage gate below.
    """

    def test_post_bind_missing_csrf_returns_403(self, client):
        resp = client.post("/settings/channels/medium/bind", data={})
        assert resp.status_code == 403

    def test_poll_bind_unknown_job_returns_404(self, client):
        resp = client.get("/settings/channels/medium/bind/deadbeef")
        assert resp.status_code == 404

    def test_post_identity_mismatch_keep_missing_csrf_returns_403(self, client):
        resp = client.post(
            "/settings/channels/medium/identity-mismatch/keep", data={}
        )
        assert resp.status_code == 403

    def test_post_identity_mismatch_replace_missing_csrf_returns_403(self, client):
        resp = client.post(
            "/settings/channels/medium/identity-mismatch/replace", data={}
        )
        assert resp.status_code == 403



class TestChannelBindingAPIRoutes:
    """Plan 2026-05-19-006 Unit 4 — generic /api/<channel>/* dashboard endpoints.

    Full behavior tests live in tests/test_generic_channel_api.py. These
    smoke tests satisfy the route-coverage gate below.
    """

    def test_get_channel_status_returns_200(self, client):
        resp = client.get("/api/blogger/status")
        assert resp.status_code == 200

    def test_post_channel_verify_missing_csrf_returns_403(self, csrf_client):
        resp = csrf_client.post("/api/blogger/verify")
        assert resp.status_code == 403

    def test_post_channel_dry_run_missing_csrf_returns_403(self, csrf_client):
        resp = csrf_client.post("/api/blogger/dry-run")
        assert resp.status_code == 403



class TestTokenPasteRoutes:
    """Plan 006 follow-up (2026-05-20) — token-paste binding for ghpages.
    (Legacy retired channel.) Full lifecycle in
    tests/test_webui_token_paste.py; this smoke test satisfies the
    route-coverage gate below."""

    def test_post_save_channel_token_missing_csrf_returns_403(self, csrf_client):
        resp = csrf_client.post("/settings/save-channel-token")
        assert resp.status_code == 403



class TestChannelBindSaveRoutes:
    """Plan 2026-05-26-002 Unit 4 — generic credential save route smoke.
    Full lifecycle in tests/test_channel_bind_save.py; this satisfies the
    route-coverage gate below."""

    def test_post_save_channel_credential_missing_csrf_returns_403(self, csrf_client):
        resp = csrf_client.post("/settings/save-channel-credential")
        assert resp.status_code == 403



class TestNotionTokenRoutes:
    """Contract tests for Plan 003 Phase 2 Notion token routes."""

    def test_save_notion_token_redirects_on_success(self, client):
        resp = client.post(
            "/settings/save-notion-token",
            data={
                "integration_token": "secret_test123",
                "database_id": "db_abc456",
            },
        )
        assert resp.status_code == 302
        assert resp.headers["Location"].startswith("/settings?")

    def test_save_notion_token_rejects_empty_token(self, client):
        resp = client.post(
            "/settings/save-notion-token",
            data={"integration_token": "", "database_id": "db_abc456"},
        )
        assert resp.status_code == 302
        assert b"flash_type=danger" in resp.data or b"flash_type=info" in resp.data



