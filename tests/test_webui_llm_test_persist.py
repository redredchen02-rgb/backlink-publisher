"""Plan 2026-06-05-003 U2 — persist last_test to llm-settings.json.

The connection-test outcome must survive page reloads so the nav pill /
status header reflect "last known" health. Covers the pure
``record_llm_test_result`` helper (RMW preserves keys + 0o600) and the
``/api/v1/settings/llm/test-connection`` route side-effect.
"""
from __future__ import annotations

__tier__ = "unit"

import json
import os
import stat
from datetime import datetime
from unittest.mock import patch

import pytest

from webui_app.services import settings_service


@pytest.fixture
def cfg_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
    return tmp_path


def _write_settings(payload: dict) -> None:
    path = settings_service.llm_settings_file()
    path.write_text(json.dumps(payload), encoding="utf-8")
    path.chmod(0o600)


# ── record_llm_test_result helper ────────────────────────────────────────────


def test_record_ok_writes_parseable_block(cfg_dir):
    _write_settings({"endpoint": "https://api.example.com", "api_key": "k"})
    settings_service.record_llm_test_result(ok=True, message="连接成功！")

    stored = json.loads(settings_service.llm_settings_file().read_text("utf-8"))
    assert stored["last_test"]["ok"] is True
    assert stored["last_test"]["message"] == "连接成功！"
    # parseable ISO timestamp
    datetime.fromisoformat(stored["last_test"]["at"])


def test_record_failed_outcome(cfg_dir):
    _write_settings({"endpoint": "https://api.example.com", "api_key": "k"})
    settings_service.record_llm_test_result(ok=False, message="连接失败: HTTP 500")
    stored = json.loads(settings_service.llm_settings_file().read_text("utf-8"))
    assert stored["last_test"]["ok"] is False
    assert "500" in stored["last_test"]["message"]


def test_record_preserves_existing_keys(cfg_dir):
    _write_settings({
        "endpoint": "https://api.example.com",
        "api_key": "secret-key",
        "model": "gpt-4",
        "use_article_gen": True,
    })
    settings_service.record_llm_test_result(ok=True, message="ok")
    stored = json.loads(settings_service.llm_settings_file().read_text("utf-8"))
    assert stored["endpoint"] == "https://api.example.com"
    assert stored["api_key"] == "secret-key"
    assert stored["model"] == "gpt-4"
    assert stored["use_article_gen"] is True


def test_record_keeps_file_mode_0600(cfg_dir):
    _write_settings({"endpoint": "https://api.example.com", "api_key": "k"})
    settings_service.record_llm_test_result(ok=True, message="ok")
    mode = stat.S_IMODE(settings_service.llm_settings_file().stat().st_mode)
    assert mode == 0o600


def test_record_message_never_contains_api_key(cfg_dir):
    _write_settings({"endpoint": "https://api.example.com", "api_key": "sk-leak"})
    settings_service.record_llm_test_result(ok=True, message="连接成功！")
    stored = json.loads(settings_service.llm_settings_file().read_text("utf-8"))
    assert "sk-leak" not in stored["last_test"]["message"]


def test_record_absent_file_creates_valid_0600(cfg_dir):
    assert not settings_service.llm_settings_file().exists()
    settings_service.record_llm_test_result(ok=True, message="ok")
    path = settings_service.llm_settings_file()
    assert path.exists()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert json.loads(path.read_text("utf-8"))["last_test"]["ok"] is True


# ── route side-effect ────────────────────────────────────────────────────────


@pytest.fixture
def client(cfg_dir, monkeypatch):
    monkeypatch.setenv("BACKLINK_PUBLISHER_LLM_ALLOW_ANY_HOST", "1")
    from webui_app import create_app
    app = create_app()
    app.config["TESTING"] = True
    app.config["CSRF_ENABLED"] = False
    app.config["WTF_CSRF_ENABLED"] = False
    return app.test_client()


def test_route_persists_last_test_on_success(client):
    with patch("webui_app.api.llm_diagnostics_api._guard_llm_endpoint", return_value=(None, None)), \
         patch("webui_app.api.llm_diagnostics_api._safe_get_json",
               return_value=(200, {"data": [{"id": "gpt-4"}]})):
        resp = client.post("/api/v1/settings/llm/test-connection", json={
            "endpoint": "https://api.example.com/v1",
            "api_key": "sk-test",
            "model": "gpt-4",
        })
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "ok"
    stored = json.loads(settings_service.llm_settings_file().read_text("utf-8"))
    assert stored["last_test"]["ok"] is True
    datetime.fromisoformat(stored["last_test"]["at"])


def test_route_persists_failed_outcome(client):
    with patch("webui_app.api.llm_diagnostics_api._guard_llm_endpoint", return_value=(None, None)), \
         patch("webui_app.api.llm_diagnostics_api._safe_get_json", return_value=(500, {})), \
         patch("webui_app.api.llm_diagnostics_api._safe_post_json", return_value=(500, {})):
        resp = client.post("/api/v1/settings/llm/test-connection", json={
            "endpoint": "https://api.example.com/v1",
            "api_key": "sk-test",
            "model": "gpt-4",
        })
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "error"
    stored = json.loads(settings_service.llm_settings_file().read_text("utf-8"))
    assert stored["last_test"]["ok"] is False


def test_route_write_failure_does_not_break_response(client):
    """Persistence is best-effort: a record failure must not 500 the test."""
    with patch("webui_app.api.llm_diagnostics_api._guard_llm_endpoint", return_value=(None, None)), \
         patch("webui_app.api.llm_diagnostics_api._safe_get_json",
               return_value=(200, {"data": []})), \
         patch("webui_app.services.settings_service.record_llm_test_result",
               side_effect=OSError("disk full")):
        resp = client.post("/api/v1/settings/llm/test-connection", json={
            "endpoint": "https://api.example.com/v1",
            "api_key": "sk-test",
            "model": "gpt-4",
        })
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "ok"
