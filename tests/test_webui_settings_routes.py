"""WebUI route contract tests — settings routes."""

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

class TestSettingsRoutes:
    def test_save_target_keywords_empty_redirects(self, client):
        resp = client.post(
            "/settings/save-target-keywords", data={"domain_count": "0"},
        )
        assert resp.status_code == 302
        assert resp.headers["Location"].startswith("/app/settings?")

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
        assert resp.headers["Location"].startswith("/app/settings?")

    def test_settings_schedule_save_invalid_redirects(self, client):
        resp = client.post(
            "/settings/schedule",
            data={"min_interval_hours": "not-a-number"},
        )
        assert resp.status_code == 302
        assert resp.headers["Location"].startswith("/app/settings?")

    def test_save_blog_ids_redirects(self, client):
        resp = client.post(
            "/settings/save-blog-ids",
            data={"domain[]": "https://x.com/", "blog_id[]": "12345"},
        )
        assert resp.status_code == 302
        assert resp.headers["Location"].startswith("/app/settings?")

    def test_save_blog_ids_empty_redirects(self, client):
        resp = client.post("/settings/save-blog-ids", data={})
        assert resp.status_code == 302
        assert resp.headers["Location"].startswith("/app/settings?")

    # Medium Integration-Token routes removed in U8 (Medium discontinued the tokens;
    # the management UI is retired — see settings_basic.py). No replacement endpoint.

    def test_clear_medium_oauth_redirects(self, client):
        resp = client.post("/settings/clear-medium-oauth")
        assert resp.status_code == 302
        assert resp.headers["Location"].startswith("/app/settings?")

    # medium browser-login tests removed — routes retired in U8 5b (Plan 2026-06-18-002).
    # CSRF enforcement on /api/v1/settings/medium/* covered by test_webui_api_v1_medium_login.

    def test_revoke_blogger_redirects(self, client):
        resp = client.post("/settings/revoke-blogger")
        assert resp.status_code == 302
        assert resp.headers["Location"].startswith("/app/settings?")

    def test_save_blogger_oauth_missing_creds_redirects(self, client):
        resp = client.post(
            "/settings/save-blogger-oauth",
            data={"client_id": "", "client_secret": ""},
        )
        assert resp.status_code == 302
        assert resp.headers["Location"].startswith("/app/settings?")

    def test_save_blogger_oauth_with_creds_redirects(self, client):
        resp = client.post(
            "/settings/save-blogger-oauth",
            data={"client_id": "fake-id", "client_secret": "fake-secret"},
        )
        assert resp.status_code == 302
        assert resp.headers["Location"].startswith("/app/settings?")

    def test_blogger_oauth_start_missing_creds_redirects(self, client):
        resp = client.post(
            "/settings/blogger/oauth-start",
            data={"client_id": "", "client_secret": ""},
        )
        assert resp.status_code == 302
        assert resp.headers["Location"].startswith("/app/settings?")

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



# TestBindRoutes removed — /settings/channels/*/bind routes retired in U8 5b.
# CSRF/loopback coverage now in test_webui_api_v1_bind.py.


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



# TestTokenPasteRoutes, TestChannelBindSaveRoutes, TestNotionTokenRoutes removed —
# routes retired in U8 5b (Plan 2026-06-18-002). Coverage in test_webui_api_v1_*.py.



