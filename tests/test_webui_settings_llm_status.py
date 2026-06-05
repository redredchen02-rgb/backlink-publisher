"""Plan 2026-06-05-003 U5 — settings #pane-llm status header.

Renders /settings under each pro_status state and asserts the status line plus
the "解锁清单" checklist (✓ active / ○ inactive) reflect live pro_status.
"""
from __future__ import annotations

__tier__ = "unit"

import json

import pytest

from webui_app.services import settings_service


@pytest.fixture
def cfg_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
    monkeypatch.delenv("BACKLINK_PUBLISHER_LITE", raising=False)
    return tmp_path


def _write_llm(payload: dict) -> None:
    path = settings_service.llm_settings_file()
    path.write_text(json.dumps(payload), encoding="utf-8")
    path.chmod(0o600)


def _settings_html(cfg_dir):
    from webui_app import create_app
    app = create_app()
    app.config["TESTING"] = True
    app.config["CSRF_ENABLED"] = False
    app.config["WTF_CSRF_ENABLED"] = False
    resp = app.test_client().get("/settings")
    assert resp.status_code == 200
    return resp.get_data(as_text=True)


def test_header_healthy_shows_enabled_and_checks(cfg_dir):
    _write_llm({
        "endpoint": "https://api.example.com/v1", "api_key": "sk-x",
        "model": "gpt-4", "use_article_gen": True, "use_image_gen": True,
        "last_test": {"ok": True, "at": "2026-06-05T10:00:00", "message": "ok"},
    })
    html = _settings_html(cfg_dir)
    assert "已启用" in html
    assert "✓ AI 全文生成" in html
    assert "✓ Copilot 智能问答" in html


def test_header_image_gen_off_shows_circle_on_cover_row(cfg_dir):
    _write_llm({
        "endpoint": "https://api.example.com/v1", "api_key": "sk-x",
        "model": "gpt-4", "use_article_gen": True, "use_image_gen": False,
        "last_test": {"ok": True, "at": "2026-06-05T10:00:00", "message": "ok"},
    })
    html = _settings_html(cfg_dir)
    assert "✓ AI 全文生成" in html
    assert "○ AI 封面图" in html


def test_header_unconfigured_all_circles_and_hint(cfg_dir):
    html = _settings_html(cfg_dir)
    assert "未启用" in html
    assert "○ AI 全文生成" in html
    assert "○ Copilot 智能问答" in html
    assert "○ 锚文本智能建议" in html


def test_header_pending_failed_test_shows_retry_hint(cfg_dir):
    _write_llm({
        "endpoint": "https://api.example.com/v1", "api_key": "sk-x",
        "model": "gpt-4", "use_article_gen": True,
        "last_test": {"ok": False, "at": "2026-06-05T10:00:00", "message": "HTTP 500"},
    })
    html = _settings_html(cfg_dir)
    assert "待激活" in html
    assert "测试连接" in html


def test_header_never_renders_api_key(cfg_dir):
    secret = "sk-status-secret"
    _write_llm({
        "endpoint": "https://api.example.com/v1", "api_key": secret,
        "model": "gpt-4", "use_article_gen": True,
    })
    html = _settings_html(cfg_dir)
    assert secret not in html
    # configured + article_gen but no last_test → pending with a verify hint
    assert "待激活" in html
    assert "测试连接" in html
