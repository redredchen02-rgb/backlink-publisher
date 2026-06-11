"""Tests for autopilot backend — run_keepalive_for_site, _keepalive_cycle_job,
_restore_scheduled_jobs (Plan 2026-06-09-001 U7).
"""

from __future__ import annotations

__tier__ = "unit"

import os
import sys
import types
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ── Break scheduler's circular import (same approach as test_webui_scheduler) ─

@pytest.fixture(scope="module")
def _sched_mod():
    """Load webui_app.scheduler without the drafts_api circular dependency."""
    _d = types.ModuleType("webui_app.api.drafts_api")
    _d.__package__ = "webui_app.api"
    _d.DraftAPI = MagicMock()
    _d._publish_draft_job = MagicMock()
    _d._scheduler = MagicMock()
    sys.modules.setdefault("webui_app.api.drafts_api", _d)

    import webui_app.scheduler as _mod
    return _mod


# ── run_keepalive_for_site ─────────────────────────────────────────────────────

class TestRunKeepaliveForSite:
    def test_returns_success_result_on_empty_candidates(self, monkeypatch):
        from webui_app.services.keepalive_job import run_keepalive_for_site
        monkeypatch.setattr(
            "webui_app.services._keepalive_engine._default_candidates",
            lambda store: [],
        )
        monkeypatch.setattr(
            "webui_app.services._keepalive_engine._default_unverified_candidates",
            lambda store: [],
        )
        monkeypatch.setattr(
            "webui_app.services._keepalive_engine.EventStore",
            lambda: MagicMock(),
        )
        result = run_keepalive_for_site("https://example.com/")
        assert result.success is True
        assert result.checked == 0
        assert result.error is None

    def test_filters_candidates_by_domain(self, monkeypatch):
        from webui_app.services.keepalive_job import run_keepalive_for_site

        cands = [
            {"target_url": "https://example.com/work/1"},  # matches
            {"target_url": "https://other.com/work/1"},    # does NOT match
        ]
        monkeypatch.setattr(
            "webui_app.services._keepalive_engine._default_candidates",
            lambda store: cands,
        )
        monkeypatch.setattr(
            "webui_app.services._keepalive_engine._default_unverified_candidates",
            lambda store: [],
        )
        monkeypatch.setattr(
            "webui_app.services._keepalive_engine.EventStore",
            lambda: MagicMock(),
        )
        probed = []
        monkeypatch.setattr(
            "webui_app.services._keepalive_engine._default_probe",
            lambda cand: (probed.append(cand) or {"verdict": "alive"}),
        )
        monkeypatch.setattr(
            "webui_app.services._keepalive_engine.emit_recheck", lambda *a: None
        )
        monkeypatch.setattr(
            "webui_app.services._keepalive_engine.write_verified_at", lambda *a: None
        )
        result = run_keepalive_for_site("https://example.com/")
        assert result.checked == 1
        assert probed[0]["target_url"] == "https://example.com/work/1"

    def test_per_site_lock_prevents_concurrent_run(self):
        from webui_app.services import keepalive_job as kj

        lock = kj._site_lock("https://busy.com/")
        lock.acquire()
        try:
            result = kj.run_keepalive_for_site("https://busy.com/")
            assert result.success is False
            assert "already running" in (result.error or "")
        finally:
            lock.release()

    def test_returns_graceful_error_when_eventstore_raises(self, monkeypatch):
        from webui_app.services.keepalive_job import run_keepalive_for_site

        def _boom():
            raise RuntimeError("no db")

        monkeypatch.setattr(
            "webui_app.services._keepalive_engine.EventStore",
            _boom,
        )
        result = run_keepalive_for_site("https://unknown-site.com/")
        assert result.success is False
        assert result.error is not None


# ── _autopilot_job_id ─────────────────────────────────────────────────────────

class TestAutopilotJobId:
    def test_deterministic(self, _sched_mod):
        jid = _sched_mod._autopilot_job_id("https://example.com/")
        assert jid == _sched_mod._autopilot_job_id("https://example.com/")

    def test_starts_with_autopilot_prefix(self, _sched_mod):
        assert _sched_mod._autopilot_job_id("https://x.com/").startswith("autopilot_")


# ── _keepalive_cycle_job ──────────────────────────────────────────────────────

class TestKeepaliveJobCycle:
    def test_writes_history_with_autopilot_source(self, _sched_mod):
        ok_result = MagicMock(success=True, checked=3, errors=0, error=None)
        sched_data: dict = {"autopilot_targets": {}}

        sched_store = MagicMock()
        sched_store.load.return_value = sched_data
        captured: list = []
        sched_store.update.side_effect = lambda fn: captured.append(fn(sched_data))

        hist_store = MagicMock()
        hist_entries: list = []
        hist_store.update.side_effect = lambda fn: hist_entries.append(fn([]))

        with patch.object(_sched_mod, "_sched_store", sched_store), \
             patch.object(_sched_mod, "_hist_store", hist_store), \
             patch.object(_sched_mod, "run_keepalive_for_site", return_value=ok_result):
            _sched_mod._keepalive_cycle_job("https://example.com/")

        assert len(hist_entries) >= 1
        entry = hist_entries[0][0]
        assert entry["extra_json"]["source"] == "autopilot"
        assert entry["status"] == "autopilot_ok"

    def test_sets_alert_pending_on_failure(self, _sched_mod):
        fail_result = MagicMock(success=False, checked=0, errors=0, error="timeout")
        sched_data: dict = {
            "autopilot_targets": {"https://example.com/": {"enabled": True}}
        }
        captured: list = []

        sched_store = MagicMock()
        sched_store.load.return_value = sched_data
        sched_store.update.side_effect = lambda fn: captured.append(fn(dict(sched_data)))

        hist_store = MagicMock()
        hist_store.update.side_effect = lambda fn: fn([])

        with patch.object(_sched_mod, "_sched_store", sched_store), \
             patch.object(_sched_mod, "_hist_store", hist_store), \
             patch.object(_sched_mod, "run_keepalive_for_site", return_value=fail_result):
            _sched_mod._keepalive_cycle_job("https://example.com/")

        assert len(captured) > 0
        alert = captured[-1]["autopilot_targets"]["https://example.com/"].get("alert_pending")
        assert alert is True

    def test_no_alert_on_success(self, _sched_mod):
        ok_result = MagicMock(success=True, checked=1, errors=0, error=None)
        sched_data: dict = {
            "autopilot_targets": {
                "https://example.com/": {"enabled": True, "alert_pending": True}
            }
        }
        captured: list = []

        sched_store = MagicMock()
        sched_store.load.return_value = sched_data
        sched_store.update.side_effect = lambda fn: captured.append(fn(dict(sched_data)))

        hist_store = MagicMock()
        hist_store.update.side_effect = lambda fn: fn([])

        with patch.object(_sched_mod, "_sched_store", sched_store), \
             patch.object(_sched_mod, "_hist_store", hist_store), \
             patch.object(_sched_mod, "run_keepalive_for_site", return_value=ok_result):
            _sched_mod._keepalive_cycle_job("https://example.com/")

        assert len(captured) > 0
        alert = captured[-1]["autopilot_targets"]["https://example.com/"].get("alert_pending")
        assert alert is False


# ── _restore_scheduled_jobs (autopilot extension) ─────────────────────────────

class TestRestoreScheduledJobsAutopilot:
    def test_registers_n_jobs_for_n_enabled_sites(self, _sched_mod, tmp_path):
        sched_data = {
            "autopilot_targets": {
                "https://a.com/": {"enabled": True, "interval_seconds": 3600},
                "https://b.com/": {"enabled": True, "interval_seconds": 7200},
                "https://c.com/": {"enabled": False, "interval_seconds": 3600},
            },
            "maintenance_mode": False,
        }
        sched_store = MagicMock()
        sched_store.load.return_value = sched_data

        registered: list = []
        mock_scheduler = MagicMock()
        mock_scheduler.add_job.side_effect = lambda *a, **kw: registered.append(kw.get("id"))

        with patch.object(_sched_mod, "_queue_store") as mock_q, \
             patch.object(_sched_mod, "_drafts_store") as mock_d, \
             patch.object(_sched_mod, "_batch_ops_store"), \
             patch.object(_sched_mod, "_scheduler", mock_scheduler), \
             patch.object(_sched_mod, "_sched_store", sched_store):
            mock_q.update.return_value = []
            mock_q.load.return_value = []
            mock_d.load.return_value = []
            _sched_mod._restore_scheduled_jobs()

        autopilot_ids = [j for j in registered if j and j.startswith("autopilot_")]
        assert len(autopilot_ids) == 2

    def test_skips_autopilot_under_maintenance_mode(self, _sched_mod):
        sched_data = {
            "autopilot_targets": {
                "https://a.com/": {"enabled": True, "interval_seconds": 3600},
            },
            "maintenance_mode": True,
        }
        sched_store = MagicMock()
        sched_store.load.return_value = sched_data

        registered: list = []
        mock_scheduler = MagicMock()
        mock_scheduler.add_job.side_effect = lambda *a, **kw: registered.append(kw.get("id"))

        with patch.object(_sched_mod, "_queue_store") as mock_q, \
             patch.object(_sched_mod, "_drafts_store") as mock_d, \
             patch.object(_sched_mod, "_batch_ops_store"), \
             patch.object(_sched_mod, "_scheduler", mock_scheduler), \
             patch.object(_sched_mod, "_sched_store", sched_store):
            mock_q.update.return_value = []
            mock_q.load.return_value = []
            mock_d.load.return_value = []
            _sched_mod._restore_scheduled_jobs()

        autopilot_ids = [j for j in registered if j and j.startswith("autopilot_")]
        assert len(autopilot_ids) == 0
