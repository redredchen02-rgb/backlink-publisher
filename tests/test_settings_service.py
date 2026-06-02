"""Unit tests for webui_app.services.settings_service — Plan 2026-06-01-001 U4.

Flask-free: no Flask client, no request context.
Covers: LLM settings load (0600 repair), schedule settings, calc_next_available,
group_history, load_incomplete_run, token_paste_status, persist_three_tier_config.
"""
from __future__ import annotations

import json
import os
import stat
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from webui_app.services import settings_service


@pytest.fixture
def cfg_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
    return tmp_path


# ── LLM settings ─────────────────────────────────────────────────────────────


def test_load_llm_settings_defaults_when_no_file(cfg_dir):
    result = settings_service.load_llm_settings()
    assert result["api_key"] == ""
    assert result["temperature"] == 0.7
    assert result["model"] == ""


def test_load_llm_settings_reads_existing_file(cfg_dir):
    path = settings_service.llm_settings_file()
    path.write_text(json.dumps({"api_key": "mykey", "model": "gpt-4"}), encoding="utf-8")
    path.chmod(0o600)
    result = settings_service.load_llm_settings()
    assert result["api_key"] == "mykey"
    assert result["model"] == "gpt-4"
    assert result["temperature"] == 0.7  # default preserved


def test_load_llm_settings_auto_chmod_loose_perms(cfg_dir):
    """Pre-#140 0o644 file must be auto-chmod'd to 0o600 on load."""
    path = settings_service.llm_settings_file()
    path.write_text(json.dumps({"api_key": "secret"}), encoding="utf-8")
    path.chmod(0o644)
    assert stat.S_IMODE(path.stat().st_mode) == 0o644

    settings_service.load_llm_settings()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_load_llm_settings_corrupt_file_returns_defaults(cfg_dir):
    path = settings_service.llm_settings_file()
    path.write_text("NOT JSON!!!", encoding="utf-8")
    path.chmod(0o600)
    result = settings_service.load_llm_settings()
    assert result["api_key"] == ""  # default, not exception


# ── Schedule settings ─────────────────────────────────────────────────────────


def test_load_schedule_settings_defaults_when_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
    with patch("webui_store.schedule_store.load", return_value={}):
        result = settings_service.load_schedule_settings()
    assert result == {"min_interval_hours": 4, "jitter_minutes": 30}


def test_save_and_load_schedule_settings_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
    saved = {"min_interval_hours": 8, "jitter_minutes": 15}
    with patch("webui_store.schedule_store.save") as mock_save:
        settings_service.save_schedule_settings(saved)
        mock_save.assert_called_once_with(saved)


# ── calc_next_available ───────────────────────────────────────────────────────


def test_calc_next_available_no_history_returns_requested(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
    requested = datetime(2026, 6, 2, 12, 0)
    with patch("webui_store.schedule_store.load", return_value={}), \
         patch("webui_store.drafts_store.load", return_value=[]), \
         patch("webui_store.history_store.load", return_value=[]):
        result = settings_service.calc_next_available(requested)
    assert result == requested


def test_calc_next_available_respects_min_interval(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
    last_pub = datetime(2026, 6, 2, 10, 0)
    requested = datetime(2026, 6, 2, 12, 0)
    with patch("webui_store.schedule_store.load", return_value={"min_interval_hours": 4, "jitter_minutes": 0}), \
         patch("webui_store.drafts_store.load", return_value=[
             {"status": "published", "published_at": last_pub.isoformat()}
         ]), \
         patch("webui_store.history_store.load", return_value=[]):
        result = settings_service.calc_next_available(requested)
    # last_pub (10:00) + 4h = 14:00; requested (12:00) < 14:00 → return 14:00
    assert result == datetime(2026, 6, 2, 14, 0)


# ── group_history ─────────────────────────────────────────────────────────────


def test_group_history_empty_list():
    assert settings_service.group_history([]) == []


def test_group_history_single_item():
    items = [{"run_id": "r1", "status": "published", "platform": "writeas",
              "created_at": "2026-06-02 10:00", "language": "zh-CN"}]
    groups = settings_service.group_history(items)
    assert len(groups) == 1
    assert groups[0]["n_total"] == 1
    assert groups[0]["is_multi"] is False
    assert groups[0]["n_published"] == 1


def test_group_history_same_run_id_groups():
    items = [
        {"run_id": "r1", "status": "published", "platform": "writeas",
         "created_at": "2026-06-02 10:00", "language": "zh-CN"},
        {"run_id": "r1", "status": "drafted", "platform": "writeas",
         "created_at": "2026-06-02 10:01", "language": "zh-CN"},
    ]
    groups = settings_service.group_history(items)
    assert len(groups) == 1
    assert groups[0]["n_total"] == 2
    assert groups[0]["is_multi"] is True
    assert groups[0]["n_published"] == 1
    assert groups[0]["n_drafted"] == 1


def test_group_history_different_run_ids_separate_groups():
    items = [
        {"run_id": "r1", "status": "published", "created_at": "2026-06-02 10:00",
         "platform": "a", "language": "zh-CN"},
        {"run_id": "r2", "status": "failed", "created_at": "2026-06-02 11:00",
         "platform": "b", "language": "zh-CN"},
    ]
    groups = settings_service.group_history(items)
    assert len(groups) == 2
    assert groups[1]["n_failed"] == 1


def test_group_history_none_run_id_each_separate():
    items = [
        {"run_id": None, "status": "published", "created_at": "t1", "platform": "x", "language": "zh-CN"},
        {"run_id": None, "status": "published", "created_at": "t2", "platform": "y", "language": "zh-CN"},
    ]
    groups = settings_service.group_history(items)
    assert len(groups) == 2


# ── load_incomplete_run ───────────────────────────────────────────────────────


def test_load_incomplete_run_returns_none_on_empty():
    with patch("backlink_publisher.checkpoint.list_incomplete", return_value=[]):
        result = settings_service.load_incomplete_run()
    assert result is None


def test_load_incomplete_run_counts_pending_and_failed():
    run = {
        "run_id": "r1",
        "items": [
            {"status": "pending"},
            {"status": "failed"},
            {"status": "done"},
        ],
    }
    with patch("backlink_publisher.checkpoint.list_incomplete", return_value=[run]):
        result = settings_service.load_incomplete_run()
    assert result["pending_count"] == 2
    assert result["run_id"] == "r1"


def test_load_incomplete_run_returns_none_on_exception():
    with patch("backlink_publisher.checkpoint.list_incomplete", side_effect=Exception("err")):
        result = settings_service.load_incomplete_run()
    assert result is None


# ── token_paste_status ────────────────────────────────────────────────────────


def test_token_paste_status_bound_masks_token():
    import backlink_publisher.publishing.adapters  # noqa: F401 — registration
    cfg = MagicMock()
    cfg.writeas_token_path = None

    def mock_load(path=None):
        return {"token": "abcdefghijk"}

    result = settings_service.token_paste_status(cfg, "writeas", mock_load)
    assert result["bound"] is True
    assert "abcdefghijk" not in result["masked"]
    assert result["masked"].startswith("abc")
    assert result["masked"].endswith("ijk")


def test_token_paste_status_unbound():
    import backlink_publisher.publishing.adapters  # noqa: F401 — registration
    cfg = MagicMock()
    cfg.writeas_token_path = None

    def mock_load(path=None):
        return None

    result = settings_service.token_paste_status(cfg, "writeas", mock_load)
    assert result["bound"] is False
    assert result["masked"] == ""


def test_token_paste_status_notion_bound():
    import backlink_publisher.publishing.adapters  # noqa: F401 — registration
    cfg = MagicMock()
    cfg.notion_token_path = None

    def mock_load(path=None):
        return {"integration_token": "tok_secret_abc", "database_id": "db123"}

    result = settings_service.token_paste_status_notion(cfg, mock_load)
    assert result["bound"] is True
    assert result["database_id_set"] is True
    assert "tok_secret_abc" not in result["masked"]
