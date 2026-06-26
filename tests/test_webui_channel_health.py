"""Tests for channel credential TTL helpers + liveness probe (Plan 2026-06-09-001 U4)."""

from __future__ import annotations

__tier__ = "unit"

from datetime import datetime, timedelta, timezone, UTC
import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ── credential_age_days / is_near_expiry ─────────────────────────────────────

class TestCredentialAgeDays:
    def test_returns_none_when_no_bound_at(self, monkeypatch):
        from webui_store.channel_status import credential_age_days
        monkeypatch.setattr(
            "webui_store.channel_status.get_status",
            lambda ch: {"status": "unbound", "bound_at": None},
        )
        assert credential_age_days("medium") is None

    def test_returns_days_for_recent_binding(self, monkeypatch):
        from webui_store.channel_status import credential_age_days
        ts = (datetime.now(UTC) - timedelta(days=3)).isoformat()
        monkeypatch.setattr(
            "webui_store.channel_status.get_status",
            lambda ch: {"status": "bound", "bound_at": ts},
        )
        age = credential_age_days("medium")
        assert age is not None
        assert 2.9 < age < 3.1

    def test_handles_z_suffix_timestamp(self, monkeypatch):
        from webui_store.channel_status import credential_age_days
        ts = (datetime.now(UTC) - timedelta(days=10)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        monkeypatch.setattr(
            "webui_store.channel_status.get_status",
            lambda ch: {"status": "bound", "bound_at": ts},
        )
        age = credential_age_days("blogger")
        assert age is not None
        assert 9.9 < age < 10.1


class TestIsNearExpiry:
    def test_true_when_bound_8_days_ago(self, monkeypatch):
        from webui_store.channel_status import is_near_expiry
        ts = (datetime.now(UTC) - timedelta(days=8)).isoformat()
        monkeypatch.setattr(
            "webui_store.channel_status.get_status",
            lambda ch: {"status": "bound", "bound_at": ts},
        )
        assert is_near_expiry("medium") is True

    def test_false_when_bound_6_days_ago(self, monkeypatch):
        from webui_store.channel_status import is_near_expiry
        ts = (datetime.now(UTC) - timedelta(days=6)).isoformat()
        monkeypatch.setattr(
            "webui_store.channel_status.get_status",
            lambda ch: {"status": "bound", "bound_at": ts},
        )
        assert is_near_expiry("medium") is False

    def test_false_when_no_bound_at(self, monkeypatch):
        from webui_store.channel_status import is_near_expiry
        monkeypatch.setattr(
            "webui_store.channel_status.get_status",
            lambda ch: {"status": "unbound", "bound_at": None},
        )
        assert is_near_expiry("medium") is False

    def test_custom_threshold(self, monkeypatch):
        from webui_store.channel_status import is_near_expiry
        ts = (datetime.now(UTC) - timedelta(days=3)).isoformat()
        monkeypatch.setattr(
            "webui_store.channel_status.get_status",
            lambda ch: {"status": "bound", "bound_at": ts},
        )
        assert is_near_expiry("medium", threshold_days=2) is True
        assert is_near_expiry("medium", threshold_days=5) is False


# ── probe_channel_liveness ────────────────────────────────────────────────────

class TestProbeChannelLiveness:
    def test_blogger_ok_returns_alive(self, monkeypatch):
        from webui_app.services.credential_service import probe_channel_liveness
        monkeypatch.setattr(
            "webui_app.helpers.channel_probes._get_blogger_token_status",
            lambda: {"state": "ok"},
        )
        assert probe_channel_liveness("blogger") == "alive"

    def test_blogger_expiring_returns_alive(self, monkeypatch):
        from webui_app.services.credential_service import probe_channel_liveness
        monkeypatch.setattr(
            "webui_app.helpers.channel_probes._get_blogger_token_status",
            lambda: {"state": "expiring"},
        )
        assert probe_channel_liveness("blogger") == "alive"

    def test_blogger_expired_returns_expired(self, monkeypatch):
        from webui_app.services.credential_service import probe_channel_liveness
        monkeypatch.setattr(
            "webui_app.helpers.channel_probes._get_blogger_token_status",
            lambda: {"state": "expired"},
        )
        assert probe_channel_liveness("blogger") == "expired"

    def test_blogger_none_returns_unreachable(self, monkeypatch):
        from webui_app.services.credential_service import probe_channel_liveness
        monkeypatch.setattr(
            "webui_app.helpers.channel_probes._get_blogger_token_status",
            lambda: {"state": "none"},
        )
        assert probe_channel_liveness("blogger") == "unreachable"

    def test_velog_ok_returns_alive(self, monkeypatch):
        from webui_app.services.credential_service import probe_channel_liveness
        monkeypatch.setattr(
            "webui_app.helpers.channel_probes._get_velog_status",
            lambda: {"state": "ok"},
        )
        assert probe_channel_liveness("velog") == "alive"

    def test_velog_permission_denied_returns_expired(self, monkeypatch):
        from webui_app.services.credential_service import probe_channel_liveness
        monkeypatch.setattr(
            "webui_app.helpers.channel_probes._get_velog_status",
            lambda: {"state": "permission_denied"},
        )
        assert probe_channel_liveness("velog") == "expired"

    def test_velog_err_returns_unreachable(self, monkeypatch):
        from webui_app.services.credential_service import probe_channel_liveness
        monkeypatch.setattr(
            "webui_app.helpers.channel_probes._get_velog_status",
            lambda: {"state": "err"},
        )
        assert probe_channel_liveness("velog") == "unreachable"

    def test_fallback_channel_bound_returns_alive(self, monkeypatch):
        from webui_app.services.credential_service import probe_channel_liveness
        monkeypatch.setattr(
            "webui_store.channel_status.get_status",
            lambda ch: {"status": "bound"},
        )
        assert probe_channel_liveness("devto") == "alive"

    def test_fallback_channel_expired_returns_expired(self, monkeypatch):
        from webui_app.services.credential_service import probe_channel_liveness
        monkeypatch.setattr(
            "webui_store.channel_status.get_status",
            lambda ch: {"status": "expired"},
        )
        assert probe_channel_liveness("devto") == "expired"


# ── probe-liveness route ──────────────────────────────────────────────────────

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
def _isolated_webui_state(tmp_path, monkeypatch):
    import webui_store as _ws

    state_dir = tmp_path / "webui_state"
    state_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(_ws.history_store, "path", state_dir / "publish-history.json")
    monkeypatch.setattr(_ws.profiles_store, "path", state_dir / "webui.db")
    monkeypatch.setattr(_ws.drafts_store, "path", state_dir / "webui.db")
    monkeypatch.setattr(_ws.schedule_store, "path", state_dir / "webui.db")


class TestProbeLivenessRoute:
    def test_probe_blogger_returns_status(self, client, monkeypatch):
        """POST /settings/channels/blogger/probe-liveness returns {status: alive}."""
        monkeypatch.setattr(
            "webui_app.services.credential_service.probe_channel_liveness",
            lambda ch: "alive",
        )
        resp = client.post("/settings/channels/blogger/probe-liveness")
        assert resp.status_code == 200
        assert resp.is_json
        assert resp.get_json()["status"] == "alive"

    def test_probe_expired_channel_returns_expired(self, client, monkeypatch):
        monkeypatch.setattr(
            "webui_app.services.credential_service.probe_channel_liveness",
            lambda ch: "expired",
        )
        resp = client.post("/settings/channels/velog/probe-liveness")
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "expired"
