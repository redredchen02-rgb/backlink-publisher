"""WebUI route contract tests — history routes."""

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

class TestHistoryRoutes:
    def test_ce_history_post_returns_200(self, client):
        resp = client.post("/ce:history")
        assert resp.status_code == 200

    def test_ce_history_delete_with_unknown_id_returns_200(self, client):
        resp = client.post("/ce:history/delete", data={"id": "nonexistent"})
        assert resp.status_code == 200

    def test_ce_history_update_status_with_unknown_id_returns_200(self, client):
        resp = client.post(
            "/ce:history/update-status",
            data={"id": "nonexistent", "status": "published"},
        )
        assert resp.status_code == 200

    def test_ce_history_reuse_returns_200(self, client):
        resp = client.post(
            "/ce:history/reuse", data={"target_url": "https://x.com/"},
        )
        assert resp.status_code == 200


# ═════════════════════════════════════════════════════════════════════════════
# Draft queue POST routes — /ce:draft/*
# ═════════════════════════════════════════════════════════════════════════════



class TestDraftRoutes:
    def test_draft_save_with_empty_plans_redirects(self, client):
        resp = client.post("/ce:draft/save", data={"plans": ""})
        assert resp.status_code == 302
        assert resp.headers["Location"].startswith("/?tab=draft")

    def test_draft_save_with_plans_redirects(self, client):
        resp = client.post(
            "/ce:draft/save",
            data={
                "plans": '{"id": "x"}',
                "platform": "medium",
                "publish_mode": "draft",
            },
        )
        assert resp.status_code == 302
        assert resp.headers["Location"].startswith("/?tab=draft")

    def test_draft_schedule_missing_params_redirects(self, client):
        resp = client.post("/ce:draft/schedule", data={})
        assert resp.status_code == 302
        assert "/?tab=draft" in resp.headers["Location"]

    def test_draft_schedule_invalid_datetime_redirects(self, client):
        resp = client.post(
            "/ce:draft/schedule",
            data={"id": "abc", "scheduled_at": "not-a-datetime"},
        )
        assert resp.status_code == 302
        assert "/?tab=draft" in resp.headers["Location"]

    def test_draft_publish_now_missing_id_redirects(self, client):
        resp = client.post("/ce:draft/publish-now", data={})
        assert resp.status_code == 302
        assert "/?tab=draft" in resp.headers["Location"]

    def test_draft_publish_now_with_id_redirects(self, client):
        resp = client.post("/ce:draft/publish-now", data={"id": "anything"})
        assert resp.status_code == 302
        assert "/?tab=draft" in resp.headers["Location"]

    def test_draft_cancel_missing_id_redirects(self, client):
        resp = client.post("/ce:draft/cancel", data={})
        assert resp.status_code == 302
        assert "/?tab=draft" in resp.headers["Location"]

    def test_draft_cancel_with_id_redirects(self, client):
        resp = client.post("/ce:draft/cancel", data={"id": "nonexistent"})
        assert resp.status_code == 302
        assert "/?tab=draft" in resp.headers["Location"]

    def test_draft_delete_missing_id_redirects(self, client):
        resp = client.post("/ce:draft/delete", data={})
        assert resp.status_code == 302
        assert "/?tab=draft" in resp.headers["Location"]

    def test_draft_delete_with_id_redirects(self, client):
        resp = client.post("/ce:draft/delete", data={"id": "nonexistent"})
        assert resp.status_code == 302
        assert "/?tab=draft" in resp.headers["Location"]

    # Plan 2026-05-19-006 Unit 3 — bulk operations
    def test_draft_bulk_delete_empty_redirects(self, client):
        resp = client.post("/ce:draft/bulk-delete", data={})
        assert resp.status_code == 302
        assert "/?tab=draft" in resp.headers["Location"]

    def test_draft_bulk_publish_now_empty_redirects(self, client):
        resp = client.post("/ce:draft/bulk-publish-now", data={})
        assert resp.status_code == 302
        assert "/?tab=draft" in resp.headers["Location"]

    def test_draft_bulk_cancel_empty_redirects(self, client):
        resp = client.post("/ce:draft/bulk-cancel", data={})
        assert resp.status_code == 302
        assert "/?tab=draft" in resp.headers["Location"]



class TestHistoryBulkRoutes:
    """Plan 2026-05-19-006 Unit 4+5 — bulk + recheck history routes."""

    def test_history_bulk_delete_empty_redirects(self, client):
        resp = client.post("/ce:history/bulk-delete", data={})
        assert resp.status_code == 302

    def test_history_purge_failed_redirects(self, client):
        resp = client.post("/ce:history/purge-failed", data={})
        assert resp.status_code == 302

    def test_history_recheck_missing_id_redirects(self, client):
        resp = client.post("/ce:history/recheck", data={})
        assert resp.status_code == 302

    def test_history_bulk_recheck_empty_redirects(self, client):
        resp = client.post("/ce:history/bulk-recheck", data={})
        assert resp.status_code == 302


# ═════════════════════════════════════════════════════════════════════════════
# Settings POST routes — /settings/* and /profiles/*
# ═════════════════════════════════════════════════════════════════════════════



