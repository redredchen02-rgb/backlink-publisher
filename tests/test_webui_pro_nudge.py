"""Plan 2026-06-05-003 U4 — index activation nudge.

Renders the 发布 (index) page under each pro_status state and asserts the
dismissible activation nudge appears only when AI generation is not active,
deep-links to the Pro pane, and wires dismissal via data-action (no inline on*).
"""
from __future__ import annotations

__tier__ = "unit"

import json
from pathlib import Path

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


def _index_html(cfg_dir):
    from webui_app import create_app
    app = create_app()
    app.config["TESTING"] = True
    app.config["CSRF_ENABLED"] = False
    app.config["WTF_CSRF_ENABLED"] = False
    resp = app.test_client().get("/jinja")
    assert resp.status_code == 200
    return resp.get_data(as_text=True)


def test_nudge_bind_variant_when_unconfigured(cfg_dir):
    html = _index_html(cfg_dir)
    assert 'id="pro-activation-nudge"' in html
    assert "去绑定" in html
    assert 'href="/settings#pane-llm"' in html
    assert 'data-nudge-state="unconfigured"' in html


def test_nudge_enable_variant_when_article_gen_off(cfg_dir):
    _write_llm({
        "endpoint": "https://api.example.com/v1", "api_key": "sk-x",
        "model": "gpt-4", "use_article_gen": False,
    })
    html = _index_html(cfg_dir)
    assert 'id="pro-activation-nudge"' in html
    assert "开启全文生成" in html
    assert 'data-nudge-state="gen-off"' in html


def test_nudge_absent_when_healthy(cfg_dir):
    _write_llm({
        "endpoint": "https://api.example.com/v1", "api_key": "sk-x",
        "model": "gpt-4", "use_article_gen": True,
        "last_test": {"ok": True, "at": "2026-06-05T10:00:00", "message": "ok"},
    })
    html = _index_html(cfg_dir)
    assert 'id="pro-activation-nudge"' not in html


def test_nudge_dismiss_uses_data_action_not_inline_handler(cfg_dir):
    html = _index_html(cfg_dir)
    assert 'data-action="pro-nudge-dismiss"' in html
    # extract the nudge markup and assert no inline on* handler
    start = html.index('id="pro-activation-nudge"')
    snippet = html[start:start + 1200]
    assert "onclick" not in snippet.lower()


def test_index_js_registers_dismiss_handler():
    js = Path("webui_app/static/js/index.js").read_text(encoding="utf-8")
    assert "'pro-nudge-dismiss'" in js
    assert "_initProNudge" in js
    assert "proNudgeDismissed" in js
