"""Plan 2026-06-05-003 U3 — global-nav Pro status pill.

Renders a base-extending page (/settings) under each pro_status state and
asserts the three-state pill, the LITE gate, and api_key non-leakage.
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


def _client():
    from webui_app import create_app
    app = create_app()
    app.config["TESTING"] = True
    app.config["CSRF_ENABLED"] = False
    app.config["WTF_CSRF_ENABLED"] = False
    return app.test_client()


def _nav_html(cfg_dir):
    html = _client().get("/settings").get_data(as_text=True)
    # Console shell (Plan 2026-06-17-001 U2): topbar hosts the Pro pill.
    assert "app-topbar" in html
    return html


def test_healthy_state_renders_green_pill(cfg_dir):
    _write_llm({
        "endpoint": "https://api.example.com/v1", "api_key": "sk-x",
        "model": "gpt-4", "use_article_gen": True,
        "last_test": {"ok": True, "at": "2026-06-05T10:00:00", "message": "ok"},
    })
    html = _nav_html(cfg_dir)
    assert "global-nav__pro--healthy" in html
    assert "✦ Pro 已启用" in html


def test_pending_when_article_gen_off(cfg_dir):
    _write_llm({
        "endpoint": "https://api.example.com/v1", "api_key": "sk-x",
        "model": "gpt-4", "use_article_gen": False,
        "last_test": {"ok": True, "at": "2026-06-05T10:00:00", "message": "ok"},
    })
    html = _nav_html(cfg_dir)
    assert "global-nav__pro--pending" in html
    assert "Pro 待激活" in html


def test_pending_when_no_test_yet(cfg_dir):
    _write_llm({
        "endpoint": "https://api.example.com/v1", "api_key": "sk-x",
        "model": "gpt-4", "use_article_gen": True,
    })
    html = _nav_html(cfg_dir)
    assert "global-nav__pro--pending" in html


def test_inactive_when_unconfigured(cfg_dir):
    html = _nav_html(cfg_dir)
    assert "global-nav__pro--inactive" in html
    assert "启用 Pro" in html
    assert 'href="/settings#pane-llm"' in html


def test_pill_hidden_in_lite_edition(cfg_dir, monkeypatch):
    monkeypatch.setenv("BACKLINK_PUBLISHER_LITE", "1")
    _write_llm({
        "endpoint": "https://api.example.com/v1", "api_key": "sk-x",
        "model": "gpt-4", "use_article_gen": True,
        "last_test": {"ok": True, "at": "2026-06-05T10:00:00", "message": "ok"},
    })
    html = _nav_html(cfg_dir)
    assert "global-nav__pro" not in html


def test_pill_never_renders_api_key(cfg_dir):
    secret = "sk-super-secret-pill"
    _write_llm({
        "endpoint": "https://api.example.com/v1", "api_key": secret,
        "model": "gpt-4", "use_article_gen": True,
        "last_test": {"ok": True, "at": "2026-06-05T10:00:00", "message": "ok"},
    })
    html = _nav_html(cfg_dir)
    assert secret not in html
